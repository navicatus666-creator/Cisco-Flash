from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess  # nosec B404 - local orchestration helper for developer bootstrap
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "build" / "devtools" / "bootstrap"
DEFAULT_PROJECT_PYTHON = Path(r"C:\Python314\python.exe")


@dataclass(slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(slots=True)
class StepSpec:
    name: str
    command: list[str]
    required: bool = True


@dataclass(slots=True)
class StepResult:
    name: str
    command: list[str]
    required: bool
    ok: bool
    returncode: int
    elapsed_seconds: float
    log_path: str


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 120,
) -> CommandResult:
    completed = subprocess.run(  # nosec B603 - fixed local commands only
        command,
        cwd=str(cwd) if cwd else None,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )


def default_steps(python_exe: str) -> list[StepSpec]:
    return [
        StepSpec(
            "check_mcp_runtime",
            [python_exe, str(PROJECT_ROOT / "scripts" / "check_mcp_runtime.py")],
        ),
        StepSpec("ruff", [python_exe, "-m", "ruff", "check", "."]),
        StepSpec("mypy", [python_exe, "-m", "mypy", "ciscoautoflash", "scripts", "main.py"]),
        StepSpec("deptry", [python_exe, "-m", "deptry", "."]),
        StepSpec("lint_imports", ["lint-imports"]),
        StepSpec("pipdeptree", [python_exe, "-m", "pipdeptree", "--warn", "fail"]),
        StepSpec("pip_audit", [python_exe, "-m", "pip_audit", "--progress-spinner", "off"]),
        StepSpec(
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
    ]


def resolve_python_executable(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    env_override = os.environ.get("CISCOAUTOFLASH_BOOTSTRAP_PYTHON", "").strip()
    if env_override:
        return env_override
    if DEFAULT_PROJECT_PYTHON.exists():
        return str(DEFAULT_PROJECT_PYTHON)
    return sys.executable


def collect_runtime_info(python_exe: str) -> dict[str, Any]:
    git_status = run_command(["git", "status", "--short"], cwd=PROJECT_ROOT, timeout=30)
    uv_version = run_command(["uv", "--version"], cwd=PROJECT_ROOT, timeout=30)
    python_version = run_command([python_exe, "--version"], cwd=PROJECT_ROOT, timeout=30)
    return {
        "project_root": str(PROJECT_ROOT),
        "python_executable": python_exe,
        "python_version": (
            python_version.stdout
            or python_version.stderr
            or sys.version.splitlines()[0]
        ),
        "platform": platform.platform(),
        "started_at": _iso_now(),
        "git_dirty": bool(git_status.stdout.strip()),
        "git_status": git_status.stdout.splitlines(),
        "uv_version": uv_version.stdout or uv_version.stderr or "uv unavailable",
    }


def _write_step_log(output_dir: Path, spec: StepSpec, result: CommandResult) -> Path:
    log_path = output_dir / f"{spec.name}.log"
    log_path.write_text(
        "\n".join(
            [
                f"COMMAND: {' '.join(spec.command)}",
                f"REQUIRED: {spec.required}",
                f"RETURN CODE: {result.returncode}",
                "",
                "STDOUT:",
                result.stdout,
                "",
                "STDERR:",
                result.stderr,
            ]
        ),
        encoding="utf-8",
    )
    return log_path


def run_bootstrap(output_dir: Path, *, python_exe: str | None = None) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    resolved_python = resolve_python_executable(python_exe)
    steps = default_steps(resolved_python)
    runtime = collect_runtime_info(resolved_python)
    results: list[StepResult] = []
    failing_step = ""
    for spec in steps:
        started = time.perf_counter()
        result = run_command(spec.command, cwd=PROJECT_ROOT)
        elapsed = round(time.perf_counter() - started, 3)
        log_path = _write_step_log(output_dir, spec, result)
        step_result = StepResult(
            name=spec.name,
            command=spec.command,
            required=spec.required,
            ok=result.returncode == 0,
            returncode=result.returncode,
            elapsed_seconds=elapsed,
            log_path=str(log_path),
        )
        results.append(step_result)
        if spec.required and result.returncode != 0 and not failing_step:
            failing_step = spec.name
    completed_at = _iso_now()
    summary = {
        "status": "READY" if not failing_step else "NOT_READY",
        "started_at": runtime["started_at"],
        "completed_at": completed_at,
        "runtime": runtime,
        "steps": [asdict(item) for item in results],
        "failing_step": failing_step,
        "artifacts": {
            "output_dir": str(output_dir),
            "summary_json": str(output_dir / "summary.json"),
            "summary_md": str(output_dir / "summary.md"),
        },
    }
    return summary


def render_markdown(summary: dict[str, Any]) -> str:
    runtime = summary["runtime"]
    steps = summary["steps"]
    git_lines = runtime.get("git_status", [])
    lines = [
        "# CiscoAutoFlash Project Bootstrap",
        "",
        f"- Status: {summary['status']}",
        f"- Started at: {summary['started_at']}",
        f"- Completed at: {summary['completed_at']}",
        f"- Project root: {runtime['project_root']}",
        f"- Python: {runtime['python_version']}",
        f"- Executable: {runtime['python_executable']}",
        f"- Platform: {runtime['platform']}",
        f"- UV: {runtime['uv_version']}",
        f"- Git dirty: {'yes' if runtime['git_dirty'] else 'no'}",
        f"- Failing step: {summary['failing_step'] or '—'}",
        "",
        "## Steps",
        "| Step | Required | OK | Return code | Seconds | Log |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for step in steps:
        lines.append(
            f"| {step['name']} | {'yes' if step['required'] else 'no'} | "
            f"{'yes' if step['ok'] else 'no'} | {step['returncode']} | "
            f"{step['elapsed_seconds']} | {step['log_path']} |"
        )
    lines.extend(["", "## Git Status"])
    if git_lines:
        lines.extend([f"- `{line}`" for line in git_lines])
    else:
        lines.append("- clean")
    return "\n".join(lines) + "\n"


def _print_console_text(text: str) -> None:
    output = text if text.endswith("\n") else f"{text}\n"
    try:
        sys.stdout.write(output)
        sys.stdout.flush()
        return
    except UnicodeEncodeError:
        pass
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    payload = output.encode(encoding, errors="replace")
    if getattr(sys.stdout, "buffer", None) is not None:
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()
        return
    sys.stdout.write(payload.decode(encoding, errors="replace"))
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the CiscoAutoFlash developer bootstrap checks in one command."
    )
    parser.add_argument(
        "--json-out",
        default="",
        help=(
            "Optional explicit JSON output path. "
            "Default uses build/devtools/bootstrap/<timestamp>/summary.json."
        ),
    )
    args = parser.parse_args(argv)

    output_dir = OUTPUT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    summary = run_bootstrap(output_dir)
    summary_json = Path(args.json_out) if args.json_out else output_dir / "summary.json"
    summary_md = output_dir / "summary.md"
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_md.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_md.write_text(render_markdown(summary), encoding="utf-8")
    _print_console_text(summary_md.read_text(encoding="utf-8"))
    return 0 if summary["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
