from __future__ import annotations

from pathlib import Path

from telegram import InputMediaPhoto
from telegram.error import TelegramError

from app.services.progress import ProgressReporter
from app.utils import chunked, is_photo, is_video, telegram_retry


def _collect_files(root_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root_dir.rglob("*")):
        if path.is_file():
            files.append(path)
    return files


async def _send_photos(bot, chat_id: int, photos: list[Path], album_size: int, progress: ProgressReporter, sent: int, total: int) -> int:
    for group in chunked(photos, album_size):
        handles = [p.open("rb") for p in group]
        media = []
        for idx, handle in enumerate(handles):
            caption = group[idx].name if idx == 0 else None
            media.append(InputMediaPhoto(media=handle, caption=caption))
        try:
            await telegram_retry(bot.send_media_group, chat_id=chat_id, media=media)
        except TelegramError:
            for path in group:
                with path.open("rb") as handle:
                    await telegram_retry(bot.send_document, chat_id=chat_id, document=handle)
        finally:
            for handle in handles:
                handle.close()
        sent += len(group)
        percent = sent / total * 100.0 if total else 100.0
        await progress.update(f"📤 Sending files ({sent} / {total})", percent, None)
    return sent


async def _send_video(bot, chat_id: int, path: Path) -> None:
    try:
        with path.open("rb") as handle:
            await telegram_retry(
                bot.send_video,
                chat_id=chat_id,
                video=handle,
                supports_streaming=True,
            )
    except TelegramError:
        with path.open("rb") as handle:
            await telegram_retry(bot.send_document, chat_id=chat_id, document=handle)


async def _send_document(bot, chat_id: int, path: Path) -> None:
    with path.open("rb") as handle:
        await telegram_retry(bot.send_document, chat_id=chat_id, document=handle)


async def send_all(bot, chat_id: int, root_dir: Path, album_size: int, progress: ProgressReporter) -> None:
    files = _collect_files(root_dir)
    total = len(files)
    if total == 0:
        await progress.update("📤 Sending files (0 / 0)", 100.0, "No files to send", force=True)
        return

    photos = [p for p in files if is_photo(p)]
    videos = [p for p in files if is_video(p)]
    others = [p for p in files if p not in photos and p not in videos]

    sent = 0
    if photos:
        sent = await _send_photos(bot, chat_id, photos, album_size, progress, sent, total)

    for path in videos:
        await _send_video(bot, chat_id, path)
        sent += 1
        percent = sent / total * 100.0
        await progress.update(f"📤 Sending files ({sent} / {total})", percent, None)

    for path in others:
        await _send_document(bot, chat_id, path)
        sent += 1
        percent = sent / total * 100.0
        await progress.update(f"📤 Sending files ({sent} / {total})", percent, None)

    await progress.update(f"📤 Sending files ({sent} / {total})", 100.0, None, force=True)
