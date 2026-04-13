from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess  # nosec B404 - local developer helper uses subprocess for truth gates
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OBSMEM_ROOT = PROJECT_ROOT / "OBSMEM"
BUILD_ROOT = PROJECT_ROOT / "build" / "devtools" / "session_close"
MIRROR_ROOT = OBSMEM_ROOT / "mirrors"
INBOX_ROOT = OBSMEM_ROOT / "inbox"
MEMORY_LINT_CHECKLIST = OBSMEM_ROOT / "analyses" / "Memory_Lint_Checklist.md"


@dataclass(slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(slots=True)
class CheckResult:
    name: str
    ok: bool
    severity: str
    summary: str
    details: list[str]
    data: dict[str, Any]


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


def _run_command(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 30,
) -> CommandResult:
    completed = subprocess.run(  # nosec B603 - fixed local truth-gate command
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return CommandResult(
        returncode=completed.returncode,
        stdout=(completed.stdout or "").strip(),
        stderr=(completed.stderr or "").strip(),
    )


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _parse_git_status_line(line: str) -> dict[str, str]:
    status = line[:2]
    payload = line[3:].strip()
    old_path = ""
    new_path = payload
    if " -> " in payload:
        old_path, new_path = [part.strip() for part in payload.split(" -> ", 1)]
    return {
        "status": status,
        "path": new_path,
        "old_path": old_path,
        "raw": line,
    }


def _collect_dirty_files(project_root: Path) -> dict[str, Any]:
    result = _run_command(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=project_root,
        timeout=30,
    )
    if result.returncode != 0:
        return {
            "ok": False,
            "summary": "git status failed",
            "error": result.stderr or result.stdout,
            "items": [],
        }

    items = [
        _parse_git_status_line(line)
        for line in result.stdout.splitlines()
        if line.strip()
    ]
    return {
        "ok": True,
        "summary": "no dirty files" if not items else f"{len(items)} dirty file(s) detected",
        "items": items,
        "error": "",
    }


def _memory_lint_presence(obsmem_root: Path) -> dict[str, Any]:
    checklist = obsmem_root / "analyses" / "Memory_Lint_Checklist.md"
    present = checklist.exists() and checklist.is_file()
    size_bytes = checklist.stat().st_size if present else 0
    return {
        "path": str(checklist),
        "present": present,
        "size_bytes": size_bytes,
        "summary": (
            "Memory_Lint_Checklist present"
            if present
            else "Memory_Lint_Checklist missing"
        ),
    }


def _mirror_targets_for_path(rel_path: str) -> list[str]:
    normalized = rel_path.replace("\\", "/")
    targets: list[str] = [str(MIRROR_ROOT / "CiscoAutoFlash_Current_State.md")]
    if normalized.startswith("docs/pre_hardware/") or normalized.startswith(
        "scripts/pre_hardware_preflight.py"
    ):
        targets.append(str(MIRROR_ROOT / "Hardware_Smoke_Gate.md"))
    if normalized.startswith("OBSMEM/"):
        targets.extend(
            [
                str(MIRROR_ROOT / "Active_Risks.md"),
                str(MIRROR_ROOT / "Open_Architecture_Questions.md"),
            ]
        )
    return sorted(set(targets))


def _collect_obsmem_mirror_checks(
    project_root: Path,
    obsmem_root: Path,
    dirty_items: list[dict[str, str]],
) -> dict[str, Any]:
    mirrors = [
        obsmem_root / "mirrors" / "CiscoAutoFlash_Current_State.md",
        obsmem_root / "mirrors" / "Active_Risks.md",
        obsmem_root / "mirrors" / "Open_Architecture_Questions.md",
        obsmem_root / "mirrors" / "Hardware_Smoke_Gate.md",
    ]
    dirty_paths = [
        item["path"]
        for item in dirty_items
        if not item["path"].replace("\\", "/").startswith("OBSMEM/mirrors/")
    ]
    checks: list[dict[str, Any]] = []
    for mirror in mirrors:
        target_sources = [
            path for path in dirty_paths if str(mirror) in _mirror_targets_for_path(path)
        ]
        exists = mirror.exists() and mirror.is_file()
        size_bytes = mirror.stat().st_size if exists else 0
        latest_source_mtime = 0.0
        for source in target_sources:
            source_path = project_root / source
            if source_path.exists():
                latest_source_mtime = max(latest_source_mtime, source_path.stat().st_mtime)
        mirror_mtime = mirror.stat().st_mtime if exists else 0.0
        if not exists:
            status = "missing"
            reason = "mirror note is missing"
        elif size_bytes == 0:
            status = "empty"
            reason = "mirror note is empty"
        elif latest_source_mtime and mirror_mtime < latest_source_mtime:
            status = "stale"
            reason = "mirror note is older than recent repo changes"
        else:
            status = "ok"
            reason = "mirror note exists and is current enough"
        checks.append(
            {
                "path": str(mirror),
                "exists": exists,
                "size_bytes": size_bytes,
                "status": status,
                "reason": reason,
                "target_sources": target_sources,
            }
        )
    gaps = [item for item in checks if item["status"] != "ok"]
    return {
        "checks": checks,
        "gaps": gaps,
        "summary": (
            "no OBSMEM mirror gaps"
            if not gaps
            else f"{len(gaps)} OBSMEM mirror gap(s) detected"
        ),
    }


def _check_continuity_readiness(project_root: Path) -> dict[str, Any]:
    memory_exe = shutil.which("memory")
    if not memory_exe:
        return {
            "ok": False,
            "summary": "memory CLI not found on PATH",
            "memory_exe": "",
            "stdout": "",
            "stderr": "",
            "returncode": 127,
        }

    result = _run_command(
        [
            memory_exe,
            "context",
            "--project",
            "--limit",
            "1",
            "--fts-only",
            "--query",
            "CiscoAutoFlash",
        ],
        cwd=project_root,
        timeout=30,
    )
    output = result.stdout.strip()
    ok = result.returncode == 0 and bool(output)
    return {
        "ok": ok,
        "summary": (
            "EchoVault continuity looks ready"
            if ok
            else "EchoVault continuity is not ready"
        ),
        "memory_exe": memory_exe,
        "stdout": result.stdout[:2000],
        "stderr": result.stderr[:2000],
        "returncode": result.returncode,
    }


def _build_recommendations(summary: dict[str, Any]) -> list[str]:
    dirty_files = summary["dirty_files"]["items"]
    mirror_gaps = summary["mirror_gaps"]
    recommendations: list[str] = []
    if dirty_files:
        recommendations.append("Commit, stash, or discard the dirty repo files before closing.")
    if mirror_gaps:
        recommendations.append("Refresh the stale or missing OBSMEM mirror pages.")
    if not summary["memory_lint_checklist"]["present"]:
        recommendations.append(
            "Restore OBSMEM/analyses/Memory_Lint_Checklist.md before closing."
        )
    if not summary["continuity"]["ok"]:
        recommendations.append(
            "Run the local memory CLI health path and resolve continuity issues."
        )
    if not recommendations:
        recommendations.append("Session is clean enough to close.")
    return recommendations


def analyze_session_close(
    *,
    project_root: Path = PROJECT_ROOT,
    obsmem_root: Path = OBSMEM_ROOT,
) -> dict[str, Any]:
    dirty_files = _collect_dirty_files(project_root)
    mirror_checks = _collect_obsmem_mirror_checks(
        project_root,
        obsmem_root,
        dirty_files["items"],
    )
    memory_lint_checklist = _memory_lint_presence(obsmem_root)
    continuity = _check_continuity_readiness(project_root)
    ready = (
        dirty_files["ok"]
        and not dirty_files["items"]
        and not mirror_checks["gaps"]
        and memory_lint_checklist["present"]
        and continuity["ok"]
    )
    checks = [
        CheckResult(
            name="dirty_files",
            ok=dirty_files["ok"] and not dirty_files["items"],
            severity="error",
            summary=dirty_files["summary"],
            details=[item["raw"] for item in dirty_files["items"]],
            data={"count": len(dirty_files["items"])},
        ),
        CheckResult(
            name="obsmem_mirror_gaps",
            ok=not mirror_checks["gaps"],
            severity="error",
            summary=mirror_checks["summary"],
            details=[
                f"{item['path']} :: {item['status']} :: {item['reason']}"
                for item in mirror_checks["gaps"]
            ],
            data={"total": len(mirror_checks["checks"])},
        ),
        CheckResult(
            name="memory_lint_checklist",
            ok=memory_lint_checklist["present"],
            severity="error",
            summary=memory_lint_checklist["summary"],
            details=[memory_lint_checklist["path"]],
            data={
                "present": memory_lint_checklist["present"],
                "size_bytes": memory_lint_checklist["size_bytes"],
            },
        ),
        CheckResult(
            name="continuity_readiness",
            ok=continuity["ok"],
            severity="error",
            summary=continuity["summary"],
            details=[
                f"memory_exe={continuity['memory_exe']}",
                f"returncode={continuity['returncode']}",
            ]
            + ([continuity["stderr"]] if continuity["stderr"] else []),
            data={
                "memory_exe": continuity["memory_exe"],
                "returncode": continuity["returncode"],
            },
        ),
    ]
    summary: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "project_root": str(project_root),
        "obsmem_root": str(obsmem_root),
        "status": "CLEAN" if ready else "ACTION_REQUIRED",
        "dirty_files": dirty_files,
        "mirror_checks": mirror_checks["checks"],
        "mirror_gaps": mirror_checks["gaps"],
        "memory_lint_checklist": memory_lint_checklist,
        "continuity": continuity,
        "checks": [asdict(check) for check in checks],
    }
    summary["recommendations"] = _build_recommendations(summary)
    return summary


def _render_markdown(summary: dict[str, Any]) -> str:
    dirty_files = summary["dirty_files"]["items"]
    mirror_checks = summary["mirror_checks"]
    recommendations = summary["recommendations"]
    lines = [
        "# CiscoAutoFlash Session Close",
        "",
        f"- Status: {summary['status']}",
        f"- Generated at: {summary['generated_at']}",
        f"- Project root: {summary['project_root']}",
        f"- OBSMEM root: {summary['obsmem_root']}",
        f"- Dirty files: {len(dirty_files)}",
        f"- Mirror gaps: {len(summary['mirror_gaps'])}",
        (
            "- Memory lint checklist: "
            f"{'present' if summary['memory_lint_checklist']['present'] else 'missing'}"
        ),
        (
            "- Continuity readiness: "
            f"{'ready' if summary['continuity']['ok'] else 'not ready'}"
        ),
        "",
        "## Checks",
        "| Check | OK | Severity | Summary |",
        "| --- | --- | --- | --- |",
    ]
    for check in summary["checks"]:
        lines.append(
            f"| {check['name']} | {'yes' if check['ok'] else 'no'} | "
            f"{check['severity']} | {check['summary']} |"
        )
    lines.extend(["", "## Dirty Files"])
    if dirty_files:
        lines.append("| Status | Path |")
        lines.append("| --- | --- |")
        for item in dirty_files:
            lines.append(f"| {item['status']} | {item['path']} |")
    else:
        lines.append("- No dirty files.")
    lines.extend(["", "## Mirror Checks"])
    lines.append("| Mirror | Status | Reason |")
    lines.append("| --- | --- | --- |")
    for item in mirror_checks:
        lines.append(f"| {item['path']} | {item['status']} | {item['reason']} |")
    lines.extend(["", "## Recommendations"])
    lines.extend([f"- {item}" for item in recommendations])
    return "\n".join(lines) + "\n"


def _write_summary_files(output_dir: Path, summary: dict[str, Any]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_json = output_dir / "summary.json"
    summary_md = output_dir / "summary.md"
    rendered = _render_markdown(summary)
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_md.write_text(rendered, encoding="utf-8")
    return summary_json, summary_md


def _write_obsmem_draft(summary: dict[str, Any], output_dir: Path) -> Path:
    draft_dir = INBOX_ROOT
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / f"session_close_{_timestamp()}.md"
    dirty_files = summary["dirty_files"]["items"]
    lines = [
        "---",
        "type: project-note",
        "status: draft",
        "source_of_truth: repo",
        "repo_refs:",
        "  - C:\\PROJECT\\AGENTS.md",
        "  - C:\\PROJECT\\OBSMEM\\AGENTS.md",
        "related:",
        "  - [[CiscoAutoFlash]]",
        "  - [[Knowledge_System_Model]]",
        f"last_verified: {datetime.now().date().isoformat()}",
        "---",
        "",
        "# Session Close Draft",
        "",
        f"- Status: {summary['status']}",
        f"- Generated at: {summary['generated_at']}",
        "",
        "## Dirty Files",
    ]
    if dirty_files:
        lines.extend([f"- {item['path']}" for item in dirty_files])
    else:
        lines.append("- No dirty files.")
    lines.extend(
        [
            "",
            "## Mirror Gaps",
            *[f"- {item['path']} :: {item['status']}" for item in summary["mirror_gaps"]],
            "",
            "## Recommendations",
            *[f"- {item}" for item in summary["recommendations"]],
            "",
            "## Session Close Output",
            f"- Summary: {output_dir / 'summary.md'}",
            f"- JSON: {output_dir / 'summary.json'}",
        ]
    )
    draft_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return draft_path


def _save_echovault(summary: dict[str, Any], summary_md: Path) -> dict[str, Any]:
    memory_exe = shutil.which("memory")
    if not memory_exe:
        return {
            "ok": False,
            "memory_exe": "",
            "returncode": 127,
            "stdout": "",
            "stderr": "memory CLI not found on PATH",
            "summary": "memory CLI not found on PATH",
        }

    title = (
        "CiscoAutoFlash session close "
        f"{summary['generated_at'].replace(':', '').replace('-', '').replace('T', '_')}"
    )
    related_files = [
        summary_md,
        Path(summary["project_root"]) / "AGENTS.md",
        Path(summary["obsmem_root"]) / "AGENTS.md",
    ]
    dirty_paths = [Path(item["path"]) for item in summary["dirty_files"]["items"][:5]]
    related_arg = ",".join(str(path) for path in related_files + dirty_paths)
    command = [
        memory_exe,
        "save",
        "--title",
        title,
        "--what",
        "Captured a CiscoAutoFlash session close summary.",
        "--why",
        "Preserves the closing state, dirty files, mirror gaps, and continuity readiness.",
        "--impact",
        "Used as the durable continuity handoff for the next Codex session.",
        "--tags",
        "ciscoautoflash,session-close,continuity,devtools",
        "--category",
        "context",
        "--project",
        "CiscoAutoFlash",
        "--details-file",
        str(summary_md),
        "--related-files",
        related_arg,
    ]
    result = _run_command(command, cwd=PROJECT_ROOT, timeout=45)
    return {
        "ok": result.returncode == 0,
        "memory_exe": memory_exe,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "summary": (
            "EchoVault save succeeded"
            if result.returncode == 0
            else "EchoVault save failed"
        ),
        "command": " ".join(shlex.quote(part) for part in command),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze session close readiness for CiscoAutoFlash."
    )
    parser.add_argument(
        "--save-echovault",
        action="store_true",
        help="Save the session close summary to the local EchoVault memory CLI.",
    )
    parser.add_argument(
        "--write-obsmem-draft",
        action="store_true",
        help="Write a draft note under OBSMEM/inbox for follow-up synthesis.",
    )
    args = parser.parse_args(argv)

    output_dir = BUILD_ROOT / _timestamp()
    summary = analyze_session_close()
    summary["artifacts"] = {
        "output_dir": str(output_dir),
        "summary_json": str(output_dir / "summary.json"),
        "summary_md": str(output_dir / "summary.md"),
    }
    summary_json, summary_md = _write_summary_files(output_dir, summary)

    if args.write_obsmem_draft:
        draft_path = _write_obsmem_draft(summary, output_dir)
        summary["artifacts"]["obsmem_draft"] = str(draft_path)
    if args.save_echovault:
        save_result = _save_echovault(summary, summary_md)
        summary["continuity"]["echovault_save"] = save_result
        summary["artifacts"]["echovault_summary_md"] = str(summary_md)
    if args.write_obsmem_draft or args.save_echovault:
        _write_summary_files(output_dir, summary)

    _print_console_text(_render_markdown(summary))
    _print_console_text(f"summary_json: {summary_json}")
    _print_console_text(f"summary_md: {summary_md}")
    if args.write_obsmem_draft:
        _print_console_text(f"obsmem_draft: {summary['artifacts']['obsmem_draft']}")
    if args.save_echovault:
        echo_result = summary["continuity"].get("echovault_save", {})
        if isinstance(echo_result, dict):
            _print_console_text(
                f"echovault_save: {'OK' if echo_result.get('ok') else 'FAIL'} | "
                f"{echo_result.get('summary', '')}"
            )

    ready = (
        summary["status"] == "CLEAN"
        and (
            not args.save_echovault
            or bool(summary["continuity"].get("echovault_save", {}).get("ok", False))
        )
        and (
            not args.write_obsmem_draft
            or Path(summary["artifacts"].get("obsmem_draft", "")).exists()
        )
    )
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
