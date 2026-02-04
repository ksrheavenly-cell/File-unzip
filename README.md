# Local Telegram Unzip Bot

A production-ready Telegram bot that accepts ZIP files up to ~2GB, extracts them safely (including password-protected ZIPs), and sends the contents back with media-specific rules.

**Why Local Bot API?**
Telegram's public Bot API has file download size limits. Running the official Local Bot API Server removes those public limits and enables reliable large-file downloads and uploads directly on your VPS.

## Features
- Local Bot API Server (tdlib/telegram-bot-api) for large files.
- Shared local storage mount so the bot can read files written by the Local Bot API Server.
- Safe extraction with zip-slip protection and zip-bomb limits.
- Password ZIP support with reply-based password prompt.
- Progress UI with a single edited message for download, extraction, and sending.
- Auto cleanup of temporary job directories, plus TTL cleanup.
- Admin commands: `/status`, `/limits`, `/setlimits`, `/cleanup`.

## Project Layout
- `app/main.py`: Create app, register handlers, run polling.
- `app/handlers.py`: Bot commands, ZIP handling, password flow, admin logic.
- `app/services/`: Downloader, extractor, sender, progress, cleanup.
- `docker-compose.yml`: Runs bot + local Telegram Bot API server.

## VPS Setup (Ubuntu)
1. Install Docker and Docker Compose.
2. Enable `ufw` and allow only SSH if needed.
3. Create a bot with BotFather and note the bot token.
4. Get your `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` from https://my.telegram.org.
5. Copy `.env.example` to `.env` and fill values.
6. Start services.

Example commands:
```bash
docker compose up -d --build
```

## Verify Local Bot API
Run this from inside the Docker network:
```bash
docker compose exec bot curl http://telegram-bot-api:8081/bot<YOUR_BOT_TOKEN>/getMe
```
Note: in local mode the Bot API may return absolute file paths. The bot container mounts the Bot API storage volume (`/var/lib/telegram-bot-api`) read-only to fetch files directly.

## Configuration
All settings are in `.env`:
- `BOT_TOKEN`: Bot token from BotFather.
- `ADMIN_ID`: Numeric Telegram user ID for admin-only commands.
- `LOCAL_API_BASE_URL`: Must point at the local Bot API server.
- `LOCAL_API_FILE_URL`: Must point at the local Bot API server.
- `WORK_DIR`: Temporary work directory.
- Limits: `MAX_ZIP_GB`, `MAX_EXTRACTED_GB`, `MAX_FILES`, `MAX_EXPANSION_RATIO`, `PHOTO_ALBUM_SIZE`.
- Cleanup: `CLEANUP_TTL_MINUTES`.
- Logging: `LOG_LEVEL`.

## Security Notes
- No secrets are hardcoded. Use `.env`.
- Zip-slip is blocked by validating archive paths.
- Zip-bombs are blocked with file count, size, and expansion ratio limits.
- Disk space is checked before extraction.
- Each job runs in `/opt/unzipbot/work/<user_id>/<job_id>/`.
- All job directories are deleted on completion or error.

## Common Errors
- **Not a ZIP**: The bot only accepts `.zip` files.
- **File too large**: Increase `MAX_ZIP_GB` or send a smaller archive.
- **Wrong password**: Reply with the correct password when prompted.
- **Corrupted ZIP**: Recreate the archive and try again.
- **Safety blocked**: Reduce file count, expansion ratio, or total extracted size.

## Troubleshooting
- Check logs: `./logs/bot.log`.
- Ensure the Local Bot API server is running and reachable.
- Verify `LOCAL_API_BASE_URL` and `LOCAL_API_FILE_URL` values.
- Confirm port 8081 is bound only to `127.0.0.1` or internal Docker network.
- If downloads fail with 404, confirm the shared volume mount to `/var/lib/telegram-bot-api` is present in `docker-compose.yml`.
