#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 - local truth-gate orchestration intentionally uses subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = PROJECT_ROOT / "build" / "preflight"


def _load_hardware_day_helpers():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from ciscoautoflash.devtools.hardware_day import (
        assess_hardware_day_readiness,
        build_connection_snapshot,
        describe_connection_snapshot,
        resolve_runtime_preflight_paths,
    )

    return (
        assess_hardware_day_readiness,
        build_connection_snapshot,
        describe_connection_snapshot,
        resolve_runtime_preflight_paths,
    )


@dataclass(slots=True)
class StepResult:
    name: str
    command: list[str]
    ok: bool
    returncode: int
    elapsed_seconds: float
    log_path: str


def _default_steps() -> list[tuple[str, list[str]]]:
    python_exe = sys.executable
    return [
        (
            "unittest",
            [
                python_exe,
                "-m",
                "unittest",
                "discover",
                "-s",
                str(PROJECT_ROOT / "tests"),
                "-v",
            ],
        ),
        ("build", [python_exe, "-m", "build", str(PROJECT_ROOT)]),
    ]


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


def _run_step(name: str, command: list[str], output_dir: Path) -> StepResult:
    started = time.perf_counter()
    completed = subprocess.run(  # nosec B603
        command,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    elapsed = time.perf_counter() - started
    log_path = output_dir / f"{name}.log"
    log_path.write_text(
        "\n".join(
            [
                f"COMMAND: {' '.join(command)}",
                f"RETURN CODE: {completed.returncode}",
                "",
                "STDOUT:",
                completed.stdout,
                "",
                "STDERR:",
                completed.stderr,
            ]
        ),
        encoding="utf-8",
    )
    return StepResult(
        name=name,
        command=command,
        ok=completed.returncode == 0,
        returncode=completed.returncode,
        elapsed_seconds=round(elapsed, 3),
        log_path=str(log_path),
    )


def _render_markdown(summary: dict[str, object]) -> str:
    steps = summary["steps"]
    if not isinstance(steps, list):
        raise TypeError("summary['steps'] must be a list")
    lines = [
        "# CiscoAutoFlash Pre-Hardware Preflight",
        "",
        f"- Status: {summary['status']}",
        f"- Started at: {summary['started_at']}",
        f"- Completed at: {summary['completed_at']}",
        f"- Elapsed seconds: {summary['elapsed_seconds']}",
        f"- Failing step: {summary['failing_step'] or '—'}",
        "",
        "## Steps",
        "| Step | OK | Return code | Seconds | Log |",
        "| --- | --- | --- | --- | --- |",
    ]
    for step in steps:
        if not isinstance(step, dict):
            raise TypeError("summary['steps'] items must be dicts")
        lines.append(
            f"| {step['name']} | {'yes' if step['ok'] else 'no'} | "
            f"{step['returncode']} | {step['elapsed_seconds']} | "
            f"{step['log_path']} |"
        )
    artifacts = summary["artifacts"]
    if not isinstance(artifacts, dict):
        raise TypeError("summary['artifacts'] must be a dict")
    lines.extend(
        [
            "",
            "## Artifacts",
            *[f"- {name}: {path}" for name, path in artifacts.items()],
        ]
    )
    hardware_day_status = str(summary.get("hardware_day_status", "") or "")
    if hardware_day_status:
        lines.extend(
            [
                "",
                "## Hardware-Day Rehearsal",
                f"- Status: {hardware_day_status}",
            ]
        )
        connection_summary = summary.get("connection_summary")
        if isinstance(connection_summary, dict):
            lines.extend(
                [
                    f"- Console: {connection_summary.get('console', '')}",
                    f"- Ethernet: {connection_summary.get('ethernet', '')}",
                    f"- Optional SSH: {connection_summary.get('ssh', '')}",
                    f"- Live run: {connection_summary.get('live_run_path', '')}",
                    f"- Return path: {connection_summary.get('return_path', '')}",
                ]
            )
        next_steps = summary.get("hardware_day_next_steps")
        if isinstance(next_steps, list) and next_steps:
            lines.extend(["", "## Next Steps", *[f"- {step}" for step in next_steps]])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    (
        assess_hardware_day_readiness,
        build_connection_snapshot,
        describe_connection_snapshot,
        resolve_runtime_preflight_paths,
    ) = _load_hardware_day_helpers()
    parser = argparse.ArgumentParser(
        description="Run the local CiscoAutoFlash pre-hardware truth gate in one command."
    )
    parser.add_argument(
        "--rebuild-bundle",
        action="store_true",
        help="Rebuild the carry bundle only after the truth-gate passes.",
    )
    parser.add_argument(
        "--hardware-day-rehearsal",
        action="store_true",
        help="Add a read-only hardware-day snapshot and readiness summary.",
    )
    parser.add_argument("--host", default="", help="Optional host/IP for ping or SSH probe.")
    parser.add_argument("--username", default="", help="Optional SSH username for probe.")
    parser.add_argument("--password", default="", help="Optional SSH password for probe.")
    parser.add_argument("--secret", default="", help="Optional SSH enable secret for probe.")
    args = parser.parse_args(argv)

    run_started = datetime.now()
    output_dir = BUILD_ROOT / run_started.strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[StepResult] = []
    failing_step = ""
    for name, command in _default_steps():
        result = _run_step(name, command, output_dir)
        results.append(result)
        if not result.ok:
            failing_step = name
            break

    if args.rebuild_bundle and not failing_step:
        bundle_result = _run_step(
            "build_field_bundle",
            [sys.executable, str(PROJECT_ROOT / "scripts" / "build_field_bundle.py")],
            output_dir,
        )
        results.append(bundle_result)
        if not bundle_result.ok:
            failing_step = bundle_result.name

    connection_snapshot: dict[str, object] | None = None
    connection_summary: dict[str, str] | None = None
    hardware_day_status = ""
    hardware_day_next_steps: list[str] = []
    connection_snapshot_path = output_dir / "connection_snapshot.json"
    if args.hardware_day_rehearsal:
        connection_snapshot = build_connection_snapshot(
            host=args.host,
            username=args.username,
            password=args.password,
            secret=args.secret,
        )
        connection_snapshot_path.write_text(
            json.dumps(connection_snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        connection_summary = describe_connection_snapshot(connection_snapshot)
        hardware_day = assess_hardware_day_readiness(
            preflight_status="READY" if not failing_step else "NOT_READY",
            snapshot=connection_snapshot,
        )
        hardware_day_status = str(hardware_day["status"])
        hardware_day_next_steps = list(hardware_day["next_steps"])

    run_completed = datetime.now()
    artifacts: dict[str, str] = {
        "output_dir": str(output_dir),
        "summary_json": str(output_dir / "preflight_summary.json"),
        "summary_md": str(output_dir / "preflight_summary.md"),
    }
    summary: dict[str, object] = {
        "status": "READY" if not failing_step else "NOT_READY",
        "project_root": str(PROJECT_ROOT),
        "started_at": run_started.isoformat(timespec="seconds"),
        "completed_at": run_completed.isoformat(timespec="seconds"),
        "elapsed_seconds": round((run_completed - run_started).total_seconds(), 3),
        "failing_step": failing_step,
        "steps": [asdict(result) for result in results],
        "artifacts": artifacts,
    }
    if args.hardware_day_rehearsal:
        summary["hardware_day_status"] = hardware_day_status
        summary["hardware_day_next_steps"] = hardware_day_next_steps
        summary["connection_summary"] = connection_summary or {}
        artifacts["connection_snapshot_json"] = str(connection_snapshot_path)
        summary["connection_snapshot"] = connection_snapshot or {}
    summary_json_path = output_dir / "preflight_summary.json"
    summary_md_path = output_dir / "preflight_summary.md"
    runtime_paths = resolve_runtime_preflight_paths(output_dir.name)
    artifacts["runtime_output_dir"] = str(runtime_paths["output_dir"])
    artifacts["runtime_summary_json"] = str(runtime_paths["summary_json"])
    artifacts["runtime_summary_md"] = str(runtime_paths["summary_md"])
    artifacts["runtime_latest_summary_json"] = str(runtime_paths["latest_summary_json"])
    rendered_markdown = _render_markdown(summary)
    summary_json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary_md_path.write_text(rendered_markdown, encoding="utf-8")
    runtime_paths["output_dir"].mkdir(parents=True, exist_ok=True)
    runtime_paths["summary_json"].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    runtime_paths["summary_md"].write_text(rendered_markdown, encoding="utf-8")
    runtime_paths["latest_summary_json"].write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _print_console_text(rendered_markdown)
    if args.hardware_day_rehearsal:
        return 0 if not failing_step and hardware_day_status == "READY_FOR_HARDWARE" else 1
    return 0 if not failing_step else 1


if __name__ == "__main__":
    raise SystemExit(main())
