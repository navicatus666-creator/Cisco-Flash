from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 - local developer helper uses subprocess for repo inspection
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ciscoautoflash.devtools import obsmem_lint, session_close

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OBSMEM_ROOT = PROJECT_ROOT / "OBSMEM"
OUTPUT_ROOT = PROJECT_ROOT / "build" / "devtools" / "evidence_pack"
LATEST_SUMMARY_PATH = OUTPUT_ROOT / "latest_summary.json"
HELPER_ROOTS = {
    "bootstrap": PROJECT_ROOT / "build" / "devtools" / "bootstrap",
    "ui_smoke": PROJECT_ROOT / "build" / "devtools" / "ui_smoke",
}
DEFAULT_TASK_TYPE = "session-close"
SUPPORTED_TASK_TYPES = {"session-close", "repo-health"}
RELEVANT_CODE_REFS = {
    "session-close": [
        "C:\\PROJECT\\AGENTS.md",
        "C:\\PROJECT\\README.md",
        "C:\\PROJECT\\ciscoautoflash\\devtools\\session_close.py",
        "C:\\PROJECT\\ciscoautoflash\\devtools\\obsmem_chronicler.py",
        "C:\\PROJECT\\scripts\\run_session_close.py",
        "C:\\PROJECT\\scripts\\run_obsmem_chronicler.py",
        "C:\\PROJECT\\OBSMEM\\mirrors\\Current_Work.md",
        "C:\\PROJECT\\OBSMEM\\concepts\\Project_Chronicler_Workflow.md",
    ],
    "repo-health": [
        "C:\\PROJECT\\AGENTS.md",
        "C:\\PROJECT\\README.md",
        "C:\\PROJECT\\docs\\mcp_stack.md",
        "C:\\PROJECT\\scripts\\run_project_bootstrap.py",
        "C:\\PROJECT\\scripts\\run_obsmem_lint.py",
        "C:\\PROJECT\\scripts\\run_ui_smoke.py",
    ],
}


@dataclass(slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(slots=True)
class HypothesisRecord:
    id: str
    summary: str
    severity: str
    status: str
    recommended_action: str
    supporting_evidence: list[str]
    contradicting_evidence: list[str]
    unknowns: list[str]


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


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
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 30,
) -> CommandResult:
    completed = subprocess.run(  # nosec B603 - fixed local commands only
        command,
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
        stdout=(completed.stdout or "").rstrip("\r\n"),
        stderr=(completed.stderr or "").rstrip("\r\n"),
    )


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


def _collect_repo_state(project_root: Path) -> dict[str, Any]:
    branch = _run_command(["git", "branch", "--show-current"], cwd=project_root, timeout=15)
    head = _run_command(["git", "rev-parse", "HEAD"], cwd=project_root, timeout=15)
    subject = _run_command(["git", "log", "-1", "--pretty=%s"], cwd=project_root, timeout=15)
    status = _run_command(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=project_root,
        timeout=30,
    )
    dirty_items = [
        _parse_git_status_line(line)
        for line in status.stdout.splitlines()
        if line.strip()
    ]
    return {
        "branch": branch.stdout or "unknown",
        "head_sha": head.stdout or "unknown",
        "head_subject": subject.stdout or "unknown",
        "dirty_files": dirty_items,
        "dirty_count": len(dirty_items),
        "git_ok": branch.returncode == 0 and head.returncode == 0 and subject.returncode == 0,
    }


def _latest_summary(helper_root: Path) -> dict[str, Any] | None:
    if not helper_root.exists():
        return None
    for candidate in sorted(
        (path for path in helper_root.iterdir() if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    ):
        summary_path = candidate / "summary.json"
        if not summary_path.exists():
            continue
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        payload["_summary_path"] = str(summary_path)
        payload["_output_dir"] = str(candidate)
        return payload
    return None


def _helper_statuses(
    *,
    session_close_summary: dict[str, Any],
    memory_lint_summary: dict[str, Any],
    bootstrap_summary: dict[str, Any] | None,
    ui_smoke_summary: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    statuses = [
        {
            "name": "session_close",
            "status": session_close_summary.get("status", "UNKNOWN"),
            "source": "live-analysis",
            "completed_at": session_close_summary.get("generated_at", ""),
            "path": "",
            "summary": session_close_summary.get("status", "UNKNOWN"),
        },
        {
            "name": "memory_lint",
            "status": memory_lint_summary.get("status", "UNKNOWN"),
            "source": "live-analysis",
            "completed_at": memory_lint_summary.get("generated_at", ""),
            "path": memory_lint_summary.get("summary_json", ""),
            "summary": (
                f"errors={memory_lint_summary.get('error_count', 0)}, "
                f"warnings={memory_lint_summary.get('warning_count', 0)}"
            ),
        },
    ]
    for name, payload in (
        ("bootstrap", bootstrap_summary),
        ("ui_smoke", ui_smoke_summary),
    ):
        if payload is None:
            statuses.append(
                {
                    "name": name,
                    "status": "MISSING",
                    "source": "artifact",
                    "completed_at": "",
                    "path": "",
                    "summary": f"{name} helper artifact missing",
                }
            )
            continue
        statuses.append(
            {
                "name": name,
                "status": payload.get("status", "UNKNOWN"),
                "source": "artifact",
                "completed_at": payload.get("completed_at", payload.get("generated_at", "")),
                "path": payload.get("_summary_path", ""),
                "summary": payload.get("failing_step", "") or payload.get("status", "UNKNOWN"),
            }
        )
    return statuses


def _tail_lines(path: Path, *, limit: int = 12) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return [line for line in lines[-limit:] if line.strip()]


def _bootstrap_failures(bootstrap_summary: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not bootstrap_summary:
        return []
    failures: list[dict[str, Any]] = []
    for step in bootstrap_summary.get("steps", []):
        if step.get("ok", False):
            continue
        log_path = Path(str(step.get("log_path", "")))
        failures.append(
            {
                "step": step.get("name", ""),
                "returncode": step.get("returncode", 1),
                "required": bool(step.get("required", True)),
                "log_path": str(log_path),
                "excerpt": _tail_lines(log_path),
            }
        )
    return failures


def _lint_findings(memory_lint_summary: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for finding in memory_lint_summary.get("findings", []):
        if not isinstance(finding, dict):
            continue
        findings.append(
            {
                "severity": str(finding.get("severity", "warning")),
                "code": str(finding.get("code", "")),
                "path": str(finding.get("path", "")),
                "message": str(finding.get("message", "")),
            }
        )
    return findings


def _relevant_logs(
    *,
    session_close_summary: dict[str, Any],
    bootstrap_failures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for failure in bootstrap_failures:
        records.append(
            {
                "source": f"bootstrap:{failure['step']}",
                "path": failure["log_path"],
                "lines": failure["excerpt"],
            }
        )
    for check in session_close_summary.get("checks", []):
        if bool(check.get("ok", False)):
            continue
        details = [str(item) for item in check.get("details", [])[:8]]
        records.append(
            {
                "source": f"session_close:{check.get('name', '')}",
                "path": "",
                "lines": details,
            }
        )
    return records


def _hypothesis_status(
    supporting_evidence: list[str],
    contradicting_evidence: list[str],
    unknowns: list[str],
) -> str:
    if supporting_evidence and not contradicting_evidence:
        return "supported"
    if contradicting_evidence and not supporting_evidence:
        return "contradicted"
    if supporting_evidence and contradicting_evidence:
        return "mixed"
    if unknowns:
        return "unknown"
    return "contradicted"


def _build_hypotheses(
    *,
    repo_state: dict[str, Any],
    session_close_summary: dict[str, Any],
    memory_lint_summary: dict[str, Any],
    helper_statuses: list[dict[str, Any]],
    bootstrap_failures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    helper_index = {item["name"]: item for item in helper_statuses}

    hypotheses: list[HypothesisRecord] = []

    dirty_support = []
    dirty_contradict = []
    if repo_state["dirty_count"] > 0:
        dirty_support.append(f"git reports {repo_state['dirty_count']} dirty file(s)")
    else:
        dirty_contradict.append("git working tree is clean")
    hypotheses.append(
        HypothesisRecord(
            id="dirty_repo_state",
            summary="Dirty working tree is blocking a clean close or clean verdict.",
            severity="error",
            status=_hypothesis_status(dirty_support, dirty_contradict, []),
            recommended_action=(
                "Commit, stash, or discard the dirty files before trusting "
                "a clean verdict."
            ),
            supporting_evidence=dirty_support,
            contradicting_evidence=dirty_contradict,
            unknowns=[],
        )
    )

    freshness = session_close_summary.get("current_work_freshness", {})
    stale_support = []
    stale_contradict = []
    if not freshness.get("ok", False):
        mismatches = freshness.get("mismatches", [])
        stale_support.append(
            "Current_Work mismatches live git state"
            + (f" ({', '.join(mismatches)})" if mismatches else "")
        )
    elif freshness:
        stale_contradict.append(
            "Current_Work matches the live branch, HEAD, commit subject, "
            "and dirty count"
        )
    stale_unknowns = [] if freshness else ["Current_Work freshness data missing"]
    hypotheses.append(
        HypothesisRecord(
            id="current_work_stale",
            summary="Current_Work mirror may be stale relative to live git state.",
            severity="error",
            status=_hypothesis_status(stale_support, stale_contradict, stale_unknowns),
            recommended_action=(
                "Refresh Current_Work with the chronicler before trusting "
                "close readiness."
            ),
            supporting_evidence=stale_support,
            contradicting_evidence=stale_contradict,
            unknowns=stale_unknowns,
        )
    )

    lint_support = []
    lint_contradict = []
    lint_unknowns: list[str] = []
    lint_errors = int(memory_lint_summary.get("error_count", 0))
    lint_warnings = int(memory_lint_summary.get("warning_count", 0))
    lint_severity = "error" if lint_errors else "warning"
    if lint_errors or lint_warnings:
        lint_support.append(
            f"OBSMEM lint reports errors={lint_errors}, warnings={lint_warnings}"
        )
    else:
        lint_contradict.append("OBSMEM strict lint passes")
    hypotheses.append(
        HypothesisRecord(
            id="obsmem_drift",
            summary="OBSMEM structure or metadata is out of contract with repo expectations.",
            severity=lint_severity,
            status=_hypothesis_status(lint_support, lint_contradict, lint_unknowns),
            recommended_action="Fix OBSMEM lint findings before relying on wiki continuity.",
            supporting_evidence=lint_support,
            contradicting_evidence=lint_contradict,
            unknowns=lint_unknowns,
        )
    )

    bootstrap_status = helper_index.get("bootstrap", {})
    gate_support = []
    gate_contradict = []
    gate_unknowns = []
    if bootstrap_status.get("status") == "MISSING":
        gate_unknowns.append("bootstrap helper artifact missing")
    elif bootstrap_status.get("status") != "READY":
        gate_support.append(f"bootstrap status is {bootstrap_status.get('status', 'UNKNOWN')}")
        if bootstrap_failures:
            gate_support.extend(
                [f"failing bootstrap step: {item['step']}" for item in bootstrap_failures]
            )
    else:
        gate_contradict.append("latest bootstrap artifact is READY")
    hypotheses.append(
        HypothesisRecord(
            id="quality_gate_regression",
            summary="Recent quality/runtime gates indicate a regression or an unverified state.",
            severity="error",
            status=_hypothesis_status(gate_support, gate_contradict, gate_unknowns),
            recommended_action=(
                "Rerun or inspect project bootstrap before making a "
                "high-stakes verdict."
            ),
            supporting_evidence=gate_support,
            contradicting_evidence=gate_contradict,
            unknowns=gate_unknowns,
        )
    )

    ui_status = helper_index.get("ui_smoke", {})
    smoke_support = []
    smoke_contradict = []
    smoke_unknowns = []
    if ui_status.get("status") == "MISSING":
        smoke_unknowns.append("ui_smoke helper artifact missing")
    elif ui_status.get("status") not in {"OK", "READY"}:
        smoke_support.append(f"ui_smoke status is {ui_status.get('status', 'UNKNOWN')}")
    else:
        smoke_contradict.append("latest ui_smoke artifact is healthy")
    hypotheses.append(
        HypothesisRecord(
            id="ui_or_runtime_uncertain",
            summary="Recent UI/runtime smoke evidence is missing or degraded.",
            severity="warning",
            status=_hypothesis_status(smoke_support, smoke_contradict, smoke_unknowns),
            recommended_action=(
                "Refresh UI smoke evidence if the task depends on "
                "operator-facing behavior."
            ),
            supporting_evidence=smoke_support,
            contradicting_evidence=smoke_contradict,
            unknowns=smoke_unknowns,
        )
    )

    continuity = session_close_summary.get("continuity", {})
    continuity_support = []
    continuity_contradict = []
    continuity_unknowns: list[str] = []
    if not continuity.get("ok", False):
        continuity_support.append(continuity.get("summary", "EchoVault continuity is not ready"))
    else:
        continuity_contradict.append("EchoVault continuity probe is ready")
    hypotheses.append(
        HypothesisRecord(
            id="continuity_gap",
            summary="Continuity handoff is not ready for a safe session transition.",
            severity="warning",
            status=_hypothesis_status(
                continuity_support,
                continuity_contradict,
                continuity_unknowns,
            ),
            recommended_action="Repair EchoVault continuity before closing a substantial session.",
            supporting_evidence=continuity_support,
            contradicting_evidence=continuity_contradict,
            unknowns=continuity_unknowns,
        )
    )

    return [asdict(item) for item in hypotheses]


def _collect_unknowns(
    *,
    helper_statuses: list[dict[str, Any]],
    hypotheses: list[dict[str, Any]],
) -> list[str]:
    unknowns: list[str] = []
    for helper in helper_statuses:
        if helper.get("status") == "MISSING":
            unknowns.append(f"missing helper artifact: {helper['name']}")
    for hypothesis in hypotheses:
        unknowns.extend(str(item) for item in hypothesis.get("unknowns", []))
    return sorted(set(unknowns))


def _relevant_code_refs(task_type: str) -> list[str]:
    return list(RELEVANT_CODE_REFS.get(task_type, RELEVANT_CODE_REFS[DEFAULT_TASK_TYPE]))


def build_evidence_pack(
    output_dir: Path,
    *,
    task_type: str = DEFAULT_TASK_TYPE,
    project_root: Path = PROJECT_ROOT,
    obsmem_root: Path = OBSMEM_ROOT,
    stale_days: int = 60,
) -> dict[str, Any]:
    if task_type not in SUPPORTED_TASK_TYPES:
        raise ValueError(f"Unsupported task_type: {task_type}")

    repo_state = _collect_repo_state(project_root)
    session_close_summary = session_close.analyze_session_close(
        project_root=project_root,
        obsmem_root=obsmem_root,
    )
    memory_lint_summary = obsmem_lint.lint_obsmem(
        vault_root=obsmem_root,
        stale_days=stale_days,
        output_root=project_root / "build" / "devtools" / "memory_lint",
    )
    bootstrap_summary = _latest_summary(HELPER_ROOTS["bootstrap"])
    ui_smoke_summary = _latest_summary(HELPER_ROOTS["ui_smoke"])

    helper_statuses = _helper_statuses(
        session_close_summary=session_close_summary,
        memory_lint_summary=memory_lint_summary,
        bootstrap_summary=bootstrap_summary,
        ui_smoke_summary=ui_smoke_summary,
    )
    bootstrap_failures = _bootstrap_failures(bootstrap_summary)
    lint_findings = _lint_findings(memory_lint_summary)
    relevant_logs = _relevant_logs(
        session_close_summary=session_close_summary,
        bootstrap_failures=bootstrap_failures,
    )
    hypotheses = _build_hypotheses(
        repo_state=repo_state,
        session_close_summary=session_close_summary,
        memory_lint_summary=memory_lint_summary,
        helper_statuses=helper_statuses,
        bootstrap_failures=bootstrap_failures,
    )
    unknowns = _collect_unknowns(helper_statuses=helper_statuses, hypotheses=hypotheses)
    summary = {
        "case_id": f"{task_type}-{_timestamp()}",
        "generated_at": _iso_now(),
        "task_type": task_type,
        "status": "READY_FOR_JUDGE",
        "project_root": str(project_root),
        "obsmem_root": str(obsmem_root),
        "repo": repo_state,
        "helper_statuses": helper_statuses,
        "live_checks": {
            "session_close": session_close_summary,
            "memory_lint": memory_lint_summary,
        },
        "lint_findings": lint_findings,
        "test_failures": bootstrap_failures,
        "relevant_logs": relevant_logs,
        "relevant_code_refs": _relevant_code_refs(task_type),
        "hypotheses": hypotheses,
        "unknowns": unknowns,
        "artifacts": {
            "output_dir": str(output_dir),
            "summary_json": str(output_dir / "summary.json"),
            "summary_md": str(output_dir / "summary.md"),
            "summary_toon": str(output_dir / "summary.toon"),
        },
    }
    return summary


def render_markdown(summary: dict[str, Any]) -> str:
    repo = summary["repo"]
    helper_statuses = summary["helper_statuses"]
    hypotheses = summary["hypotheses"]
    lines = [
        "# CiscoAutoFlash Evidence Pack",
        "",
        f"- Case ID: `{summary['case_id']}`",
        f"- Task type: `{summary['task_type']}`",
        f"- Status: `{summary['status']}`",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Branch: `{repo['branch']}`",
        f"- HEAD: `{repo['head_sha'][:12]}`",
        f"- Commit: {repo['head_subject']}",
        f"- Dirty files: {repo['dirty_count']}",
        "",
        "## Helper Statuses",
        "| Helper | Source | Status | Completed | Path |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in helper_statuses:
        lines.append(
            f"| {item['name']} | {item['source']} | {item['status']} | "
            f"{item['completed_at'] or '—'} | {item['path'] or '—'} |"
        )
    lines.extend(
        [
            "",
            "## Hypotheses",
            "| ID | Severity | Status | Summary |",
            "| --- | --- | --- | --- |",
        ]
    )
    for item in hypotheses:
        lines.append(
            f"| {item['id']} | {item['severity']} | {item['status']} | {item['summary']} |"
        )
    lines.extend(["", "## Unknowns"])
    if summary["unknowns"]:
        lines.extend([f"- {item}" for item in summary["unknowns"]])
    else:
        lines.append("- none")
    lines.extend(["", "## Relevant Code Refs"])
    lines.extend([f"- `{item}`" for item in summary["relevant_code_refs"]])
    return "\n".join(lines) + "\n"


def render_toon(summary: dict[str, Any]) -> str:
    lines = [
        "meta:",
        f"  case_id: {summary['case_id']}",
        f"  task_type: {summary['task_type']}",
        f"  generated_at: {summary['generated_at']}",
        "",
        "repo:",
        f"  branch: {summary['repo']['branch']}",
        f"  head_sha: {summary['repo']['head_sha']}",
        f"  head_subject: {summary['repo']['head_subject']}",
        f"  dirty_count: {summary['repo']['dirty_count']}",
        "",
        "helper_statuses[]:",
        "name | source | status | completed_at | path",
    ]
    for item in summary["helper_statuses"]:
        lines.append(
            f"{item['name']} | {item['source']} | {item['status']} | "
            f"{item['completed_at'] or '—'} | {item['path'] or '—'}"
        )
    lines.extend(["", "dirty_files[]:", "status | path"])
    for item in summary["repo"]["dirty_files"]:
        lines.append(f"{item['status']} | {item['path']}")
    if not summary["repo"]["dirty_files"]:
        lines.append("clean | —")
    lines.extend(["", "lint_findings[]:", "severity | code | path | message"])
    for item in summary["lint_findings"]:
        lines.append(
            f"{item['severity']} | {item['code'] or '—'} | "
            f"{item['path'] or '—'} | {item['message'] or '—'}"
        )
    if not summary["lint_findings"]:
        lines.append("none | — | — | —")
    lines.extend(["", "test_failures[]:", "step | returncode | log_path"])
    for item in summary["test_failures"]:
        lines.append(f"{item['step']} | {item['returncode']} | {item['log_path'] or '—'}")
    if not summary["test_failures"]:
        lines.append("none | 0 | —")
    lines.extend(["", "hypotheses[]:", "id | severity | status | summary"])
    for item in summary["hypotheses"]:
        lines.append(
            f"{item['id']} | {item['severity']} | {item['status']} | {item['summary']}"
        )
    lines.extend(["", "supporting_evidence[]:", "hypothesis_id | fact"])
    support_rows = 0
    for item in summary["hypotheses"]:
        for fact in item.get("supporting_evidence", []):
            lines.append(f"{item['id']} | {fact}")
            support_rows += 1
    if support_rows == 0:
        lines.append("none | —")
    lines.extend(["", "contradicting_evidence[]:", "hypothesis_id | fact"])
    contradict_rows = 0
    for item in summary["hypotheses"]:
        for fact in item.get("contradicting_evidence", []):
            lines.append(f"{item['id']} | {fact}")
            contradict_rows += 1
    if contradict_rows == 0:
        lines.append("none | —")
    lines.extend(["", "unknowns[]:", "item"])
    if summary["unknowns"]:
        lines.extend(summary["unknowns"])
    else:
        lines.append("none")
    return "\n".join(lines) + "\n"


def _write_summary_files(output_dir: Path, summary: dict[str, Any]) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_json = output_dir / "summary.json"
    summary_md = output_dir / "summary.md"
    summary_toon = output_dir / "summary.toon"
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_md.write_text(render_markdown(summary), encoding="utf-8")
    summary_toon.write_text(render_toon(summary), encoding="utf-8")
    return summary_json, summary_md, summary_toon


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a structured evidence pack for CiscoAutoFlash high-stakes decisions."
    )
    parser.add_argument(
        "--task-type",
        choices=sorted(SUPPORTED_TASK_TYPES),
        default=DEFAULT_TASK_TYPE,
        help="Evidence focus. Defaults to session-close.",
    )
    parser.add_argument(
        "--json-out",
        default="",
        help=(
            "Optional explicit JSON output path. Default uses "
            "build/devtools/evidence_pack/<timestamp>/summary.json."
        ),
    )
    parser.add_argument(
        "--stale-days",
        type=int,
        default=60,
        help="Freshness threshold passed through to OBSMEM lint.",
    )
    args = parser.parse_args(argv)

    output_dir = OUTPUT_ROOT / _timestamp()
    summary = build_evidence_pack(
        output_dir,
        task_type=args.task_type,
        stale_days=args.stale_days,
    )
    summary_json = Path(args.json_out) if args.json_out else output_dir / "summary.json"
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    if str(summary_json) != summary["artifacts"]["summary_json"]:
        summary["artifacts"]["summary_json"] = str(summary_json)
    _, summary_md, summary_toon = _write_summary_files(output_dir, summary)
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    LATEST_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    LATEST_SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    _print_console_text(render_markdown(summary))
    _print_console_text(f"summary_json: {summary_json}")
    _print_console_text(f"summary_md: {summary_md}")
    _print_console_text(f"summary_toon: {summary_toon}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
