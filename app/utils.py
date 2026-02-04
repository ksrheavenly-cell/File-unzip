from __future__ import annotations

import asyncio
import mimetypes
import os
from pathlib import Path
from typing import Iterable, List

from telegram.error import NetworkError, RetryAfter, TelegramError, TimedOut

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".3gp"}
ZIP_MIME_TYPES = {"application/zip", "application/x-zip-compressed"}


def is_zip_file(filename: str | None, mime_type: str | None) -> bool:
    if mime_type and mime_type in ZIP_MIME_TYPES:
        return True
    if not filename:
        return False
    return filename.lower().endswith(".zip")


def is_photo(path: Path) -> bool:
    return path.suffix.lower() in PHOTO_EXTENSIONS


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def chunked(items: Iterable, size: int) -> List[list]:
    batch = []
    out = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            out.append(batch)
            batch = []
    if batch:
        out.append(batch)
    return out


def human_bytes(num_bytes: int) -> str:
    step = 1024.0
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < step:
            return f"{size:.1f} {unit}"
        size /= step
    return f"{size:.1f} PB"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    return mime or "application/octet-stream"


async def telegram_retry(func, *args, max_attempts: int = 5, **kwargs):
    for attempt in range(max_attempts):
        try:
            return await func(*args, **kwargs)
        except RetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
        except (TimedOut, NetworkError):
            await asyncio.sleep(1 + attempt)
        except TelegramError:
            if attempt >= max_attempts - 1:
                raise
            await asyncio.sleep(1 + attempt)


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    mins, sec = divmod(seconds, 60)
    hrs, mins = divmod(mins, 60)
    if hrs:
        return f"{hrs}h {mins}m {sec}s"
    if mins:
        return f"{mins}m {sec}s"
    return f"{sec}s"


def safe_filename(name: str) -> str:
    base = os.path.basename(name)
    return base.replace("\n", " ").replace("\r", " ")
