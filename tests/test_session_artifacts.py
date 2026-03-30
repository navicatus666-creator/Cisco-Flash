from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

from ciscoautoflash.config import SessionPaths
from ciscoautoflash.core.session_artifacts import (
    build_session_manifest,
    export_session_bundle,
    format_duration,
    write_session_manifest,
)


class SessionArtifactsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        logs_dir = root / "logs"
        reports_dir = root / "reports"
        transcripts_dir = root / "transcripts"
        sessions_dir = root / "sessions"
        session_dir = sessions_dir / "artifact"
        for directory in (logs_dir, reports_dir, transcripts_dir, sessions_dir, session_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.session = SessionPaths(
            base_dir=root,
            session_dir=session_dir,
            sessions_dir=sessions_dir,
            logs_dir=logs_dir,
            reports_dir=reports_dir,
            transcripts_dir=transcripts_dir,
            session_id="artifact",
            started_at=datetime.now(),
            log_path=logs_dir / "session.log",
            report_path=reports_dir / "report.txt",
            transcript_path=transcripts_dir / "transcript.log",
            settings_path=root / "settings" / "settings.json",
            settings_snapshot_path=root / "settings" / "snapshot.json",
            manifest_path=session_dir / "session_manifest_artifact.json",
            bundle_path=session_dir / "session_bundle_artifact.zip",
        )
        self.session.log_path.write_text("log", encoding="utf-8")
        self.session.report_path.write_text("report", encoding="utf-8")
        self.session.transcript_path.write_text("transcript", encoding="utf-8")
        self.session.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.session.settings_path.write_text('{"firmware_name":"c2960x.tar"}', encoding="utf-8")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_format_duration(self) -> None:
        self.assertEqual(format_duration(None), "—")
        self.assertEqual(format_duration(65), "00:01:05")
        self.assertEqual(format_duration(3661), "01:01:01")

    def test_write_manifest_and_export_bundle(self) -> None:
        manifest = build_session_manifest(
            session=self.session,
            profile_name="Cisco Catalyst 2960-X",
            run_mode="Operator",
            started_at="2026-03-15 14:20:00",
            last_updated_at="2026-03-15 14:25:00",
            session_elapsed_seconds=300,
            active_stage_elapsed_seconds=30,
            current_state="DONE",
            current_stage="Этап 3",
            selected_target_id="COM5",
            requested_firmware_name="c2960x.tar",
            observed_firmware_version="15.2(7)E13",
            last_scan_completed_at="2026-03-15 14:21:00",
            operator_message={
                "code": "info",
                "severity": "info",
                "title": "Готово",
                "detail": "Проверка завершена.",
                "next_step": "Откройте отчёт.",
            },
            stage_durations={"scan": 12, "stage1": 60, "stage2": 180, "stage3": 48},
        )
        write_session_manifest(self.session.manifest_path, manifest)

        saved = json.loads(self.session.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["session_id"], "artifact")
        self.assertIn("00:03:00", saved["stage_durations"].values())
        self.assertEqual(saved["operator_message"]["code"], "info")
        self.assertEqual(saved["operator_message"]["title"], "Готово")

        bundle_path = export_session_bundle(self.session)
        self.assertTrue(bundle_path.exists())
        with zipfile.ZipFile(bundle_path) as archive:
            names = set(archive.namelist())
        expected_archive_names = {
            "session_manifest.json",
            "settings_snapshot.json",
            "session.log",
            "report.txt",
            "transcript.log",
        }
        self.assertEqual(names, expected_archive_names)


if __name__ == "__main__":
    unittest.main()
