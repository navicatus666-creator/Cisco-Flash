from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from typing import Any

ARTIFACT_KEYS: tuple[tuple[str, str], ...] = (
    ("manifest", "manifest_path"),
    ("settings_snapshot", "settings_snapshot_path"),
    ("log", "log_path"),
    ("report", "report_path"),
    ("transcript", "transcript_path"),
    ("bundle", "bundle_path"),
)
ZIP_PATTERNS: dict[str, str] = {
    "manifest": "session_manifest.json",
    "settings_snapshot": "settings_snapshot.json",
    "log": "ciscoautoflash_*.log",
    "report": "install_report_*.txt",
    "transcript": "transcript_*.log",
}
REPORT_FIELDS: tuple[str, ...] = (
    "Run Mode",
    "Workflow Mode",
    "Workflow Note",
    "Session ID",
    "Started At",
    "Session Duration",
    "Current State",
    "Current Stage",
    "Target",
    "Transcript",
)
ERROR_SIGNATURES = (
    "error",
    "ошибка",
    "failed",
    "failure",
    "exception",
    "traceback",
    "timeout",
    "таймаут",
    "rommon",
    "switch:",
    "login",
    "password",
    "%error",
    "not found",
)
WARNING_SIGNATURES = (
    "warning",
    "предупреж",
    "retry",
    "manual",
    "degraded",
    "unsupported",
)
IGNORED_SIGNATURES = (
    "smoke-mode open suppressed",
    "selected target",
    "выбрана цель",
    "открыт журнал",
    "открыт отчёт",
    "открыт транскрипт",
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _safe_json_loads(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _match_zip_member(names: list[str], pattern: str) -> str | None:
    regex = re.compile("^" + pattern.replace(".", r"\.").replace("*", ".*") + "$")
    for name in names:
        if regex.match(Path(name).name):
            return name
    return None


def _artifact_record(
    *,
    name: str,
    path: str,
    present: bool,
    source: str,
    text: str = "",
) -> dict[str, Any]:
    return {
        "name": name,
        "path": path,
        "present": present,
        "source": source,
        "size_bytes": len(text.encode("utf-8")) if text else None,
        "text": text,
    }


def _resolve_dir_artifact(
    session_dir: Path,
    manifest_artifacts: dict[str, Any],
    manifest_key: str,
    fallback_glob: str | None = None,
) -> Path | None:
    raw_path = str(manifest_artifacts.get(manifest_key, "")).strip()
    if raw_path:
        candidate = Path(raw_path)
        if candidate.exists():
            return candidate
        local_candidate = session_dir / candidate.name
        if local_candidate.exists():
            return local_candidate
    if fallback_glob is not None:
        matches = sorted(session_dir.glob(fallback_glob))
        if matches:
            return matches[-1]
    return None


def _load_from_directory(source: Path) -> dict[str, Any]:
    manifest_path = source / "session_manifest.json"
    manifest_text = _read_text(manifest_path) if manifest_path.exists() else ""
    manifest = _safe_json_loads(manifest_text)
    manifest_artifacts = manifest.get("artifacts", {})
    if not isinstance(manifest_artifacts, dict):
        manifest_artifacts = {}

    records: dict[str, dict[str, Any]] = {
        "session_dir": _artifact_record(
            name="session_dir",
            path=str(source),
            present=source.exists(),
            source="directory",
        ),
        "manifest": _artifact_record(
            name="manifest",
            path=str(manifest_path),
            present=manifest_path.exists(),
            source="directory",
            text=manifest_text,
        ),
    }

    for artifact_name, manifest_key in ARTIFACT_KEYS[1:]:
        fallback = None
        if artifact_name == "bundle":
            fallback = "session_bundle_*.zip"
        resolved = _resolve_dir_artifact(source, manifest_artifacts, manifest_key, fallback)
        text = ""
        if resolved and resolved.exists() and resolved.suffix.lower() != ".zip":
            text = _read_text(resolved)
        records[artifact_name] = _artifact_record(
            name=artifact_name,
            path=str(resolved) if resolved else str(manifest_artifacts.get(manifest_key, "")),
            present=bool(resolved and resolved.exists()),
            source="directory",
            text=text,
        )

    inventory = sorted(
        str(path.relative_to(source))
        for path in source.rglob("*")
        if path.is_file()
    )
    return {
        "source_kind": "directory",
        "source_path": str(source),
        "inventory": inventory,
        "manifest": manifest,
        "records": records,
    }


def _load_from_bundle(source: Path) -> dict[str, Any]:
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        manifest_member = _match_zip_member(names, ZIP_PATTERNS["manifest"])
        manifest_text = (
            archive.read(manifest_member).decode("utf-8", errors="replace")
            if manifest_member
            else ""
        )
        manifest = _safe_json_loads(manifest_text)
        records: dict[str, dict[str, Any]] = {
            "session_dir": _artifact_record(
                name="session_dir",
                path=str(source),
                present=True,
                source="bundle-zip",
            ),
            "bundle": _artifact_record(
                name="bundle",
                path=str(source),
                present=source.exists(),
                source="bundle-zip",
            ),
            "manifest": _artifact_record(
                name="manifest",
                path=manifest_member or "session_manifest.json",
                present=manifest_member is not None,
                source="bundle-zip",
                text=manifest_text,
            ),
        }

        for artifact_name, pattern in ZIP_PATTERNS.items():
            if artifact_name == "manifest":
                continue
            member = _match_zip_member(names, pattern)
            text = ""
            if member and not member.endswith(".zip") and not member.endswith(".json"):
                text = archive.read(member).decode("utf-8", errors="replace")
            elif member and member.endswith(".json"):
                text = archive.read(member).decode("utf-8", errors="replace")
            records[artifact_name] = _artifact_record(
                name=artifact_name,
                path=member or pattern,
                present=member is not None,
                source="bundle-zip",
                text=text,
            )

    return {
        "source_kind": "bundle-zip",
        "source_path": str(source),
        "inventory": names,
        "manifest": manifest,
        "records": records,
    }


def load_triage_source(source: Path) -> dict[str, Any]:
    if source.is_dir():
        return _load_from_directory(source)
    if source.is_file() and source.suffix.lower() == ".zip":
        return _load_from_bundle(source)
    raise FileNotFoundError(f"Unsupported triage source: {source}")


def _report_fields(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key in REPORT_FIELDS and key not in result:
            result[key] = value.strip()
    return result


def _tail_lines(text: str, limit: int = 12) -> list[str]:
    return [line for line in text.splitlines() if line.strip()][-limit:]


def _collect_signatures(*texts: str) -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lower = line.lower()
            if any(ignored in lower for ignored in IGNORED_SIGNATURES):
                continue
            if any(token in lower for token in ERROR_SIGNATURES):
                if line not in seen:
                    errors.append(line)
                    seen.add(line)
                continue
            if any(token in lower for token in WARNING_SIGNATURES):
                if line not in seen:
                    warnings.append(line)
                    seen.add(line)
    return {
        "errors": errors[-8:],
        "warnings": warnings[-8:],
    }


def _artifact_integrity(records: dict[str, dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    for name in ("manifest", "log", "report", "transcript"):
        record = records.get(name, {})
        if not record.get("present"):
            issues.append(f"Missing {name} artifact.")
            continue
        if name != "manifest" and record.get("size_bytes", 0) == 0:
            issues.append(f"{name} artifact is empty.")
    return issues


def _artifact_consistency_issues(summary: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    artifacts = summary["artifacts"]
    report_fields = summary["report_fields"]
    session = summary["session"]

    def is_placeholder(value: str) -> bool:
        return value.strip().lower() in {"", "n/a", "—", "-"}

    if artifacts.get("report", {}).get("present"):
        report_transcript = str(report_fields.get("Transcript", "")).strip()
        transcript_path = str(artifacts.get("transcript", {}).get("path", "")).strip()
        if not report_transcript:
            issues.append("Report Transcript field is missing or empty.")
        elif transcript_path and Path(report_transcript).name != Path(transcript_path).name:
            issues.append("Report Transcript field does not match transcript artifact.")

    report_state = str(report_fields.get("Current State", "")).strip()
    if (
        report_state
        and not is_placeholder(report_state)
        and session["final_state"]
        and report_state != session["final_state"]
    ):
        issues.append("Report Current State does not match manifest final_state.")

    report_stage = str(report_fields.get("Current Stage", "")).strip()
    if (
        report_stage
        and not is_placeholder(report_stage)
        and session["current_stage"]
        and report_stage != session["current_stage"]
    ):
        issues.append("Report Current Stage does not match manifest current_stage.")

    report_run_mode = str(report_fields.get("Run Mode", "")).strip()
    if (
        report_run_mode
        and not is_placeholder(report_run_mode)
        and session["run_mode"]
        and report_run_mode != session["run_mode"]
    ):
        issues.append("Report Run Mode does not match manifest run_mode.")

    return issues


def _has_artifact_incomplete_issues(summary: dict[str, Any]) -> bool:
    return any(
        issue.startswith("Missing ")
        or issue.endswith(" artifact is empty.")
        or issue.startswith("Report ")
        for issue in summary["issues"]
    )


def _classify_failure(summary: dict[str, Any]) -> str:
    session = summary["session"]
    if session["final_state"] == "DONE":
        return "artifact_incomplete" if _has_artifact_incomplete_issues(summary) else "success"
    operator_message = session.get("operator_message", {})
    if isinstance(operator_message, dict):
        code = str(operator_message.get("code", "")).strip().lower()
        if code == "demo_stopped":
            return "stopped"
        if code:
            return code
    if _has_artifact_incomplete_issues(summary):
        return "artifact_incomplete"
    parts = [
        str(session.get("operator_text", "")),
        *summary["signatures"]["errors"],
        *summary["signatures"]["warnings"],
    ]
    lowered = " ".join(part.lower() for part in parts if part)
    if "не найден на usb" in lowered or "firmware file not found" in lowered or "no such file" in lowered:
        return "firmware_missing"
    if "timeout" in lowered or "таймаут" in lowered:
        return "timeout"
    if "останов" in lowered or "stopped" in lowered or "abort" in lowered:
        return "stopped"
    return "other"


def _most_likely_cause(summary: dict[str, Any]) -> str:
    failure_class = summary["session"].get("failure_class", "other")
    issues = summary["issues"]
    errors = summary["signatures"]["errors"]
    operator_text = summary["session"].get("operator_text", "")
    if failure_class == "success":
        return "The session completed and the returned diagnostic set looks internally consistent."
    if failure_class == "firmware_missing":
        return "Stage 2 could not find the requested firmware tar on usbflash0:/usbflash1:."
    if failure_class == "timeout":
        return "The workflow likely stalled before the expected reboot or prompt-recovery marker returned."
    if failure_class == "stopped":
        return "The run was stopped before the active stage completed."
    if failure_class == "artifact_incomplete":
        return issues[0] if issues else "The returned diagnostic set is incomplete or internally inconsistent."
    if operator_text:
        return operator_text
    if errors:
        return errors[0]
    return "The returned artifacts show a failure, but no stronger classification matched."


def _recommended_next_capture(summary: dict[str, Any]) -> str:
    failure_class = summary["session"].get("failure_class", "other")
    if failure_class == "success":
        return "Bring back session_bundle_*.zip only; no extra capture is required unless the operator noticed something unusual."
    if failure_class == "firmware_missing":
        return "Capture `dir usbflash0:` and `dir usbflash1:` plus the exact firmware filename visible on the USB media, then bring back the session bundle."
    if failure_class == "timeout":
        return "Capture a final dashboard screenshot, the last visible console prompt after waiting, and whether the switch actually rebooted after `archive download-sw`."
    if failure_class == "stopped":
        return "Capture why the run was stopped, the final dashboard screenshot, and the stopped session bundle for comparison."
    if failure_class == "artifact_incomplete":
        return "Bring back the whole session folder plus any matching log/report/transcript files and a screenshot of the final dashboard state."
    return "Capture the final dashboard screenshot, the exact final prompt, and the full session folder in addition to the session bundle."


def _inspect_next(summary: dict[str, Any]) -> list[str]:
    failure_class = summary["session"].get("failure_class", "other")
    if failure_class == "success":
        return [
            "report: confirm final operator-facing conclusions and reported workflow mode.",
            "transcript: spot-check the final verification commands and prompt tail.",
            "manifest: confirm final_state/current_stage and session paths.",
        ]
    if failure_class == "firmware_missing":
        return [
            "transcript: inspect `dir usbflash0:` / `dir usbflash1:` output and the first `No such file` line.",
            "log: confirm when Stage 2 decided the image was missing.",
            "manifest: check final_state/current_stage and operator_message.code.",
            "report: confirm the operator-facing next step mentions the missing image.",
        ]
    if failure_class == "timeout":
        return [
            "transcript: inspect the tail around `archive download-sw` and prompt recovery.",
            "log: confirm the last progress marker before timeout.",
            "manifest: check final_state/current_stage and stage duration fields.",
            "report: confirm the operator-facing timeout message and next step.",
        ]
    if failure_class == "stopped":
        return [
            "manifest: confirm the final state and stop-related operator message.",
            "log: find the exact stop marker and what was running immediately before it.",
            "transcript: inspect the last command/prompt pair before the stop.",
            "report: confirm the stop reason presented to the operator.",
        ]
    if failure_class == "artifact_incomplete":
        return [
            "manifest: confirm which artifacts were expected and what final state was recorded.",
            "report: check for missing fields or values that do not match the manifest.",
            "transcript: verify the file is present and non-empty before trusting the run outcome.",
            "log: confirm whether the missing/inconsistent artifact happened before or after the main failure.",
        ]
    return [
        "manifest: confirm final_state/current_stage and operator_message first.",
        "transcript: inspect the command/prompt tail around the failure.",
        "log: inspect the last error/warning signatures.",
        "report: compare the operator-facing summary against the manifest and transcript.",
    ]


def _build_next_steps(summary: dict[str, Any]) -> list[str]:
    session = summary["session"]
    artifacts = summary["artifacts"]
    signatures = summary["signatures"]
    failure_class = session.get("failure_class", "")
    next_steps: list[str] = []
    if not all(artifacts[name]["present"] for name in ("log", "report", "transcript")):
        next_steps.append(
            "Bring back session_bundle.zip when possible; a bare session folder may "
            "omit log/report/transcript."
        )
    if failure_class == "firmware_missing":
        next_steps.append(
            "Verify the exact firmware filename and capture `dir usbflash0:` / "
            "`dir usbflash1:` output before retrying."
        )
    elif failure_class == "timeout":
        next_steps.append(
            "Check whether `archive download-sw` started and whether the switch "
            "already rebooted before retrying Stage 2."
        )
    elif failure_class == "stopped":
        next_steps.append(
            "Re-scan the device and restart from the intended stage; keep the stopped "
            "session bundle for comparison."
        )
    if session["final_state"] != "DONE":
        next_steps.append(
            "Compare the failure against docs/pre_hardware/expected_outcomes.md and "
            "file it with bug_capture_template.md."
        )
    if signatures["errors"]:
        next_steps.append(
            "Inspect the error signatures and transcript tail first; they usually "
            "narrow the failing stage fastest."
        )
    if not next_steps:
        next_steps.append(
            "Use the summary as the first triage snapshot, then open the report and "
            "transcript only if you need more detail."
        )
    return next_steps


def build_triage_summary(source: Path) -> dict[str, Any]:
    loaded = load_triage_source(source)
    manifest = loaded["manifest"]
    records = loaded["records"]
    report_text = str(records.get("report", {}).get("text", ""))
    log_text = str(records.get("log", {}).get("text", ""))
    transcript_text = str(records.get("transcript", {}).get("text", ""))
    operator_message = manifest.get("operator_message", {})
    if not isinstance(operator_message, dict):
        operator_message = {}

    summary = {
        "source": {
            "path": loaded["source_path"],
            "kind": loaded["source_kind"],
            "inventory": loaded["inventory"],
        },
        "session": {
            "session_id": str(manifest.get("session_id", "")),
            "profile_name": str(manifest.get("profile_name", "")),
            "run_mode": str(manifest.get("run_mode", "")),
            "started_at": str(manifest.get("started_at", "")),
            "last_updated_at": str(manifest.get("last_updated_at", "")),
            "final_state": str(manifest.get("final_state", "")),
            "current_stage": str(manifest.get("current_stage", "")),
            "selected_target_id": str(manifest.get("selected_target_id", "")),
            "operator_severity": str(manifest.get("operator_severity", "")),
            "operator_text": str(manifest.get("operator_text", "")),
            "operator_message": operator_message,
            "stage_durations": manifest.get("stage_durations", {}),
            "stage_durations_seconds": manifest.get("stage_durations_seconds", {}),
        },
        "artifacts": {
            name: {
                "path": record["path"],
                "present": bool(record["present"]),
                "source": record["source"],
                "size_bytes": record["size_bytes"],
            }
            for name, record in records.items()
        },
        "report_fields": _report_fields(report_text),
        "signatures": _collect_signatures(log_text, transcript_text),
        "tails": {
            "log": _tail_lines(log_text),
            "transcript": _tail_lines(transcript_text),
            "report": _tail_lines(report_text),
        },
        "issues": _artifact_integrity(records),
    }
    summary["issues"].extend(_artifact_consistency_issues(summary))
    summary["session"]["failure_class"] = _classify_failure(summary)
    summary["diagnosis"] = {
        "most_likely_cause": _most_likely_cause(summary),
        "recommended_next_capture": _recommended_next_capture(summary),
        "inspect_next": _inspect_next(summary),
    }
    summary["next_steps"] = _build_next_steps(summary)
    return summary


def render_markdown_summary(summary: dict[str, Any]) -> str:
    session = summary["session"]
    artifacts = summary["artifacts"]
    signatures = summary["signatures"]
    report_fields = summary["report_fields"]
    stage_seconds = session.get("stage_durations_seconds", {})
    stage_rows = []
    if isinstance(stage_seconds, dict):
        for key, seconds in stage_seconds.items():
            stage_rows.append(f"| {key} | {seconds if seconds is not None else '—'} |")

    artifact_rows = [
        f"| {name} | {'yes' if data['present'] else 'no'} | {data['path'] or '—'} |"
        for name, data in artifacts.items()
    ]
    report_rows = [
        f"- {key}: {value}"
        for key, value in report_fields.items()
    ] or ["- No key report fields parsed."]
    error_rows = [f"- {line}" for line in signatures["errors"]] or ["- None"]
    warning_rows = [f"- {line}" for line in signatures["warnings"]] or ["- None"]
    issue_rows = [f"- {line}" for line in summary["issues"]] or ["- None"]
    inspect_rows = [f"- {line}" for line in summary["diagnosis"]["inspect_next"]]
    next_rows = [f"- {line}" for line in summary["next_steps"]]
    log_tail = "\n".join(summary["tails"]["log"]) or "(empty)"
    transcript_tail = "\n".join(summary["tails"]["transcript"]) or "(empty)"

    return "\n".join(
        [
            "# CiscoAutoFlash Session Triage",
            "",
            "## Summary",
            f"- Source: {summary['source']['kind']} -> {summary['source']['path']}",
            f"- Session ID: {session['session_id'] or 'unknown'}",
            f"- Final state: {session['final_state'] or 'unknown'}",
            f"- Failure class: {session.get('failure_class', 'unknown')}",
            f"- Most likely cause: {summary['diagnosis']['most_likely_cause']}",
            f"- Recommended next capture: {summary['diagnosis']['recommended_next_capture']}",
            f"- Current stage: {session['current_stage'] or 'unknown'}",
            f"- Selected target: {session['selected_target_id'] or 'unknown'}",
            f"- Run mode: {session['run_mode'] or 'unknown'}",
            f"- Operator severity: {session['operator_severity'] or 'unknown'}",
            f"- Operator text: {session['operator_text'] or '—'}",
            "",
            "## Artifacts",
            "| Artifact | Present | Path |",
            "| --- | --- | --- |",
            *artifact_rows,
            "",
            "## Stage Durations (seconds)",
            "| Stage | Seconds |",
            "| --- | --- |",
            *(stage_rows or ["| none | — |"]),
            "",
            "## Report Fields",
            *report_rows,
            "",
            "## Issues",
            *issue_rows,
            "",
            "## Error Signatures",
            *error_rows,
            "",
            "## Warning Signatures",
            *warning_rows,
            "",
            "## Inspect Next",
            *inspect_rows,
            "",
            "## Next Steps",
            *next_rows,
            "",
            "## Log Tail",
            "```text",
            log_tail,
            "```",
            "",
            "## Transcript Tail",
            "```text",
            transcript_tail,
            "```",
        ]
    )


def _default_output_name(summary: dict[str, Any]) -> str:
    session_id = summary["session"].get("session_id") or Path(summary["source"]["path"]).stem
    return f"{session_id}_triage"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize a CiscoAutoFlash session folder or session_bundle.zip."
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Path to a session folder or session_bundle.zip.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Write markdown and JSON outputs here.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write the JSON summary to this file.",
    )
    parser.add_argument(
        "--md-out",
        type=Path,
        default=None,
        help="Write the Markdown summary to this file.",
    )
    args = parser.parse_args(argv)

    summary = build_triage_summary(args.source.resolve())
    markdown = render_markdown_summary(summary)

    json_out = args.json_out
    md_out = args.md_out
    if args.output_dir is not None:
        base_name = _default_output_name(summary)
        json_out = json_out or args.output_dir / f"{base_name}.json"
        md_out = md_out or args.output_dir / f"{base_name}.md"

    if json_out is not None:
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if md_out is not None:
        md_out.parent.mkdir(parents=True, exist_ok=True)
        md_out.write_text(markdown, encoding="utf-8")

    print(markdown)
    if json_out is not None:
        print(f"\nJSON: {json_out}")
    if md_out is not None:
        print(f"Markdown: {md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
