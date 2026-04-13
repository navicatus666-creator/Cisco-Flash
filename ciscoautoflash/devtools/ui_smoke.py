from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404 - local UI smoke helper launches the desktop app
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "build" / "devtools" / "ui_smoke"


def build_command(*, python_exe: str, demo_scenario: str) -> list[str]:
    command = [python_exe, str(PROJECT_ROOT / "main.py"), "--demo"]
    if demo_scenario:
        command.extend(["--demo-scenario", demo_scenario])
    return command


def build_env(*, close_ms: int) -> dict[str, str]:
    env = os.environ.copy()
    env["CISCOAUTOFLASH_UI_SMOKE"] = "1"
    env["CISCOAUTOFLASH_UI_SMOKE_CLOSE_MS"] = str(close_ms)
    return env


def run_ui_smoke(
    *,
    output_dir: Path,
    python_exe: str | None = None,
    demo_scenario: str = "",
    close_ms: int = 1500,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    command = build_command(
        python_exe=python_exe or sys.executable,
        demo_scenario=demo_scenario,
    )
    env = build_env(close_ms=close_ms)
    started_at = datetime.now(UTC).isoformat()
    started = time.perf_counter()
    timed_out = False
    try:
        completed = subprocess.run(  # nosec B603 - fixed local desktop app command
            command,
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(20, int(close_ms / 1000) + 15),
            check=False,
        )
        returncode = completed.returncode
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = 124
        timeout_stdout = (
            exc.stdout.decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        timeout_stderr = (
            exc.stderr.decode("utf-8", errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
        stdout = timeout_stdout.strip()
        stderr = (timeout_stderr.strip() + "\nUI smoke timed out.").strip()
    elapsed = round(time.perf_counter() - started, 3)
    process_log = output_dir / "process.log"
    process_log.write_text(
        "\n".join(
            [
                f"COMMAND: {' '.join(command)}",
                f"RETURN CODE: {returncode}",
                f"TIMED OUT: {timed_out}",
                "",
                "STDOUT:",
                stdout,
                "",
                "STDERR:",
                stderr,
            ]
        ),
        encoding="utf-8",
    )
    return {
        "status": "READY" if returncode == 0 and not timed_out else "NOT_READY",
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
        "elapsed_seconds": elapsed,
        "timed_out": timed_out,
        "returncode": returncode,
        "command": command,
        "demo_scenario": demo_scenario or "default",
        "close_ms": close_ms,
        "artifacts": {
            "output_dir": str(output_dir),
            "process_log": str(process_log),
            "summary_json": str(output_dir / "summary.json"),
            "summary_md": str(output_dir / "summary.md"),
        },
    }


def render_markdown(summary: dict[str, Any]) -> str:
    return (
        "# CiscoAutoFlash UI Smoke\n\n"
        f"- Status: {summary['status']}\n"
        f"- Started at: {summary['started_at']}\n"
        f"- Completed at: {summary['completed_at']}\n"
        f"- Elapsed seconds: {summary['elapsed_seconds']}\n"
        f"- Demo scenario: {summary['demo_scenario']}\n"
        f"- Close ms: {summary['close_ms']}\n"
        f"- Timed out: {'yes' if summary['timed_out'] else 'no'}\n"
        f"- Return code: {summary['returncode']}\n"
        f"- Process log: {summary['artifacts']['process_log']}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a fast demo-mode UI smoke for CiscoAutoFlash."
    )
    parser.add_argument("--demo-scenario", default="", help="Optional demo scenario name.")
    parser.add_argument("--close-ms", type=int, default=1500, help="Auto-close delay in ms.")
    parser.add_argument("--json-out", default="", help="Optional explicit JSON output path.")
    args = parser.parse_args(argv)

    output_dir = OUTPUT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    summary = run_ui_smoke(
        output_dir=output_dir,
        demo_scenario=args.demo_scenario,
        close_ms=max(250, args.close_ms),
    )
    json_out = Path(args.json_out) if args.json_out else output_dir / "summary.json"
    summary_md = output_dir / "summary.md"
    json_out.parent.mkdir(parents=True, exist_ok=True)
    summary_md.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_md.write_text(render_markdown(summary), encoding="utf-8")
    print(summary_md.read_text(encoding="utf-8"), end="")
    return 0 if summary["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
