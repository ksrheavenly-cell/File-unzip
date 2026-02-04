from __future__ import annotations

import shutil
import time
from pathlib import Path


def cleanup_job(job_dir: Path) -> None:
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)


def cleanup_old_jobs(work_dir: Path, ttl_minutes: int) -> int:
    if not work_dir.exists():
        return 0
    cutoff = time.time() - ttl_minutes * 60
    removed = 0
    for user_dir in work_dir.iterdir():
        if not user_dir.is_dir():
            continue
        for job_dir in user_dir.iterdir():
            try:
                mtime = job_dir.stat().st_mtime
            except FileNotFoundError:
                continue
            if mtime < cutoff:
                shutil.rmtree(job_dir, ignore_errors=True)
                removed += 1
    return removed
