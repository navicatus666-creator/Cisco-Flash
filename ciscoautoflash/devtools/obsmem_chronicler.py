from __future__ import annotations

import argparse
import hashlib
import json
import subprocess  # nosec B404 - local developer helper uses subprocess for repo inspection
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OBSMEM_ROOT = PROJECT_ROOT / "OBSMEM"
OUTPUT_ROOT = PROJECT_ROOT / "build" / "devtools" / "obsmem_chronicler"
RUNTIME_ROOT = OUTPUT_ROOT / "runtime"
STATE_PATH = RUNTIME_ROOT / "state.json"
EVENTS_PATH = RUNTIME_ROOT / "events.jsonl"
CURRENT_WORK_PATH = OBSMEM_ROOT / "mirrors" / "Current_Work.md"
DAILY_ROOT = OBSMEM_ROOT / "daily"
LOG_PATH = OBSMEM_ROOT / "log.md"
MANUAL_NOTES_START = "<!-- CHRONICLER:MANUAL-NOTES-START -->"
MANUAL_NOTES_END = "<!-- CHRONICLER:MANUAL-NOTES-END -->"
HELPER_ROOTS = {
    "bootstrap": PROJECT_ROOT / "build" / "devtools" / "bootstrap",
    "memory_lint": PROJECT_ROOT / "build" / "devtools" / "memory_lint",
    "session_close": PROJECT_ROOT / "build" / "devtools" / "session_close",
    "ui_smoke": PROJECT_ROOT / "build" / "devtools" / "ui_smoke",
}
EVENT_TITLES = {
    "session_start": "Session started",
    "session_stop": "Session stopped",
    "snapshot": "Snapshot updated",
    "win": "Victory",
    "issue": "Issue",
    "discovery": "Discovery",
    "decision": "Decision",
    "next-step": "Next step",
}


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


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _iso_now() -> str:
    return _now_utc().isoformat()


def _today_str() -> str:
    return datetime.now().date().isoformat()


def _timestamp() -> str:
    return _now_utc().strftime("%Y%m%d_%H%M%S")


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _write_text_if_changed(path: Path, text: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    current = _read_text(path)
    if current == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def _run_command(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 30,
) -> tuple[int, str, str]:
    completed = subprocess.run(  # nosec B603 - fixed local commands only
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return (
        completed.returncode,
        (completed.stdout or "").rstrip("\r\n"),
        (completed.stderr or "").rstrip("\r\n"),
    )


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _load_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


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


def _repo_state(project_root: Path) -> dict[str, Any]:
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
        for line in status[1].splitlines()
        if line.strip()
    ]
    return {
        "branch": branch[1] or "unknown",
        "head_sha": head[1] or "unknown",
        "head_subject": subject[1] or "unknown",
        "dirty_items": dirty_items,
        "dirty_count": len(dirty_items),
    }


def _focus_area_for_path(rel_path: str) -> str:
    normalized = rel_path.replace("\\", "/")
    if normalized.startswith("ciscoautoflash/ui/") or normalized == "main.py":
        return "UI"
    if normalized.startswith("ciscoautoflash/devtools/") or normalized.startswith("scripts/"):
        return "Devtools"
    if normalized.startswith("tests/"):
        return "Tests"
    if normalized.startswith("docs/"):
        return "Docs"
    if normalized.startswith("OBSMEM/"):
        return "OBSMEM"
    if normalized.startswith(".github/"):
        return "CI"
    if normalized in {"pyproject.toml", "uv.lock"}:
        return "Dependencies"
    if normalized.startswith("ciscoautoflash/"):
        return "Core"
    return "Project"


def _focus_areas(dirty_items: list[dict[str, str]]) -> list[str]:
    return sorted({_focus_area_for_path(item["path"]) for item in dirty_items})


def _chronicler_managed_paths() -> set[str]:
    return {
        "OBSMEM/mirrors/Current_Work.md",
        "OBSMEM/log.md",
        f"OBSMEM/daily/{_today_str()}.md",
    }


def _display_dirty_items(dirty_items: list[dict[str, str]]) -> list[dict[str, str]]:
    managed = _chronicler_managed_paths()
    return [
        item
        for item in dirty_items
        if item["path"].replace("\\", "/") not in managed
    ]


def _latest_helper_summary(helper_root: Path) -> dict[str, Any] | None:
    if not helper_root.exists():
        return None
    candidates = sorted(
        (path for path in helper_root.iterdir() if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    )
    for candidate in candidates:
        summary_path = candidate / "summary.json"
        if not summary_path.exists():
            continue
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        return {
            "path": str(summary_path),
            "status": payload.get("status", "UNKNOWN"),
            "completed_at": payload.get("completed_at", ""),
        }
    return None


def _helper_statuses() -> dict[str, dict[str, Any]]:
    statuses: dict[str, dict[str, Any]] = {}
    for name, root in HELPER_ROOTS.items():
        payload = _latest_helper_summary(root)
        if payload is None:
            statuses[name] = {"status": "MISSING", "path": "", "completed_at": ""}
        else:
            statuses[name] = payload
    return statuses


def _manual_events(events: list[dict[str, Any]], *, limit: int = 12) -> list[dict[str, Any]]:
    interesting = [
        event
        for event in events
        if event.get("event_type") in {"win", "issue", "discovery", "decision", "next-step"}
    ]
    return interesting[-limit:]


def _short_dirty_files(dirty_items: list[dict[str, str]], *, limit: int = 8) -> list[str]:
    return [item["path"] for item in dirty_items[:limit]]


def _summarize_helper_statuses(statuses: dict[str, dict[str, Any]]) -> str:
    parts = [f"{name}:{payload['status']}" for name, payload in sorted(statuses.items())]
    return ", ".join(parts)


def _snapshot_payload(project_root: Path) -> dict[str, Any]:
    repo = _repo_state(project_root)
    display_dirty_items = _display_dirty_items(repo["dirty_items"])
    return {
        "created_at": _iso_now(),
        "repo": repo,
        "display_dirty_items": display_dirty_items,
        "display_dirty_count": len(display_dirty_items),
        "focus_areas": _focus_areas(display_dirty_items),
        "helper_statuses": _helper_statuses(),
        "short_dirty_files": _short_dirty_files(display_dirty_items),
    }


def _snapshot_hash(snapshot: dict[str, Any]) -> str:
    stable_payload = {
        "branch": snapshot["repo"]["branch"],
        "head_sha": snapshot["repo"]["head_sha"],
        "dirty": [(item["status"], item["path"]) for item in snapshot["display_dirty_items"]],
        "helpers": {
            name: payload["status"]
            for name, payload in sorted(snapshot["helper_statuses"].items())
        },
        "focus_areas": snapshot["focus_areas"],
    }
    raw = json.dumps(stable_payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _extract_manual_notes(existing_text: str) -> str:
    if MANUAL_NOTES_START not in existing_text or MANUAL_NOTES_END not in existing_text:
        return "- "
    start = existing_text.index(MANUAL_NOTES_START) + len(MANUAL_NOTES_START)
    end = existing_text.index(MANUAL_NOTES_END)
    block = existing_text[start:end].strip("\n")
    return block.strip() or "- "


def _render_current_work(
    snapshot: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    session_label: str,
) -> str:
    repo = snapshot["repo"]
    recent = _manual_events(events, limit=6)
    focus = snapshot["focus_areas"] or ["Maintenance"]
    dirty_lines = [f"- `{path}`" for path in snapshot["short_dirty_files"]] or ["- clean"]
    helper_lines = [
        f"- `{name}`: `{payload['status']}`"
        for name, payload in sorted(snapshot["helper_statuses"].items())
    ]
    event_lines = []
    for event in recent:
        label = event.get("message", "").strip() or EVENT_TITLES.get(
            event["event_type"],
            event["event_type"],
        )
        event_lines.append(f"- `{event['event_type']}`: {label}")
    if not event_lines:
        event_lines = ["- No manual chronicler events yet."]
    return "\n".join(
        [
            "---",
            "type: mirror",
            "status: active",
            "source_of_truth: repo",
            "repo_refs:",
            "  - C:\\PROJECT\\README.md",
            "  - C:\\PROJECT\\AGENTS.md",
            "  - C:\\PROJECT\\docs\\mcp_stack.md",
            "  - C:\\PROJECT\\scripts\\run_project_bootstrap.py",
            "  - C:\\PROJECT\\scripts\\run_obsmem_lint.py",
            "  - C:\\PROJECT\\scripts\\run_session_close.py",
            "related:",
            '  - "[[CiscoAutoFlash]]"',
            '  - "[[Knowledge_System_Model]]"',
            '  - "[[Project_Chronicler_Workflow]]"',
            "last_verified: " + _today_str(),
            "---",
            "",
            "# Current Work",
            "",
            "## Session now",
            f"- Label: {session_label or 'Unlabelled working session'}",
            f"- Branch: `{repo['branch']}`",
            f"- HEAD: `{repo['head_sha'][:12]}`",
            f"- Commit: {repo['head_subject']}",
            f"- Dirty files: {snapshot['display_dirty_count']}",
            f"- Focus areas: {', '.join(focus)}",
            "",
            "## Dirty paths",
            *dirty_lines,
            "",
            "## Helper health",
            *helper_lines,
            "",
            "## Recent wins and findings",
            *event_lines,
            "",
            "## Notes",
            "- This page is the compact bridge between repo truth and the OBSMEM narrative layer.",
            (
                "- Keep implementation truth in repo files first. "
                "Use this page for current focus and continuity only."
            ),
            "",
            "## Related",
            "- Project hub: [[CiscoAutoFlash]]",
            "- Memory model: [[Knowledge_System_Model]]",
            "- Workflow: [[Project_Chronicler_Workflow]]",
            "",
            "## Read next",
            "- [[CiscoAutoFlash_Current_State]]",
            "- [[Active_Risks]]",
            "- [[Project_Chronicler_Workflow]]",
            "",
        ]
    )


def _render_daily_note(
    note_date: str,
    snapshot: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    existing_text: str,
    session_label: str,
) -> str:
    repo = snapshot["repo"]
    manual_notes = _extract_manual_notes(existing_text)
    recent = _manual_events(events, limit=20)
    grouped: dict[str, list[str]] = {
        "win": [],
        "issue": [],
        "discovery": [],
        "decision": [],
        "next-step": [],
    }
    for event in recent:
        message = event.get("message", "").strip()
        if message:
            grouped.setdefault(event["event_type"], []).append(message)
    helper_lines = [
        f"- `{name}`: `{payload['status']}`"
        for name, payload in sorted(snapshot["helper_statuses"].items())
    ]
    dirty_lines = [
        f"- `{item['status'].strip()}` `{item['path']}`"
        for item in snapshot["display_dirty_items"][:12]
    ] or ["- clean"]

    def _section(title: str, items: list[str], empty: str) -> list[str]:
        return [f"## {title}", *(f"- {item}" for item in items or [empty]), ""]

    return "\n".join(
        [
            "---",
            "type: project-note",
            "status: active",
            "source_of_truth: repo",
            "repo_refs:",
            "  - C:\\PROJECT\\README.md",
            "  - C:\\PROJECT\\AGENTS.md",
            "  - C:\\PROJECT\\OBSMEM\\AGENTS.md",
            "related:",
            '  - "[[CiscoAutoFlash]]"',
            '  - "[[Current_Work]]"',
            '  - "[[Project_Chronicler_Workflow]]"',
            "last_verified: " + _today_str(),
            "---",
            "",
            f"# {note_date}",
            "",
            "## Session snapshot",
            f"- Label: {session_label or 'Unlabelled working session'}",
            f"- Branch: `{repo['branch']}`",
            f"- Commit: `{repo['head_sha'][:12]}` {repo['head_subject']}",
            f"- Focus areas: {', '.join(snapshot['focus_areas'] or ['Maintenance'])}",
            f"- Helper health: {_summarize_helper_statuses(snapshot['helper_statuses'])}",
            "",
            "## Dirty paths",
            *dirty_lines,
            "",
            "## Helper health details",
            *helper_lines,
            "",
            *_section("Victories", grouped.get("win", []), "No victories logged yet."),
            *_section("Issues and losses", grouped.get("issue", []), "No issues logged yet."),
            *_section(
                "Findings and tricks",
                grouped.get("discovery", []),
                "No discoveries logged yet.",
            ),
            *_section("Decisions", grouped.get("decision", []), "No decisions logged yet."),
            *_section("Next steps", grouped.get("next-step", []), "No next steps logged yet."),
            "## Manual Notes",
            MANUAL_NOTES_START,
            manual_notes,
            MANUAL_NOTES_END,
            "",
            "## Related",
            "- [[Current_Work]]",
            "- [[CiscoAutoFlash]]",
            "- [[Project_Chronicler_Workflow]]",
            "",
            "## Read next",
            "- [[Current_Work]]",
            "- [[CiscoAutoFlash_Current_State]]",
            "- [[Project_Chronicler_Workflow]]",
            "",
        ]
    )


def _append_log_event(
    log_path: Path,
    event: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    session_label: str,
) -> None:
    title = EVENT_TITLES.get(event["event_type"], event["event_type"].replace("-", " ").title())
    if event.get("message"):
        title = f"{title} | {event['message']}"
    header = f"## [{_today_str()}] chronicler | {title}"
    existing = _read_text(log_path)
    lines = [
        header,
        f"- timestamp: {event['created_at']}",
        f"- session: `{event.get('session_id', 'none')}`",
        f"- label: {session_label or 'Unlabelled working session'}",
        f"- branch: `{snapshot['repo']['branch']}`",
        f"- head: `{snapshot['repo']['head_sha'][:12]}`",
        f"- focus: {', '.join(snapshot['focus_areas'] or ['Maintenance'])}",
    ]
    if event.get("details"):
        for key, value in sorted(event["details"].items()):
            if isinstance(value, (dict, list)):
                payload = json.dumps(value, ensure_ascii=False)
            else:
                payload = str(value)
            lines.append(f"- {key}: {payload}")
    addition = "\n".join(["", *lines, ""])
    log_path.write_text(existing + addition, encoding="utf-8")


def _record_event(
    runtime_root: Path,
    *,
    event_type: str,
    session_id: str,
    message: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "created_at": _iso_now(),
        "event_type": event_type,
        "session_id": session_id,
        "message": message.strip(),
        "details": details or {},
    }
    _append_jsonl(runtime_root / "events.jsonl", payload)
    return payload


def _initial_state() -> dict[str, Any]:
    return {
        "active_session_id": "",
        "session_label": "",
        "last_snapshot_hash": "",
        "last_snapshot_at": "",
        "last_report": "",
    }


def _write_outputs(
    *,
    vault_root: Path,
    snapshot: dict[str, Any],
    events: list[dict[str, Any]],
    session_label: str,
) -> dict[str, str]:
    current_work = vault_root / "mirrors" / "Current_Work.md"
    note_date = _today_str()
    daily_note = vault_root / "daily" / f"{note_date}.md"
    current_changed = _write_text_if_changed(
        current_work,
        _render_current_work(snapshot, events, session_label=session_label),
    )
    daily_changed = _write_text_if_changed(
        daily_note,
        _render_daily_note(
            note_date,
            snapshot,
            events,
            existing_text=_read_text(daily_note),
            session_label=session_label,
        ),
    )
    return {
        "current_work": str(current_work),
        "daily_note": str(daily_note),
        "current_work_changed": "yes" if current_changed else "no",
        "daily_note_changed": "yes" if daily_changed else "no",
    }


def run_snapshot(
    *,
    project_root: Path,
    vault_root: Path,
    output_root: Path,
    state_path: Path,
    runtime_root: Path,
    session_label: str = "",
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    state = _load_json(state_path, _initial_state())
    snapshot = _snapshot_payload(project_root)
    snapshot_hash = _snapshot_hash(snapshot)
    session_id = state.get("active_session_id", "") or f"snapshot-{_timestamp()}"
    changed = snapshot_hash != state.get("last_snapshot_hash", "")
    event_payload = None
    if changed:
        event_payload = _record_event(
            runtime_root,
            event_type="snapshot",
            session_id=session_id,
            details={
                "dirty_count": snapshot["display_dirty_count"],
                "head_sha": snapshot["repo"]["head_sha"],
                "focus_areas": snapshot["focus_areas"],
            },
        )
    events = _load_events(runtime_root / "events.jsonl")
    artifact_paths = _write_outputs(
        vault_root=vault_root,
        snapshot=snapshot,
        events=events,
        session_label=session_label or state.get("session_label", ""),
    )
    state.update(
        {
            "last_snapshot_hash": snapshot_hash,
            "last_snapshot_at": snapshot["created_at"],
            "session_label": session_label or state.get("session_label", ""),
        }
    )
    _write_json(state_path, state)
    return {
        "status": "UPDATED" if changed else "UNCHANGED",
        "mode": "once",
        "created_at": snapshot["created_at"],
        "session_id": session_id,
        "session_label": state.get("session_label", ""),
        "snapshot": snapshot,
        "event": event_payload,
        "artifacts": artifact_paths,
    }


def run_manual_event(
    *,
    project_root: Path,
    vault_root: Path,
    output_root: Path,
    state_path: Path,
    runtime_root: Path,
    event_type: str,
    message: str,
    session_label: str = "",
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    state = _load_json(state_path, _initial_state())
    session_id = state.get("active_session_id", "") or f"manual-{_timestamp()}"
    snapshot = _snapshot_payload(project_root)
    effective_label = session_label or state.get("session_label", "")
    event_payload = _record_event(
        runtime_root,
        event_type=event_type,
        session_id=session_id,
        message=message,
        details={
            "branch": snapshot["repo"]["branch"],
            "head_sha": snapshot["repo"]["head_sha"],
        },
    )
    _append_log_event(vault_root / "log.md", event_payload, snapshot, session_label=effective_label)
    events = _load_events(runtime_root / "events.jsonl")
    artifact_paths = _write_outputs(
        vault_root=vault_root,
        snapshot=snapshot,
        events=events,
        session_label=effective_label,
    )
    state.update(
        {
            "session_label": effective_label,
            "last_snapshot_hash": _snapshot_hash(snapshot),
            "last_snapshot_at": snapshot["created_at"],
        }
    )
    _write_json(state_path, state)
    return {
        "status": "EVENT_RECORDED",
        "mode": "event",
        "created_at": snapshot["created_at"],
        "session_id": session_id,
        "session_label": effective_label,
        "event": event_payload,
        "snapshot": snapshot,
        "artifacts": artifact_paths,
    }


def _start_session(
    *,
    project_root: Path,
    vault_root: Path,
    runtime_root: Path,
    state: dict[str, Any],
    session_label: str,
) -> dict[str, Any]:
    snapshot = _snapshot_payload(project_root)
    session_id = f"chronicle-{_timestamp()}"
    effective_label = session_label or state.get("session_label", "")
    event_payload = _record_event(
        runtime_root,
        event_type="session_start",
        session_id=session_id,
        message=effective_label,
        details={"head_sha": snapshot["repo"]["head_sha"]},
    )
    _append_log_event(vault_root / "log.md", event_payload, snapshot, session_label=effective_label)
    state.update(
        {
            "active_session_id": session_id,
            "session_label": effective_label,
            "last_snapshot_hash": "",
            "last_snapshot_at": "",
        }
    )
    return state


def _stop_session(
    *,
    project_root: Path,
    vault_root: Path,
    runtime_root: Path,
    state: dict[str, Any],
) -> dict[str, Any]:
    snapshot = _snapshot_payload(project_root)
    session_id = state.get("active_session_id", "") or f"chronicle-{_timestamp()}"
    event_payload = _record_event(
        runtime_root,
        event_type="session_stop",
        session_id=session_id,
        message=state.get("session_label", ""),
        details={"dirty_count": snapshot["repo"]["dirty_count"]},
    )
    _append_log_event(
        vault_root / "log.md",
        event_payload,
        snapshot,
        session_label=state.get("session_label", ""),
    )
    state.update(
        {
            "active_session_id": "",
            "last_snapshot_at": snapshot["created_at"],
        }
    )
    return state


def run_watch(
    *,
    project_root: Path,
    vault_root: Path,
    output_root: Path,
    state_path: Path,
    runtime_root: Path,
    session_label: str = "",
    interval_seconds: int = 90,
    max_cycles: int | None = None,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    state = _load_json(state_path, _initial_state())
    state = _start_session(
        project_root=project_root,
        vault_root=vault_root,
        runtime_root=runtime_root,
        state=state,
        session_label=session_label,
    )
    _write_json(state_path, state)
    cycles = 0
    last_summary: dict[str, Any] | None = None
    try:
        while True:
            last_summary = run_snapshot(
                project_root=project_root,
                vault_root=vault_root,
                output_root=output_root,
                state_path=state_path,
                runtime_root=runtime_root,
                session_label=state.get("session_label", ""),
            )
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            time.sleep(max(5, interval_seconds))
    finally:
        state = _load_json(state_path, _initial_state())
        state = _stop_session(
            project_root=project_root,
            vault_root=vault_root,
            runtime_root=runtime_root,
            state=state,
        )
        _write_json(state_path, state)
    return {
        "status": "WATCH_STOPPED",
        "mode": "watch",
        "cycles": cycles,
        "session_id": state.get("active_session_id", ""),
        "session_label": state.get("session_label", ""),
        "last_summary": last_summary,
    }


def stop_active_session(
    *,
    project_root: Path,
    vault_root: Path,
    state_path: Path,
    runtime_root: Path,
) -> dict[str, Any]:
    runtime_root.mkdir(parents=True, exist_ok=True)
    state = _load_json(state_path, _initial_state())
    if not state.get("active_session_id"):
        return {
            "status": "NO_ACTIVE_SESSION",
            "mode": "stop",
            "session_id": "",
            "session_label": state.get("session_label", ""),
        }
    state = _stop_session(
        project_root=project_root,
        vault_root=vault_root,
        runtime_root=runtime_root,
        state=state,
    )
    _write_json(state_path, state)
    return {
        "status": "STOPPED",
        "mode": "stop",
        "session_id": "",
        "session_label": state.get("session_label", ""),
    }


def _render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# OBSMEM Chronicler",
        "",
        f"- Status: {summary.get('status', 'UNKNOWN')}",
        f"- Mode: {summary.get('mode', 'unknown')}",
        f"- Session label: {summary.get('session_label', '') or '—'}",
        f"- Session id: {summary.get('session_id', '') or '—'}",
    ]
    snapshot = summary.get("snapshot")
    if snapshot:
        lines.extend(
            [
                f"- Branch: {snapshot['repo']['branch']}",
                f"- HEAD: {snapshot['repo']['head_sha'][:12]}",
                f"- Dirty files: {snapshot['repo']['dirty_count']}",
                f"- Focus areas: {', '.join(snapshot['focus_areas'] or ['Maintenance'])}",
            ]
        )
    event = summary.get("event")
    if event:
        lines.append(f"- Event: {event['event_type']} | {event.get('message', '') or '—'}")
    artifacts = summary.get("artifacts", {})
    if artifacts:
        lines.extend(
            [
                "",
                "## Artifacts",
                *(f"- {name}: {value}" for name, value in artifacts.items()),
            ]
        )
    return "\n".join(lines) + "\n"


def _write_summary_files(output_dir: Path, summary: dict[str, Any]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_json = output_dir / "summary.json"
    summary_md = output_dir / "summary.md"
    summary_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary_md.write_text(_render_markdown(summary), encoding="utf-8")
    return summary_json, summary_md


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Maintain OBSMEM Current Work and daily chronicle pages."
    )
    parser.add_argument("--vault", default=str(OBSMEM_ROOT), help="OBSMEM vault root.")
    parser.add_argument(
        "--output-root",
        default=str(OUTPUT_ROOT),
        help="Report root under build/devtools/obsmem_chronicler.",
    )
    parser.add_argument("--watch", action="store_true", help="Run a background watch loop.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single snapshot sync (default mode).",
    )
    parser.add_argument("--interval", type=int, default=90, help="Watch interval in seconds.")
    parser.add_argument(
        "--event-type",
        choices=["win", "issue", "discovery", "decision", "next-step"],
        default="",
        help="Record a manual event.",
    )
    parser.add_argument("--message", default="", help="Manual event message.")
    parser.add_argument("--session-label", default="", help="Human-readable session label.")
    parser.add_argument("--stop", action="store_true", help="Stop an active chronicler session.")
    args = parser.parse_args(argv)

    vault_root = Path(args.vault).resolve()
    output_root = Path(args.output_root).resolve()
    runtime_root = output_root / "runtime"
    state_path = runtime_root / "state.json"
    run_output_dir = output_root / _timestamp()

    if args.stop:
        summary = stop_active_session(
            project_root=PROJECT_ROOT,
            vault_root=vault_root,
            state_path=state_path,
            runtime_root=runtime_root,
        )
    elif args.event_type:
        if not args.message.strip():
            parser.error("--message is required when --event-type is used")
        summary = run_manual_event(
            project_root=PROJECT_ROOT,
            vault_root=vault_root,
            output_root=output_root,
            state_path=state_path,
            runtime_root=runtime_root,
            event_type=args.event_type,
            message=args.message,
            session_label=args.session_label,
        )
    elif args.watch:
        summary = run_watch(
            project_root=PROJECT_ROOT,
            vault_root=vault_root,
            output_root=output_root,
            state_path=state_path,
            runtime_root=runtime_root,
            session_label=args.session_label,
            interval_seconds=args.interval,
        )
    else:
        summary = run_snapshot(
            project_root=PROJECT_ROOT,
            vault_root=vault_root,
            output_root=output_root,
            state_path=state_path,
            runtime_root=runtime_root,
            session_label=args.session_label,
        )

    summary["artifacts"] = {
        **summary.get("artifacts", {}),
        "output_dir": str(run_output_dir),
        "summary_json": str(run_output_dir / "summary.json"),
        "summary_md": str(run_output_dir / "summary.md"),
        "state_json": str(state_path),
        "events_jsonl": str(runtime_root / "events.jsonl"),
    }
    _write_summary_files(run_output_dir, summary)
    _print_console_text(f"OBSMEM chronicler: {summary['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
