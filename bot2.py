import asyncio
import io
import math
import nest_asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

def human_readable_size(size_bytes: int) -> str:
    """Convert file size in bytes to a human-readable string."""
    if size_bytes is None:
        return "Unknown"
    if size_bytes == 0:
        return "0 B"
    size_names = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_names[i]}"

def get_video_quality(height: int) -> str:
    """Estimate video quality based on its height."""
    if height <= 144:
        return "144p"
    elif height <= 240:
        return "240p"
    elif height <= 360:
        return "360p"
    elif height <= 480:
        return "480p"
    elif height <= 720:
        return "720p"
    elif height <= 1080:
        return "1080p"
    else:
        return "HD"

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    caption_info = ""
    thumb = None  # Placeholder for thumbnail

    # Default file name fallback: use file_unique_id if available.
    def get_name(media, default_label: str) -> str:
        # If media has file_name, use it; otherwise use file_unique_id.
        return getattr(media, "file_name", None) or getattr(media, "file_unique_id", default_label)

    # Process Photo messages
    if message.photo:
        photo = message.photo[-1]  # use largest for info
        name = get_name(photo, "Photo")
        caption_info = (
            f"<code>Type       : Photo</code>\n"
            f"<code>Name       : {name}</code>\n"
            f"<code>File Size  : {human_readable_size(photo.file_size)}</code>\n"
            f"<code>Dimensions : {photo.width} x {photo.height}</code>"
        )
        # Use a lower resolution version as a thumbnail.
        thumb = message.photo[0]

    # Process Video messages
    elif message.video:
        video = message.video
        name = get_name(video, "Video")
        caption_info = (
            f"<code>Type       : Video</code>\n"
            f"<code>Name       : {name}</code>\n"
            f"<code>File Size  : {human_readable_size(video.file_size)}</code>\n"
            f"<code>Dimensions : {video.width} x {video.height}</code>\n"
            f"<code>Quality    : {get_video_quality(video.height)}</code>"
        )
        if video.thumb:
            thumb = video.thumb

    # Process Document messages
    elif message.document:
        document = message.document
        name = get_name(document, "Document")
        caption_info = (
            f"<code>Type       : Document</code>\n"
            f"<code>Name       : {name}</code>\n"
            f"<code>File Size  : {human_readable_size(document.file_size)}</code>"
        )
        if document.thumb:
            thumb = document.thumb

    # Process Voice messages
    elif message.voice:
        voice = message.voice
        name = get_name(voice, "Voice")
        caption_info = (
            f"<code>Type       : Voice Note</code>\n"
            f"<code>Name       : {name}</code>\n"
            f"<code>File Size  : {human_readable_size(voice.file_size)}</code>\n"
            f"<code>Duration   : {voice.duration} sec</code>"
        )

    # Process Video Note messages
    elif message.video_note:
        video_note = message.video_note
        name = get_name(video_note, "Video Note")
        caption_info = (
            f"<code>Type       : Video Note</code>\n"
            f"<code>Name       : {name}</code>\n"
            f"<code>File Size  : {human_readable_size(video_note.file_size)}</code>\n"
            f"<code>Dimensions : {video_note.length} x {video_note.length}</code>"
        )
        if video_note.thumb:
            thumb = video_note.thumb

    # Process Stickers
    elif message.sticker:
        sticker = message.sticker
        name = get_name(sticker, "Sticker")
        caption_info = (
            f"<code>Type       : Sticker</code>\n"
            f"<code>Name       : {name}</code>\n"
            f"<code>File Size  : {human_readable_size(sticker.file_size)}</code>\n"
            f"<code>Dimensions : {sticker.width} x {sticker.height}</code>"
        )
        thumb = sticker

    # Send reply using the original message as a reply.
    if thumb:
        try:
            # Download the thumbnail into memory.
            file_obj = await thumb.get_file()
            file_bytes = io.BytesIO(await file_obj.download_as_bytearray())
            file_bytes.seek(0)
            await message.reply_photo(
                photo=file_bytes, 
                caption=caption_info,
                parse_mode="HTML",
                reply_to_message_id=message.message_id
            )
        except Exception as e:
            await message.reply_text(
                caption_info + "\n\n(Thumbnail unavailable)",
                parse_mode="HTML",
                reply_to_message_id=message.message_id
            )
    else:
        await message.reply_text(
            caption_info,
            parse_mode="HTML",
            reply_to_message_id=message.message_id
        )

async def main():
    nest_asyncio.apply()
    app = ApplicationBuilder().token("7777781337:AAFPK7Wvd0vCFsSr33ZDy8J85ySRNCGmJR0").build()
    app.add_handler(MessageHandler(filters.ALL, handle_media))
    await app.run_polling()

if __name__ == '__main__':
    asyncio.run(main())
