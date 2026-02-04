from __future__ import annotations

import asyncio
import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.services.progress import ProgressReporter
from app.utils import human_bytes


class ExtractionError(Exception):
    pass


class PasswordRequired(ExtractionError):
    pass


class WrongPassword(ExtractionError):
    pass


class SafetyBlocked(ExtractionError):
    pass


class CorruptArchive(ExtractionError):
    pass


@dataclass
class ArchiveInfo:
    file_count: int
    total_size: int
    encrypted: bool


def _is_safe_member(path_str: str) -> bool:
    if not path_str:
        return False
    if path_str.startswith("/") or path_str.startswith("\\"):
        return False
    norm = path_str.replace("\\", "/")
    p = PurePosixPath(norm)
    if p.is_absolute():
        return False
    if any(part == ".." for part in p.parts):
        return False
    if ":" in path_str:
        return False
    return True


def _parse_slt(output: str) -> list[dict]:
    entries: list[dict] = []
    current: dict = {}
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        if " = " in line:
            key, val = line.split(" = ", 1)
            current[key] = val
    if current:
        entries.append(current)
    return entries


async def inspect_archive(zip_path: Path, password: str | None = None) -> ArchiveInfo:
    args = ["7z", "l", "-slt", str(zip_path)]
    if password:
        args.insert(2, f"-p{password}")

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    out_text = stdout.decode(errors="ignore")
    err_text = stderr.decode(errors="ignore")
    combined = out_text + "\n" + err_text

    if proc.returncode != 0:
        if "Wrong password" in combined or "incorrect password" in combined:
            raise WrongPassword("Wrong password")
        if "Can not open encrypted archive" in combined:
            raise PasswordRequired("Password required")
        if "Can not open file as archive" in combined or "Headers Error" in combined:
            raise CorruptArchive("Corrupted or unsupported archive")
        raise ExtractionError(combined.strip() or "Failed to inspect archive")

    entries = _parse_slt(out_text)
    file_count = 0
    total_size = 0
    encrypted = False

    for entry in entries:
        path = entry.get("Path")
        if not path:
            continue
        if entry.get("Folder") == "+":
            continue
        if not _is_safe_member(path):
            raise SafetyBlocked("Zip-slip path detected")
        if entry.get("Encrypted") == "+":
            encrypted = True
        try:
            size = int(entry.get("Size", "0"))
        except ValueError:
            size = 0
        file_count += 1
        total_size += size

    return ArchiveInfo(file_count=file_count, total_size=total_size, encrypted=encrypted)


def validate_archive(info: ArchiveInfo, zip_size: int, max_files: int, max_total: int, max_ratio: int) -> None:
    if info.file_count == 0:
        raise CorruptArchive("Archive is empty")
    if info.file_count > max_files:
        raise SafetyBlocked(f"Too many files ({info.file_count} > {max_files})")
    if info.total_size > max_total:
        raise SafetyBlocked(
            f"Extracted size too large ({human_bytes(info.total_size)} > {human_bytes(max_total)})"
        )
    if zip_size > 0:
        ratio = info.total_size / max(zip_size, 1)
        if ratio > max_ratio:
            raise SafetyBlocked(f"Expansion ratio too high ({ratio:.1f} > {max_ratio})")


def check_disk_space(target_dir: Path, required_bytes: int) -> None:
    usage = shutil.disk_usage(target_dir)
    margin = max(int(required_bytes * 0.1), 512 * 1024 * 1024)
    if usage.free < required_bytes + margin:
        raise SafetyBlocked("Not enough disk space for extraction")


async def extract_archive(
    zip_path: Path,
    dest_dir: Path,
    password: str | None,
    progress: ProgressReporter,
) -> None:
    args = ["7z", "x", "-y", "-bsp1", f"-o{dest_dir}", str(zip_path)]
    if password:
        args.insert(2, f"-p{password}")

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stderr_task = asyncio.create_task(proc.stderr.read())
    output_lines: list[str] = []
    percent_re = re.compile(r"(\d+)%")

    if proc.stdout:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode(errors="ignore").strip()
            if text:
                output_lines.append(text)
                match = percent_re.search(text)
                if match:
                    percent = float(match.group(1))
                    await progress.update("📦 Extracting files", percent, None)

    await proc.wait()
    stderr = (await stderr_task).decode(errors="ignore")
    combined = "\n".join(output_lines) + "\n" + stderr

    if proc.returncode != 0:
        if "Wrong password" in combined or "incorrect password" in combined:
            raise WrongPassword("Wrong password")
        if "Can not open encrypted archive" in combined or "Enter password" in combined:
            raise PasswordRequired("Password required")
        if "Can not open file as archive" in combined or "Headers Error" in combined:
            raise CorruptArchive("Corrupted or unsupported archive")
        raise ExtractionError(combined.strip() or "Extraction failed")

    await progress.update("📦 Extracting files", 100.0, "Extraction complete", force=True)
