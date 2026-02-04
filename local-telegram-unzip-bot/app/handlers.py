from __future__ import annotations

import logging
import shutil
import time
import uuid
from pathlib import Path

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes, MessageHandler, filters

from app.config import Config
from app.services.cleanup import cleanup_job, cleanup_old_jobs
from app.services.downloader import download_file
from app.services.extractor import (
    CorruptArchive,
    ExtractionError,
    PasswordRequired,
    SafetyBlocked,
    WrongPassword,
    check_disk_space,
    extract_archive,
    inspect_archive,
    validate_archive,
)
from app.services.progress import ProgressReporter
from app.services.sender import send_all
from app.utils import (
    ensure_dir,
    format_duration,
    human_bytes,
    is_zip_file,
    safe_filename,
)

logger = logging.getLogger(__name__)


def _get_config(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.application.bot_data["config"]


def _is_admin(update: Update, config: Config) -> bool:
    user = update.effective_user
    return bool(user and user.id == config.admin_id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "Send me a ZIP file and I will extract it and send the contents back."
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "Upload a ZIP (up to the configured limit). If it is password-protected, I will ask for the password."
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.document or not message.from_user:
        return

    config = _get_config(context)
    if context.user_data.get("pending_job"):
        await message.reply_text("You have a pending password request. Reply with the password first.")
        return

    document = message.document
    filename = safe_filename(document.file_name or "archive.zip")

    if not is_zip_file(filename, document.mime_type):
        await message.reply_text("Not a ZIP file. Please send a .zip archive.")
        return

    if document.file_size and document.file_size > config.max_zip_bytes:
        await message.reply_text(
            f"File too large. Limit is {config.max_zip_gb} GB."
        )
        return

    job_id = uuid.uuid4().hex
    job_dir = config.work_dir / str(message.from_user.id) / job_id
    ensure_dir(job_dir)
    zip_path = job_dir / filename
    extract_dir = job_dir / "extracted"

    progress_msg = await message.reply_text("⏳ Processing started...", quote=True)
    progress = ProgressReporter(
        bot=context.bot,
        chat_id=message.chat_id,
        message_id=progress_msg.message_id,
    )

    active_jobs = context.application.bot_data.setdefault("active_jobs", set())
    active_jobs.add(job_dir)

    pending_password = False
    try:
        await progress.update("⬇️ Downloading ZIP", 0.0, "Starting", force=True)
        downloaded = await download_file(context.bot, document.file_id, zip_path, progress)
        if downloaded > config.max_zip_bytes:
            await progress.fail(f"File too large ({config.max_zip_gb} GB limit)")
            await message.reply_text(
                f"File too large. Limit is {config.max_zip_gb} GB."
            )
            return

        await progress.update("📦 Extracting files", 0.0, "Inspecting archive", force=True)
        needs_inspection = False
        try:
            info = await inspect_archive(zip_path)
        except PasswordRequired:
            info = None
            needs_inspection = True

        if info:
            validate_archive(
                info,
                zip_size=downloaded,
                max_files=config.max_files,
                max_total=config.max_extracted_bytes,
                max_ratio=config.max_expansion_ratio,
            )
            check_disk_space(config.work_dir, info.total_size)

        if needs_inspection or (info and info.encrypted):
            await progress.update(
                "🔐 Password required",
                0.0,
                "Reply with the password for this ZIP",
                force=True,
            )
            await message.reply_text(
                "This ZIP is password-protected. Reply with the password to continue."
            )
            context.user_data["pending_job"] = {
                "job_dir": str(job_dir),
                "zip_path": str(zip_path),
                "extract_dir": str(extract_dir),
                "progress_message_id": progress_msg.message_id,
                "attempts": 0,
                "file_count": info.file_count if info else None,
                "needs_inspection": needs_inspection,
            }
            pending_password = True
            return

        ensure_dir(extract_dir)
        await extract_archive(zip_path, extract_dir, None, progress)

        await progress.update("📤 Sending files", 0.0, "Starting", force=True)
        await send_all(context.bot, message.chat_id, extract_dir, config.photo_album_size, progress)
        await progress.success()
    except SafetyBlocked as exc:
        await progress.fail(str(exc))
        await message.reply_text(f"Safety blocked: {exc}")
    except PasswordRequired:
        await progress.fail("Password required")
        await message.reply_text("This ZIP is password-protected. Please resend with a password.")
    except WrongPassword:
        await progress.fail("Wrong password")
        await message.reply_text("Wrong password. Please try again.")
    except CorruptArchive:
        await progress.fail("Corrupted or unsupported ZIP archive")
        await message.reply_text("Corrupted or unsupported ZIP archive.")
    except ExtractionError as exc:
        logger.exception("Extraction error")
        await progress.fail(f"Extraction failed: {exc}")
        await message.reply_text(f"Extraction failed: {exc}")
    except Exception:
        logger.exception("Unexpected error")
        await progress.fail("Unexpected error")
        await message.reply_text("Unexpected error while processing the ZIP.")
    finally:
        if not pending_password:
            cleanup_job(job_dir)
            active_jobs.discard(job_dir)


async def handle_password_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.text or not message.from_user:
        return

    job = context.user_data.get("pending_job")
    if not job:
        return

    password = message.text.strip()
    if not password:
        await message.reply_text("Password cannot be empty. Try again.")
        return

    config = _get_config(context)
    job_dir = Path(job["job_dir"])
    zip_path = Path(job["zip_path"])
    extract_dir = Path(job["extract_dir"])

    if not zip_path.exists():
        context.user_data.pop("pending_job", None)
        await message.reply_text("The pending job has expired. Please resend the ZIP.")
        return

    progress = ProgressReporter(
        bot=context.bot,
        chat_id=message.chat_id,
        message_id=job["progress_message_id"],
    )

    active_jobs = context.application.bot_data.setdefault("active_jobs", set())
    active_jobs.add(job_dir)

    try:
        if job.get("needs_inspection"):
            await progress.update("📦 Extracting files", 0.0, "Inspecting archive", force=True)
            info = await inspect_archive(zip_path, password=password)
            validate_archive(
                info,
                zip_size=zip_path.stat().st_size,
                max_files=config.max_files,
                max_total=config.max_extracted_bytes,
                max_ratio=config.max_expansion_ratio,
            )
            check_disk_space(config.work_dir, info.total_size)

        ensure_dir(extract_dir)
        await extract_archive(zip_path, extract_dir, password, progress)

        await progress.update("📤 Sending files", 0.0, "Starting", force=True)
        await send_all(context.bot, message.chat_id, extract_dir, config.photo_album_size, progress)
        await progress.success()

        context.user_data.pop("pending_job", None)
        cleanup_job(job_dir)
        active_jobs.discard(job_dir)
    except WrongPassword:
        job["attempts"] += 1
        if job["attempts"] >= 3:
            context.user_data.pop("pending_job", None)
            cleanup_job(job_dir)
            active_jobs.discard(job_dir)
            await progress.fail("Wrong password (too many attempts)")
            await message.reply_text("Wrong password too many times. Job cancelled.")
        else:
            await message.reply_text("Wrong password. Try again.")
    except CorruptArchive:
        context.user_data.pop("pending_job", None)
        cleanup_job(job_dir)
        active_jobs.discard(job_dir)
        await progress.fail("Corrupted or unsupported ZIP archive")
        await message.reply_text("Corrupted or unsupported ZIP archive.")
    except SafetyBlocked as exc:
        await progress.fail(str(exc))
        context.user_data.pop("pending_job", None)
        cleanup_job(job_dir)
        active_jobs.discard(job_dir)
        await message.reply_text(f"Safety blocked: {exc}")
    except Exception:
        logger.exception("Unexpected error in password flow")
        await progress.fail("Unexpected error")
        context.user_data.pop("pending_job", None)
        cleanup_job(job_dir)
        active_jobs.discard(job_dir)
        await message.reply_text("Unexpected error while processing the ZIP.")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    config = _get_config(context)
    if not _is_admin(update, config):
        await update.message.reply_text("Admin only command.")
        return

    free = shutil.disk_usage(config.work_dir)
    uptime = format_duration(time.time() - context.application.bot_data.get("start_time", time.time()))
    active_jobs = len(context.application.bot_data.get("active_jobs", set()))

    await update.message.reply_text(
        "Status\n"
        f"Uptime: {uptime}\n"
        f"Disk free: {human_bytes(free.free)}\n"
        f"Disk used: {human_bytes(free.used)}\n"
        f"Active jobs: {active_jobs}"
    )


async def limits_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    config = _get_config(context)
    if not _is_admin(update, config):
        await update.message.reply_text("Admin only command.")
        return

    await update.message.reply_text(
        "Limits\n"
        f"MAX_ZIP_GB={config.max_zip_gb}\n"
        f"MAX_EXTRACTED_GB={config.max_extracted_gb}\n"
        f"MAX_FILES={config.max_files}\n"
        f"MAX_EXPANSION_RATIO={config.max_expansion_ratio}\n"
        f"PHOTO_ALBUM_SIZE={config.photo_album_size}\n"
        f"CLEANUP_TTL_MINUTES={config.cleanup_ttl_minutes}"
    )


async def setlimits_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    config = _get_config(context)
    if not _is_admin(update, config):
        await update.message.reply_text("Admin only command.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /setlimits KEY=VALUE ...")
        return

    errors = []
    for token in context.args:
        if "=" not in token:
            errors.append(f"Invalid token: {token}")
            continue
        key, value = token.split("=", 1)
        key = key.upper()
        try:
            if key == "MAX_ZIP_GB":
                config.max_zip_gb = float(value)
            elif key == "MAX_EXTRACTED_GB":
                config.max_extracted_gb = float(value)
            elif key == "MAX_FILES":
                config.max_files = int(value)
            elif key == "MAX_EXPANSION_RATIO":
                config.max_expansion_ratio = int(value)
            elif key == "PHOTO_ALBUM_SIZE":
                config.photo_album_size = int(value)
            elif key == "CLEANUP_TTL_MINUTES":
                config.cleanup_ttl_minutes = int(value)
            else:
                errors.append(f"Unknown key: {key}")
        except ValueError:
            errors.append(f"Invalid value for {key}: {value}")

    if config.max_zip_gb <= 0 or config.max_extracted_gb <= 0:
        errors.append("MAX_ZIP_GB and MAX_EXTRACTED_GB must be > 0")
    if config.max_extracted_gb < config.max_zip_gb:
        errors.append("MAX_EXTRACTED_GB must be >= MAX_ZIP_GB")
    if config.max_files <= 0:
        errors.append("MAX_FILES must be > 0")
    if config.max_expansion_ratio < 1:
        errors.append("MAX_EXPANSION_RATIO must be >= 1")
    if not 1 <= config.photo_album_size <= 10:
        errors.append("PHOTO_ALBUM_SIZE must be between 1 and 10")
    if config.cleanup_ttl_minutes < 1:
        errors.append("CLEANUP_TTL_MINUTES must be >= 1")

    if errors:
        await update.message.reply_text("Errors:\n" + "\n".join(errors))
        return

    await update.message.reply_text("Limits updated for this runtime.")


async def cleanup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    config = _get_config(context)
    if not _is_admin(update, config):
        await update.message.reply_text("Admin only command.")
        return

    removed = cleanup_old_jobs(config.work_dir, config.cleanup_ttl_minutes)
    await update.message.reply_text(f"Cleanup removed {removed} job(s).")


def register_handlers(app) -> None:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("limits", limits_cmd))
    app.add_handler(CommandHandler("setlimits", setlimits_cmd))
    app.add_handler(CommandHandler("cleanup", cleanup_cmd))

    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_password_reply))
