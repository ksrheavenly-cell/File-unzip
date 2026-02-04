from __future__ import annotations

import time
from dataclasses import dataclass

from telegram import Bot


def render_progress_bar(percent: float, width: int = 20, style: str = "blocks") -> str:
    percent = max(0.0, min(100.0, percent))
    filled = int(width * (percent / 100.0))
    empty = max(0, width - filled)
    if style == "blocks":
        full_char, empty_char = "█", "░"
    elif style == "ascii":
        full_char, empty_char = "=", "-"
    elif style == "emoji":
        full_char, empty_char = "🟩", "⬜"
    else:
        full_char, empty_char = "#", "-"
    return f"[{full_char * filled}{empty_char * empty}]"


def render_spinner(frame: int) -> str:
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    return frames[frame % len(frames)]


@dataclass
class ProgressReporter:
    bot: Bot
    chat_id: int
    message_id: int
    throttle_seconds: float = 1.0
    min_percent_step: float = 5.0
    style: str = "blocks"

    def __post_init__(self) -> None:
        self._last_update = 0.0
        self._last_percent = -1.0
        self._last_stage = ""
        self._spinner_frame = 0

    async def update(
        self,
        stage: str,
        percent: float,
        detail: str | None = None,
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        percent = max(0.0, min(100.0, percent))
        stage_changed = stage != self._last_stage
        percent_changed = percent - self._last_percent >= self.min_percent_step
        time_ok = (now - self._last_update) >= self.throttle_seconds

        if not force and not stage_changed and not percent_changed and not time_ok:
            return

        bar = render_progress_bar(percent, style=self.style)
        if detail:
            text = f"{stage}\n{bar} {percent:.0f}%\n{detail}"
        else:
            text = f"{stage}\n{bar} {percent:.0f}%"
        try:
            await self.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=text,
            )
            self._last_update = now
            self._last_percent = percent
            self._last_stage = stage
        except Exception:
            return

    async def update_indeterminate(self, stage: str, detail: str | None = None, force: bool = False) -> None:
        now = time.monotonic()
        stage_changed = stage != self._last_stage
        time_ok = (now - self._last_update) >= self.throttle_seconds
        if not force and not stage_changed and not time_ok:
            return

        spinner = render_spinner(self._spinner_frame)
        self._spinner_frame += 1
        if detail:
            text = f"{stage}\n{spinner} {detail}"
        else:
            text = f"{stage}\n{spinner} Working..."
        try:
            await self.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=text,
            )
            self._last_update = now
            self._last_stage = stage
        except Exception:
            return

    async def success(self) -> None:
        await self.update("✅ Done!", 100.0, None, force=True)

    async def fail(self, reason: str) -> None:
        text = f"❌ Failed: {reason}"
        try:
            await self.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=text,
            )
            self._last_update = time.monotonic()
            self._last_stage = "failed"
        except Exception:
            return
