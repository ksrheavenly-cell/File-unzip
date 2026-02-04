from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from telegram.ext import Application

from app.config import load_config
from app.handlers import register_handlers
from app.services.cleanup import cleanup_old_jobs
from app.utils import ensure_dir


def setup_logging(log_level: str, work_dir: Path) -> None:
    log_dir = work_dir.parent / "logs"
    ensure_dir(log_dir)
    log_file = log_dir / "bot.log"

    formatter = logging.Formatter(
        "time=%(asctime)s level=%(levelname)s logger=%(name)s msg=%(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(log_file)]
    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(level=log_level.upper(), handlers=handlers)


async def ttl_cleanup_job(context) -> None:
    config = context.application.bot_data["config"]
    removed = cleanup_old_jobs(config.work_dir, config.cleanup_ttl_minutes)
    if removed:
        logging.getLogger(__name__).info("cleanup removed=%s", removed)


def create_app() -> Application:
    config = load_config()
    ensure_dir(config.work_dir)
    setup_logging(config.log_level, config.work_dir)

    app = (
        Application.builder()
        .token(config.bot_token)
        .base_url(config.local_api_base_url)
        .base_file_url(config.local_api_file_url)
        .build()
    )

    app.bot_data["config"] = config
    app.bot_data["start_time"] = time.time()
    app.bot_data["active_jobs"] = set()

    register_handlers(app)

    app.job_queue.run_repeating(ttl_cleanup_job, interval=600, first=60)
    return app


def main() -> None:
    app = create_app()
    app.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()
