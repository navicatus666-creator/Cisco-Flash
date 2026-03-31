from __future__ import annotations

import json
import shutil
import zipfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import SessionPaths

STAGE_DURATION_LABELS: tuple[tuple[str, str], ...] = (
    ("scan", "Scan Duration"),
    ("stage1", "Stage 1 Duration"),
    ("stage2", "Stage 2 Duration"),
    ("stage3", "Stage 3 Duration"),
)


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def build_stage_duration_map(
    stage_durations: Mapping[str, float | None],
) -> dict[str, dict[str, float | str | None]]:
    result: dict[str, dict[str, float | str | None]] = {}
    for key, label in STAGE_DURATION_LABELS:
        seconds = stage_durations.get(key)
        result[key] = {
            "label": label,
            "seconds": round(seconds, 3) if seconds is not None else None,
            "display": format_duration(seconds),
        }
    return result


def build_stage_duration_rows(
    stage_durations: Mapping[str, float | None],
) -> list[tuple[str, str]]:
    return [
        (label, format_duration(stage_durations.get(key)))
        for key, label in STAGE_DURATION_LABELS
    ]


def build_session_manifest(
    *,
    session: SessionPaths,
    profile_name: str,
    run_mode: str,
    started_at: str,
    last_updated_at: str,
    session_elapsed_seconds: float,
    active_stage_elapsed_seconds: float | None,
    current_state: str,
    current_stage: str,
    selected_target_id: str,
    requested_firmware_name: str,
    observed_firmware_version: str,
    last_scan_completed_at: str,
    operator_message: Mapping[str, str],
    stage_durations: Mapping[str, float | None],
) -> dict[str, Any]:
    operator_text = " | ".join(
        value.strip()
        for value in (
            operator_message.get("title", ""),
            operator_message.get("detail", ""),
            operator_message.get("next_step", ""),
        )
        if value.strip()
    )
    duration_map = build_stage_duration_map(stage_durations)
    return {
        "session_id": session.session_id,
        "profile_name": profile_name,
        "run_mode": run_mode,
        "started_at": started_at,
        "last_updated_at": last_updated_at,
        "session_duration": format_duration(session_elapsed_seconds),
        "session_elapsed_seconds": round(session_elapsed_seconds, 3),
        "active_stage_duration": format_duration(active_stage_elapsed_seconds),
        "active_stage_elapsed_seconds": (
            round(active_stage_elapsed_seconds, 3)
            if active_stage_elapsed_seconds is not None
            else None
        ),
        "final_state": current_state,
        "current_state": current_state,
        "current_stage": current_stage,
        "selected_target_id": selected_target_id or "",
        "requested_firmware_name": requested_firmware_name or "",
        "observed_firmware_version": observed_firmware_version or "",
        "last_scan_at": last_scan_completed_at or "",
        "operator_severity": operator_message.get("severity", ""),
        "operator_message": dict(operator_message),
        "operator_text": operator_text,
        "artifacts": {
            "session_dir": str(session.session_dir),
            "log_path": str(session.log_path),
            "report_path": str(session.report_path),
            "transcript_path": str(session.transcript_path),
            "settings_path": str(session.settings_path),
            "settings_snapshot_path": str(session.settings_snapshot_path),
            "manifest_path": str(session.manifest_path),
            "bundle_path": str(session.bundle_path),
            "event_timeline_path": str(session.event_timeline_path),
            "dashboard_snapshot_path": (
                str(session.dashboard_snapshot_path)
                if session.dashboard_snapshot_path is not None
                else ""
            ),
        },
        "stage_durations": {
            entry["label"]: str(entry["display"]) for entry in duration_map.values()
        },
        "stage_durations_seconds": {
            key: entry["seconds"] for key, entry in duration_map.items()
        },
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def write_session_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def update_manifest_artifacts(
    path: Path,
    **artifact_paths: Path | str | None,
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(manifest, dict):
        return None
    artifacts = manifest.get("artifacts", {})
    if not isinstance(artifacts, dict):
        artifacts = {}
    for key, value in artifact_paths.items():
        artifacts[key] = str(value) if value else ""
    manifest["artifacts"] = artifacts
    write_session_manifest(path, manifest)
    return manifest


def snapshot_settings(source_path: Path, snapshot_path: Path) -> Path | None:
    if not source_path.exists():
        return None
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, snapshot_path)
    return snapshot_path


def export_session_bundle(session: SessionPaths) -> Path:
    snapshot_settings(session.settings_path, session.settings_snapshot_path)
    files = [
        ("session_manifest.json", session.manifest_path),
        ("settings_snapshot.json", session.settings_snapshot_path),
        (session.log_path.name, session.log_path),
        (session.report_path.name, session.report_path),
        (session.transcript_path.name, session.transcript_path),
        (session.event_timeline_path.name, session.event_timeline_path),
    ]
    if session.dashboard_snapshot_path is not None:
        snapshot_path = Path(session.dashboard_snapshot_path)
        files.append((snapshot_path.name, snapshot_path))
    session.bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        session.bundle_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for archive_name, source_path in files:
            if source_path.exists():
                archive.write(source_path, arcname=archive_name)
    return session.bundle_path
