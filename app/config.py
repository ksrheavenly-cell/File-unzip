from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _get_env(name: str, default=None, cast=str, required: bool = False):
    value = os.getenv(name, default)
    if value is None or value == "":
        if required:
            raise ValueError(f"Missing required env: {name}")
        return default
    try:
        return cast(value)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Invalid value for {name}: {value}") from exc


@dataclass
class Config:
    bot_token: str
    admin_id: int
    local_api_base_url: str
    local_api_file_url: str
    work_dir: Path
    max_zip_gb: float
    max_extracted_gb: float
    max_files: int
    max_expansion_ratio: int
    photo_album_size: int
    cleanup_ttl_minutes: int
    log_level: str

    @property
    def max_zip_bytes(self) -> int:
        return int(self.max_zip_gb * 1024**3)

    @property
    def max_extracted_bytes(self) -> int:
        return int(self.max_extracted_gb * 1024**3)


def load_config() -> Config:
    load_dotenv()

    config = Config(
        bot_token=_get_env("BOT_TOKEN", required=True),
        admin_id=_get_env("ADMIN_ID", required=True, cast=int),
        local_api_base_url=_get_env("LOCAL_API_BASE_URL", required=True),
        local_api_file_url=_get_env("LOCAL_API_FILE_URL", required=True),
        work_dir=Path(_get_env("WORK_DIR", required=True)),
        max_zip_gb=_get_env("MAX_ZIP_GB", "2", cast=float),
        max_extracted_gb=_get_env("MAX_EXTRACTED_GB", "6", cast=float),
        max_files=_get_env("MAX_FILES", "5000", cast=int),
        max_expansion_ratio=_get_env("MAX_EXPANSION_RATIO", "50", cast=int),
        photo_album_size=_get_env("PHOTO_ALBUM_SIZE", "4", cast=int),
        cleanup_ttl_minutes=_get_env("CLEANUP_TTL_MINUTES", "60", cast=int),
        log_level=_get_env("LOG_LEVEL", "INFO"),
    )

    if config.max_zip_gb <= 0:
        raise ValueError("MAX_ZIP_GB must be > 0")
    if config.max_extracted_gb <= 0:
        raise ValueError("MAX_EXTRACTED_GB must be > 0")
    if config.max_extracted_gb < config.max_zip_gb:
        raise ValueError("MAX_EXTRACTED_GB must be >= MAX_ZIP_GB")
    if config.max_files <= 0:
        raise ValueError("MAX_FILES must be > 0")
    if config.max_expansion_ratio < 1:
        raise ValueError("MAX_EXPANSION_RATIO must be >= 1")
    if not 1 <= config.photo_album_size <= 10:
        raise ValueError("PHOTO_ALBUM_SIZE must be between 1 and 10")
    if config.cleanup_ttl_minutes < 1:
        raise ValueError("CLEANUP_TTL_MINUTES must be >= 1")

    config.work_dir = config.work_dir.resolve()
    return config
