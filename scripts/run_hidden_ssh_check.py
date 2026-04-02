#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _ensure_project_root_on_path() -> None:
    project_root = str(PROJECT_ROOT)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


def _timestamp() -> str:
    _ensure_project_root_on_path()
    from ciscoautoflash.core.logging_utils import timestamp

    return timestamp()

try:
    from PIL import Image as _Image
    from PIL import ImageDraw as _ImageDraw
    from PIL import ImageGrab as _ImageGrab
except ImportError:  # pragma: no cover - environment dependent
    Image: Any | None = None
    ImageDraw: Any | None = None
    ImageGrab: Any | None = None
else:
    Image: Any | None = _Image
    ImageDraw: Any | None = _ImageDraw
    ImageGrab: Any | None = _ImageGrab

if TYPE_CHECKING:
    from ciscoautoflash.core.events import AppEvent
    from ciscoautoflash.core.models import ConnectionTarget

AppConfig: Any = None
append_session_log: Any = None
timestamp: Any = None
export_session_bundle: Any = None
update_manifest_artifacts: Any = None
SshTransportFactory: Any = None
WorkflowController: Any = None
build_c2960x_profile: Any = None


def _load_project_runtime() -> None:
    global AppConfig
    global append_session_log
    global timestamp
    global export_session_bundle
    global update_manifest_artifacts
    global SshTransportFactory
    global WorkflowController
    global build_c2960x_profile

    _ensure_project_root_on_path()

    if AppConfig is None:
        from ciscoautoflash.config import AppConfig as _AppConfig

        AppConfig = _AppConfig
    if append_session_log is None or timestamp is None:
        from ciscoautoflash.core.logging_utils import (
            append_session_log as _append_session_log,
        )
        from ciscoautoflash.core.logging_utils import timestamp as _timestamp_fn

        append_session_log = _append_session_log
        timestamp = _timestamp_fn
    if export_session_bundle is None or update_manifest_artifacts is None:
        from ciscoautoflash.core.session_artifacts import (
            export_session_bundle as _export_session_bundle,
        )
        from ciscoautoflash.core.session_artifacts import (
            update_manifest_artifacts as _update_manifest_artifacts,
        )

        export_session_bundle = _export_session_bundle
        update_manifest_artifacts = _update_manifest_artifacts
    if SshTransportFactory is None:
        from ciscoautoflash.core.ssh_transport import (
            SshTransportFactory as _SshTransportFactory,
        )

        SshTransportFactory = _SshTransportFactory
    if WorkflowController is None:
        from ciscoautoflash.core.workflow import (
            WorkflowController as _WorkflowController,
        )

        WorkflowController = _WorkflowController
    if build_c2960x_profile is None:
        from ciscoautoflash.profiles import (
            build_c2960x_profile as _build_c2960x_profile,
        )

        build_c2960x_profile = _build_c2960x_profile


@dataclass(slots=True)
class HiddenSshArtifacts:
    session_dir: Path
    log_path: Path
    transcript_path: Path
    report_path: Path
    manifest_path: Path
    bundle_path: Path
    timeline_path: Path
    summary_json_path: Path
    summary_md_path: Path
    dashboard_snapshot_path: Path | None


class EventTimelineRecorder:
    def __init__(self, target_id: str, artifacts: HiddenSshArtifacts) -> None:
        self.target_id = target_id
        self.artifacts = artifacts
        self.current_state = "IDLE"
        self.current_stage = ""
        self.operator_message_code = ""
        self.progress_percent = 0
        self.entries: list[dict[str, Any]] = []

    def handle(self, event: AppEvent) -> None:
        if event.kind == "state_changed":
            self.current_state = str(event.payload.get("state", self.current_state))
            stage = str(event.payload.get("current_stage", "")).strip()
            if stage:
                self.current_stage = stage
        elif event.kind == "progress":
            self.progress_percent = int(event.payload.get("percent", self.progress_percent) or 0)
            stage = str(event.payload.get("stage_name", "")).strip()
            if stage:
                self.current_stage = stage
        elif event.kind == "operator_message":
            message = event.payload.get("message")
            self.operator_message_code = str(getattr(message, "code", "") or "")
        elif event.kind == "selected_target_changed":
            target_id = str(event.payload.get("target_id", "")).strip()
            if target_id:
                self.target_id = target_id
        self.entries.append(
            {
                "timestamp": _timestamp(),
                "kind": event.kind,
                "state": self.current_state,
                "current_stage": self.current_stage,
                "selected_target_id": self.target_id,
                "operator_message_code": self.operator_message_code,
                "progress_percent": self.progress_percent,
                "paths": self._event_paths(event),
            }
        )
        self.write()

    def _event_paths(self, event: AppEvent) -> dict[str, str]:
        path_keys = (
            "session_dir",
            "log_path",
            "report_path",
            "transcript_path",
            "settings_path",
            "settings_snapshot_path",
            "manifest_path",
            "bundle_path",
            "event_timeline_path",
            "dashboard_snapshot_path",
        )
        if event.kind == "session_paths":
            return {
                key: str(event.payload.get(key, ""))
                for key in path_keys
                if str(event.payload.get(key, "")).strip()
            }
        if event.kind == "report_ready":
            return {"report_path": str(self.artifacts.report_path)}
        return {}

    def write(self) -> None:
        self.artifacts.timeline_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifacts.timeline_path.write_text(
            json.dumps(self.entries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Hidden engineering helper for SSH probe, optional Stage 3 verify, "
            "and optional SCP upload."
        )
    )
    parser.add_argument("--host", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--secret", default="")
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--device-type", default="cisco_ios")
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--banner-timeout", type=float)
    parser.add_argument("--auth-timeout", type=float)
    parser.add_argument("--session-timeout", type=float)
    parser.add_argument("--file-system", default="flash:")
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--skip-ping", action="store_true")
    parser.add_argument("--scp-file")
    parser.add_argument("--dest-file")
    return parser.parse_args()


def _build_target(args: argparse.Namespace) -> ConnectionTarget:
    _ensure_project_root_on_path()
    from ciscoautoflash.core.models import ConnectionTarget

    metadata: dict[str, Any] = {
        "host": args.host,
        "username": args.username,
        "password": args.password,
        "device_type": args.device_type,
        "port": args.port,
        "file_system": args.file_system,
    }
    optional = {
        "secret": args.secret,
        "timeout": args.timeout,
        "banner_timeout": args.banner_timeout,
        "auth_timeout": args.auth_timeout,
        "session_timeout": args.session_timeout,
    }
    for key, value in optional.items():
        if value not in {None, ""}:
            metadata[key] = value
    return ConnectionTarget(
        id=f"ssh:{args.host}",
        label=f"SSH {args.host}",
        metadata=metadata,
    )


def _ping_host(host: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["ping", "-n", "1", host],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    lines = [
        line.strip()
        for line in (completed.stdout or "").splitlines()
        if line.strip()
    ]
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "summary": lines[-1] if lines else "",
    }


def _capture_snapshot(artifacts: HiddenSshArtifacts, state: str) -> Path | None:
    path = artifacts.session_dir / f"dashboard_snapshot_{state.lower()}.png"
    if ImageGrab is not None:
        try:
            ImageGrab.grab().save(path)
            artifacts.dashboard_snapshot_path = path
            return path
        except Exception:
            pass
    if Image is None or ImageDraw is None:
        return None
    image = Image.new("RGB", (960, 540), color=(250, 250, 250))
    drawer = ImageDraw.Draw(image)
    drawer.text(
        (24, 24),
        (
            "CiscoAutoFlash hidden SSH check\n"
            f"Terminal state: {state}\n"
            f"Captured: {_timestamp()}"
        ),
        fill=(20, 20, 20),
    )
    image.save(path)
    artifacts.dashboard_snapshot_path = path
    return path


def _render_markdown(summary: dict[str, Any]) -> str:
    probe = summary["probe"]
    stage3 = summary["stage3"]
    scp = summary["scp"]
    artifacts = summary["artifacts"]
    lines = [
        "# CiscoAutoFlash Hidden SSH Check",
        "",
        f"- Overall status: {summary['overall_status']}",
        f"- Host: {summary['host']}",
        f"- Ping ok: {'yes' if summary['ping']['ok'] else 'no'}",
        f"- Probe available: {'yes' if probe['available'] else 'no'}",
        f"- Probe state: {probe['connection_state'] or 'unknown'}",
        f"- Probe prompt: {probe['prompt_type'] or 'unknown'}",
        f"- Stage 3 attempted: {'yes' if stage3['attempted'] else 'no'}",
        f"- Stage 3 final state: {stage3['final_state'] or 'not run'}",
        f"- SCP attempted: {'yes' if scp['attempted'] else 'no'}",
        f"- SCP ok: {'yes' if scp['ok'] else 'no'}",
        "",
        "## Artifacts",
        "",
        f"- Session dir: {artifacts['session_dir']}",
        f"- Transcript: {artifacts['transcript_path']}",
        f"- Report: {artifacts['report_path']}",
        f"- Manifest: {artifacts['manifest_path']}",
        f"- Event timeline: {artifacts['event_timeline_path']}",
        f"- Bundle: {artifacts['bundle_path'] or 'not created'}",
    ]
    if artifacts["dashboard_snapshot_path"]:
        lines.append(f"- Dashboard snapshot: {artifacts['dashboard_snapshot_path']}")
    if probe["recommended_next_action"]:
        lines.extend(
            ["", "## Next Step", "", f"- {probe['recommended_next_action']}"]
        )
    return "\n".join(lines) + "\n"


def run_hidden_ssh_check(args: argparse.Namespace) -> dict[str, Any]:
    _load_project_runtime()

    config = AppConfig()
    session = config.create_session_paths()
    artifacts = HiddenSshArtifacts(
        session_dir=session.session_dir,
        log_path=session.log_path,
        transcript_path=session.transcript_path,
        report_path=session.report_path,
        manifest_path=session.manifest_path,
        bundle_path=session.bundle_path,
        timeline_path=session.event_timeline_path,
        summary_json_path=session.session_dir / "ssh_check_summary.json",
        summary_md_path=session.session_dir / "ssh_check_summary.md",
        dashboard_snapshot_path=session.dashboard_snapshot_path,
    )
    profile = build_c2960x_profile()
    target = _build_target(args)
    recorder = EventTimelineRecorder(target.id, artifacts)

    def handle_event(event: AppEvent) -> None:
        recorder.handle(event)

    append_session_log(
        session.log_path,
        f"[{_timestamp()}] Hidden SSH check started for {args.host}",
    )
    ping = {"ok": None, "returncode": None, "summary": ""}
    if not args.skip_ping:
        ping = _ping_host(args.host)
        append_session_log(
            session.log_path,
            (
                f"[{timestamp()}] Ping "
                f"{'ok' if ping['ok'] else 'failed'} for "
                f"{args.host}: {ping['summary']}"
            ),
        )

    factory = SshTransportFactory(
        config.timing,
        [target],
        transcript_path=session.transcript_path,
    )
    controller = WorkflowController(
        profile=profile,
        transport_factory=factory,
        session=session,
        event_handler=handle_event,
        timing=config.timing,
    )
    controller.initialize()
    controller.selected_target = target

    probe = factory.probe(
        target,
        profile.prompts,
        timeout=config.timing.scan_probe_timeout,
    )
    append_session_log(
        session.log_path,
        (
            f"[{timestamp()}] SSH probe state={probe.connection_state} "
            f"prompt={probe.prompt_type or 'unknown'}"
        ),
    )

    stage3_summary: dict[str, Any] = {
        "attempted": False,
        "final_state": "",
        "report_ready": False,
    }
    scp_summary: dict[str, Any] = {
        "attempted": bool(args.scp_file),
        "ok": False,
        "result": {},
        "error": "",
    }
    overall_status = "OK" if probe.available else "FAILED"

    if probe.available and not args.probe_only:
        stage3_summary["attempted"] = True
        try:
            controller.run_stage3(background=False)
        except Exception as exc:  # pragma: no cover - defensive
            append_session_log(
                session.log_path,
                f"[{_timestamp()}] Hidden SSH Stage 3 crashed: {exc}",
            )
        stage3_summary["final_state"] = controller.state.value
        stage3_summary["report_ready"] = session.report_path.exists()
        if controller.state.value not in {"DONE", "IDLE"}:
            overall_status = "FAILED"
        if controller.state.value in {"FAILED", "STOPPED"}:
            snapshot_path = _capture_snapshot(artifacts, controller.state.value)
            if snapshot_path is not None:
                session.dashboard_snapshot_path = snapshot_path

    if probe.available and args.scp_file:
        transport = factory.create(target)
        try:
            transport.connect()
            transport.ensure_privileged_prompt()
            scp_summary["result"] = transport.upload_file(
                args.scp_file,
                dest_file=args.dest_file,
                file_system=args.file_system,
            )
            scp_summary["ok"] = True
        except Exception as exc:
            scp_summary["error"] = str(exc)
            overall_status = "FAILED"
            append_session_log(
                session.log_path,
                f"[{timestamp()}] Hidden SCP check failed: {exc}",
            )
        finally:
            try:
                transport.disconnect()
            except Exception:
                pass

    bundle_path = None
    if session.manifest_path.exists():
        update_manifest_artifacts(
            session.manifest_path,
            event_timeline_path=str(session.event_timeline_path),
            dashboard_snapshot_path=str(
                session.dashboard_snapshot_path or ""
            ),
        )
        bundle_path = export_session_bundle(session)

    summary = {
        "overall_status": overall_status,
        "host": args.host,
        "ping": ping,
        "probe": {
            "available": probe.available,
            "prompt_type": probe.prompt_type,
            "connection_state": probe.connection_state,
            "status_message": probe.status_message,
            "recommended_next_action": probe.recommended_next_action,
            "error_code": probe.error_code,
        },
        "stage3": stage3_summary,
        "scp": scp_summary,
        "artifacts": {
            "session_dir": str(artifacts.session_dir),
            "log_path": str(artifacts.log_path),
            "transcript_path": str(artifacts.transcript_path),
            "report_path": str(artifacts.report_path),
            "manifest_path": str(artifacts.manifest_path),
            "bundle_path": str(bundle_path or ""),
            "event_timeline_path": str(artifacts.timeline_path),
            "dashboard_snapshot_path": str(artifacts.dashboard_snapshot_path or ""),
        },
    }
    artifacts.summary_json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    artifacts.summary_md_path.write_text(
        _render_markdown(summary),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    summary = run_hidden_ssh_check(_parse_args())
    print(f"Status: {summary['overall_status']}")
    print(f"Summary JSON: {summary['artifacts']['session_dir']}\\ssh_check_summary.json")
    print(f"Summary MD: {summary['artifacts']['session_dir']}\\ssh_check_summary.md")
    if summary["artifacts"]["bundle_path"]:
        print(f"Bundle: {summary['artifacts']['bundle_path']}")
    return 0 if summary["overall_status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
