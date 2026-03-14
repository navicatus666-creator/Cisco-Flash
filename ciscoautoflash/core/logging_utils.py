from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

SENSITIVE_PATTERN = re.compile(r"(password|enable secret|secret|key)\s+\S+", re.IGNORECASE)


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def mask_sensitive(text: str) -> str:
    return SENSITIVE_PATTERN.sub(lambda match: f"{match.group(1)} ******", text)


def append_session_log(log_path: Path, message: str) -> None:
    safe_text = mask_sensitive(message)
    with log_path.open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(safe_text + "\n")


def append_transcript_line(transcript_path: Path, direction: str, message: str) -> None:
    safe_text = mask_sensitive(message)
    with transcript_path.open("a", encoding="utf-8", errors="replace") as handle:
        if not safe_text:
            return
        lines = safe_text.splitlines() or [safe_text]
        for line in lines:
            handle.write(f"{timestamp()} | {direction:<8} | {line}\n")
