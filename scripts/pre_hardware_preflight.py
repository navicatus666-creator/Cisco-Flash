#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = PROJECT_ROOT / "build" / "preflight"


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
        ("check_mcp_runtime", [python_exe, str(PROJECT_ROOT / "scripts" / "check_mcp_runtime.py")]),
        ("unittest", [python_exe, "-m", "unittest", "discover", "-s", str(PROJECT_ROOT / "tests"), "-v"]),
        ("build", [python_exe, "-m", "build", str(PROJECT_ROOT)]),
        ("demo_smoke", [python_exe, str(PROJECT_ROOT / "scripts" / "run_demo_gui_smoke.py")]),
    ]


def _run_step(name: str, command: list[str], output_dir: Path) -> StepResult:
    started = time.perf_counter()
    completed = subprocess.run(
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
    assert isinstance(steps, list)
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
        assert isinstance(step, dict)
        lines.append(
            f"| {step['name']} | {'yes' if step['ok'] else 'no'} | {step['returncode']} | {step['elapsed_seconds']} | {step['log_path']} |"
        )
    artifacts = summary["artifacts"]
    assert isinstance(artifacts, dict)
    lines.extend(
        [
            "",
            "## Artifacts",
            *[f"- {name}: {path}" for name, path in artifacts.items()],
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the local CiscoAutoFlash pre-hardware truth gate in one command."
    )
    parser.add_argument(
        "--rebuild-bundle",
        action="store_true",
        help="Rebuild the carry bundle only after the truth-gate passes.",
    )
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

    run_completed = datetime.now()
    summary = {
        "status": "READY" if not failing_step else "NOT_READY",
        "project_root": str(PROJECT_ROOT),
        "started_at": run_started.isoformat(timespec="seconds"),
        "completed_at": run_completed.isoformat(timespec="seconds"),
        "elapsed_seconds": round((run_completed - run_started).total_seconds(), 3),
        "failing_step": failing_step,
        "steps": [asdict(result) for result in results],
        "artifacts": {
            "output_dir": str(output_dir),
            "summary_json": str(output_dir / "preflight_summary.json"),
            "summary_md": str(output_dir / "preflight_summary.md"),
        },
    }
    summary_json_path = output_dir / "preflight_summary.json"
    summary_md_path = output_dir / "preflight_summary.md"
    summary_json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_md_path.write_text(_render_markdown(summary), encoding="utf-8")

    print(summary_md_path.read_text(encoding="utf-8"))
    return 0 if not failing_step else 1


if __name__ == "__main__":
    raise SystemExit(main())
