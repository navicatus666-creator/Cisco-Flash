from __future__ import annotations

import argparse
import sys
import urllib.parse
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OBSMEM_ROOT = PROJECT_ROOT / "OBSMEM"

def _today_str() -> str:
    from datetime import datetime

    return datetime.now().date().isoformat()


def _print_console_text(text: str) -> None:
    output = text if text.endswith("\n") else f"{text}\n"
    stream = sys.stdout
    try:
        stream.write(output)
        stream.flush()
        return
    except UnicodeEncodeError:
        pass
    encoding = getattr(stream, "encoding", None) or "utf-8"
    payload = output.encode(encoding, errors="replace")
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(payload)
        buffer.flush()
        return
    stream.write(payload.decode(encoding, errors="replace"))
    stream.flush()


def resolve_target(target: str) -> Path:
    key = target.strip().lower()
    canonical_targets = {
        "current-work": OBSMEM_ROOT / "mirrors" / "Current_Work.md",
        "daily": OBSMEM_ROOT / "daily" / f"{_today_str()}.md",
        "log": OBSMEM_ROOT / "log.md",
        "index": OBSMEM_ROOT / "index.md",
        "readme": OBSMEM_ROOT / "README.md",
        "project": OBSMEM_ROOT / "projects" / "CiscoAutoFlash.md",
        "policy": OBSMEM_ROOT / "concepts" / "Obsidian_MCP_Integration_Policy.md",
    }
    value = canonical_targets.get(key)
    if isinstance(value, Path):
        return value
    candidate = Path(target)
    if candidate.is_absolute():
        return candidate
    return (OBSMEM_ROOT / candidate).resolve()


def build_obsidian_uri(path: Path) -> str:
    normalized = str(path.resolve())
    return "obsidian://open?path=" + urllib.parse.quote(normalized, safe="")


def open_in_obsidian(path: Path) -> bool:
    return webbrowser.open(build_obsidian_uri(path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Open canonical OBSMEM pages in Obsidian."
    )
    parser.add_argument(
        "target",
        nargs="?",
        default="current-work",
        help=(
            "Canonical target (current-work, daily, log, index, readme, "
            "project, policy) or OBSMEM-relative path."
        ),
    )
    args = parser.parse_args(argv)

    path = resolve_target(args.target)
    if not path.exists():
        _print_console_text(f"Missing OBSMEM target: {path}")
        return 1

    opened = open_in_obsidian(path)
    _print_console_text(
        f"Opened in Obsidian: {path}" if opened else f"Failed to open in Obsidian: {path}"
    )
    return 0 if opened else 1


if __name__ == "__main__":
    raise SystemExit(main())
