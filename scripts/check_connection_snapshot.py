#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _ensure_project_root_on_path() -> None:
    project_root = str(PROJECT_ROOT)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture a read-only CiscoAutoFlash hardware-day connection snapshot."
    )
    parser.add_argument("--host", default="")
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--secret", default="")
    parser.add_argument("--output-dir", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _ensure_project_root_on_path()
    from ciscoautoflash.devtools.hardware_day import (
        build_connection_snapshot,
        render_connection_snapshot_markdown,
    )

    snapshot = build_connection_snapshot(
        host=args.host,
        username=args.username,
        password=args.password,
        secret=args.secret,
    )
    markdown = render_connection_snapshot_markdown(snapshot)
    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "connection_snapshot.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (output_dir / "connection_snapshot.md").write_text(
            markdown,
            encoding="utf-8",
        )
        print(str(output_dir / "connection_snapshot.md"))
        return 0
    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
