from __future__ import annotations

import asyncio
import time
from pathlib import Path

import aiohttp
from telegram import Bot

from app.services.progress import ProgressReporter
from app.utils import human_bytes

LOCAL_STORAGE_DIR = Path("/var/lib/telegram-bot-api")


async def _wait_for_local_file(path: Path, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if path.exists():
            return True
        await asyncio.sleep(0.2)
    return path.exists()


async def _copy_local_file(src_path: Path, dest_path: Path, progress: ProgressReporter) -> int:
    total = src_path.stat().st_size
    downloaded = 0
    start = time.monotonic()

    with src_path.open("rb") as src, dest_path.open("wb") as dst:
        while True:
            chunk = await asyncio.to_thread(src.read, 1024 * 1024)
            if not chunk:
                break
            dst.write(chunk)
            downloaded += len(chunk)
            elapsed = max(time.monotonic() - start, 0.01)
            speed = downloaded / elapsed
            percent = downloaded / total * 100.0 if total else 0.0
            speed_mb = speed / (1024 * 1024)
            detail = f"{human_bytes(downloaded)}/{human_bytes(total)} at {speed_mb:.2f} MB/s"
            await progress.update("⬇️ Downloading ZIP", percent, detail)

    await progress.update("⬇️ Downloading ZIP", 100.0, "Download complete", force=True)
    return downloaded


async def download_file(
    bot: Bot,
    file_id: str,
    dest_path: Path,
    progress: ProgressReporter,
) -> int:
    tg_file = await bot.get_file(file_id)
    file_path = tg_file.file_path
    if not file_path:
        raise RuntimeError("Missing file path from Telegram")

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # Local Bot API returns absolute paths in local mode
    src_path = Path(file_path)
    if src_path.is_absolute() and LOCAL_STORAGE_DIR in src_path.parents:
        if await _wait_for_local_file(src_path):
            return await _copy_local_file(src_path, dest_path, progress)
        raise RuntimeError(f"Local file not found: {src_path}")

    if file_path.startswith("http://") or file_path.startswith("https://"):
        url = file_path
    else:
        base = bot.base_file_url or ""
        base = base.rstrip("/")
        url = f"{base}/{file_path.lstrip('/')}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            total = resp.content_length or 0
            downloaded = 0
            start = time.monotonic()

            with dest_path.open("wb") as f:
                async for chunk in resp.content.iter_chunked(1024 * 1024):
                    f.write(chunk)
                    downloaded += len(chunk)
                    elapsed = max(time.monotonic() - start, 0.01)
                    speed = downloaded / elapsed
                    if total:
                        percent = downloaded / total * 100.0
                        speed_mb = speed / (1024 * 1024)
                        detail = (
                            f"{human_bytes(downloaded)}/{human_bytes(total)} "
                            f"at {speed_mb:.2f} MB/s"
                        )
                        await progress.update("⬇️ Downloading ZIP", percent, detail)
                    else:
                        detail = f"{human_bytes(downloaded)} downloaded"
                        await progress.update_indeterminate("⬇️ Downloading ZIP", detail)

    await progress.update("⬇️ Downloading ZIP", 100.0, "Download complete", force=True)
    return downloaded
