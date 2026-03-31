from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from ciscoautoflash.config import AppConfig, SessionPaths, WorkflowTiming
from ciscoautoflash.core.events import AppEvent
from ciscoautoflash.core.models import ConnectionTarget, ScanResult
from scripts.run_hidden_ssh_check import (
    EventTimelineRecorder,
    HiddenSshArtifacts,
    run_hidden_ssh_check,
)


def make_session(root: Path) -> SessionPaths:
    return SessionPaths(
        base_dir=root,
        logs_dir=root / "logs",
        reports_dir=root / "reports",
        transcripts_dir=root / "transcripts",
        sessions_dir=root / "sessions",
        session_dir=root / "sessions" / "20260401_010101",
        session_id="20260401_010101",
        started_at=datetime.now(),
        log_path=root / "logs" / "ciscoautoflash_20260401_010101.log",
        report_path=root / "reports" / "install_report_20260401_010101.txt",
        transcript_path=root / "transcripts" / "transcript_20260401_010101.log",
        settings_path=root / "settings" / "settings.json",
        settings_snapshot_path=(
            root / "sessions" / "20260401_010101" / "settings_snapshot.json"
        ),
        manifest_path=(
            root
            / "sessions"
            / "20260401_010101"
            / "session_manifest_20260401_010101.json"
        ),
        bundle_path=(
            root
            / "sessions"
            / "20260401_010101"
            / "session_bundle_20260401_010101.zip"
        ),
        event_timeline_path=(
            root / "sessions" / "20260401_010101" / "event_timeline.json"
        ),
        dashboard_snapshot_path=None,
    )


class EventTimelineRecorderTests(unittest.TestCase):
    def test_recorder_tracks_state_stage_and_operator_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = make_session(root)
            session.event_timeline_path.parent.mkdir(parents=True, exist_ok=True)
            recorder = EventTimelineRecorder(
                "ssh:10.0.0.1",
                HiddenSshArtifacts(
                    session_dir=session.session_dir,
                    log_path=session.log_path,
                    transcript_path=session.transcript_path,
                    report_path=session.report_path,
                    manifest_path=session.manifest_path,
                    bundle_path=session.bundle_path,
                    timeline_path=session.event_timeline_path,
                    summary_json_path=session.session_dir / "ssh_check_summary.json",
                    summary_md_path=session.session_dir / "ssh_check_summary.md",
                    dashboard_snapshot_path=None,
                ),
            )
            message = type("Msg", (), {"code": "timeout"})()
            recorder.handle(
                AppEvent(
                    "session_paths",
                    {
                        "session_dir": str(session.session_dir),
                        "event_timeline_path": str(session.event_timeline_path),
                    },
                )
            )
            recorder.handle(AppEvent("progress", {"percent": 40, "stage_name": "Этап 3: Проверка"}))
            recorder.handle(AppEvent("operator_message", {"message": message}))
            recorder.handle(AppEvent("state_changed", {"state": "FAILED"}))

            payload = json.loads(session.event_timeline_path.read_text(encoding="utf-8"))
            self.assertEqual(payload[-1]["state"], "FAILED")
            self.assertEqual(payload[-1]["current_stage"], "Этап 3: Проверка")
            self.assertEqual(payload[-1]["operator_message_code"], "timeout")
            self.assertEqual(payload[-1]["progress_percent"], 40)


class RunHiddenSshCheckTests(unittest.TestCase):
    def test_run_hidden_ssh_check_probe_only_writes_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = make_session(root)
            for path in (
                session.base_dir,
                session.logs_dir,
                session.reports_dir,
                session.transcripts_dir,
                session.sessions_dir,
                session.session_dir,
                session.settings_path.parent,
            ):
                path.mkdir(parents=True, exist_ok=True)
            config = AppConfig(project_root=root, runtime_root=root, timing=WorkflowTiming())
            probe = ScanResult(
                target=ConnectionTarget(
                    id="ssh:10.0.0.1",
                    label="SSH 10.0.0.1",
                    metadata={"host": "10.0.0.1", "username": "admin", "password": "pw"},
                ),
                available=True,
                status_message="ok",
                prompt_type="priv",
                connection_state="ready",
                recommended_next_action="",
                error_code="",
                score=10,
                raw_preview="",
            )
            controller = Mock()
            controller.initialize = Mock()
            controller.selected_target = None
            controller.state.value = "IDLE"
            controller.run_stage3 = Mock()
            factory = Mock()
            factory.probe.return_value = probe
            with (
                patch("scripts.run_hidden_ssh_check.AppConfig", return_value=config),
                patch.object(AppConfig, "create_session_paths", return_value=session),
                patch(
                    "scripts.run_hidden_ssh_check.SshTransportFactory",
                    return_value=factory,
                ),
                patch(
                    "scripts.run_hidden_ssh_check.WorkflowController",
                    return_value=controller,
                ),
                patch(
                    "scripts.run_hidden_ssh_check._ping_host",
                    return_value={
                        "ok": True,
                        "returncode": 0,
                        "summary": "ok",
                    },
                ),
                patch(
                    "scripts.run_hidden_ssh_check.export_session_bundle",
                    return_value=session.bundle_path,
                ),
                patch("scripts.run_hidden_ssh_check.update_manifest_artifacts"),
            ):
                summary = run_hidden_ssh_check(
                    Namespace(
                        host="10.0.0.1",
                        username="admin",
                        password="pw",
                        secret="",
                        port=22,
                        device_type="cisco_ios",
                        timeout=None,
                        banner_timeout=None,
                        auth_timeout=None,
                        session_timeout=None,
                        file_system="flash:",
                        probe_only=True,
                        skip_ping=False,
                        scp_file=None,
                        dest_file=None,
                    )
                )

            self.assertEqual(summary["overall_status"], "OK")
            self.assertTrue(
                Path(
                    summary["artifacts"]["session_dir"],
                    "ssh_check_summary.json",
                ).exists()
            )
            controller.run_stage3.assert_not_called()
