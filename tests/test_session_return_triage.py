from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from ciscoautoflash.devtools import session_return_triage


def _sample_manifest(
    session_dir: Path,
    log_path: Path,
    report_path: Path,
    transcript_path: Path,
    bundle_path: Path,
) -> dict[str, object]:
    return {
        "session_id": "20260330_123456",
        "profile_name": "Cisco Catalyst 2960-X",
        "run_mode": "Real",
        "started_at": "2026-03-30 12:34:56",
        "last_updated_at": "2026-03-30 12:55:00",
        "final_state": "FAILED",
        "current_state": "FAILED",
        "current_stage": "Этап 2",
        "selected_target_id": "COM7",
        "operator_severity": "error",
        "operator_message": {
            "severity": "error",
            "title": "Операция превысила таймаут",
            "detail": "Таймаут установки: этап 2 не завершился в отведённое время",
            "next_step": "Проверьте устройство и соберите session bundle.",
        },
        "operator_text": (
            "Операция превысила таймаут | "
            "Таймаут установки: этап 2 не завершился в отведённое время | "
            "Проверьте устройство и соберите session bundle."
        ),
        "artifacts": {
            "session_dir": str(session_dir),
            "log_path": str(log_path),
            "report_path": str(report_path),
            "transcript_path": str(transcript_path),
            "settings_path": str(session_dir / "settings.json"),
            "settings_snapshot_path": str(session_dir / "settings_snapshot.json"),
            "manifest_path": str(session_dir / "session_manifest.json"),
            "bundle_path": str(bundle_path),
        },
        "stage_durations": {
            "Scan Duration": "00:00:03",
            "Stage 1 Duration": "00:00:15",
            "Stage 2 Duration": "00:10:00",
            "Stage 3 Duration": "—",
        },
        "stage_durations_seconds": {
            "scan": 3.0,
            "stage1": 15.0,
            "stage2": 600.0,
            "stage3": None,
        },
    }


def _write_fixture(root: Path) -> tuple[Path, Path]:
    session_dir = root / "20260330_123456"
    session_dir.mkdir()
    log_path = root / "ciscoautoflash_20260330_123456.log"
    report_path = root / "install_report_20260330_123456.txt"
    transcript_path = root / "transcript_20260330_123456.log"
    bundle_path = session_dir / "session_bundle_20260330_123456.zip"

    log_path.write_text(
        "\n".join(
            [
                "[2026-03-30 12:45:00] Firmware file not found on usbflash0:",
                "[2026-03-30 12:45:01] Операция превысила таймаут",
                "[2026-03-30 12:45:02] [DEMO][UI] Smoke-mode open suppressed: ignored",
            ]
        ),
        encoding="utf-8",
    )
    report_path.write_text(
        "\n".join(
            [
                "Run Mode: Real",
                "Workflow Mode: Full run",
                "Current State: FAILED",
                "Current Stage: Этап 2",
            ]
        ),
        encoding="utf-8",
    )
    transcript_path.write_text(
        "\n".join(
            [
                "2026-03-30 12:44:58 | READ     | Switch#",
                (
                    "2026-03-30 12:45:00 | READ     | "
                    "%Error opening usbflash0:c2960x.tar (No such file)"
                ),
            ]
        ),
        encoding="utf-8",
    )
    (session_dir / "settings_snapshot.json").write_text("{}", encoding="utf-8")
    manifest = _sample_manifest(session_dir, log_path, report_path, transcript_path, bundle_path)
    (session_dir / "session_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(session_dir / "session_manifest.json", arcname="session_manifest.json")
        archive.write(session_dir / "settings_snapshot.json", arcname="settings_snapshot.json")
        archive.write(log_path, arcname=log_path.name)
        archive.write(report_path, arcname=report_path.name)
        archive.write(transcript_path, arcname=transcript_path.name)
    return session_dir, bundle_path


class SessionReturnTriageTests(unittest.TestCase):
    def test_build_triage_summary_from_session_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir, _bundle_path = _write_fixture(Path(temp_dir))

            summary = session_return_triage.build_triage_summary(session_dir)

            self.assertEqual(summary["source"]["kind"], "directory")
            self.assertEqual(summary["session"]["final_state"], "FAILED")
            self.assertEqual(summary["session"]["selected_target_id"], "COM7")
            self.assertTrue(summary["artifacts"]["log"]["present"])
            self.assertTrue(summary["signatures"]["errors"])
            self.assertIn("Compare the failure", "\n".join(summary["next_steps"]))

    def test_build_triage_summary_from_bundle_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _session_dir, bundle_path = _write_fixture(Path(temp_dir))

            summary = session_return_triage.build_triage_summary(bundle_path)

            self.assertEqual(summary["source"]["kind"], "bundle-zip")
            self.assertTrue(summary["artifacts"]["bundle"]["present"])
            self.assertTrue(summary["artifacts"]["report"]["present"])
            self.assertIn("session_manifest.json", summary["source"]["inventory"])

    def test_render_markdown_summary_contains_core_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir, _bundle_path = _write_fixture(Path(temp_dir))
            summary = session_return_triage.build_triage_summary(session_dir)

            markdown = session_return_triage.render_markdown_summary(summary)

            self.assertIn("# CiscoAutoFlash Session Triage", markdown)
            self.assertIn("## Artifacts", markdown)
            self.assertIn("## Error Signatures", markdown)
            self.assertIn("COM7", markdown)

    def test_main_writes_output_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_dir, _bundle_path = _write_fixture(root)
            output_dir = root / "triage"

            exit_code = session_return_triage.main(
                [str(session_dir), "--output-dir", str(output_dir)]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue((output_dir / "20260330_123456_triage.json").exists())
            self.assertTrue((output_dir / "20260330_123456_triage.md").exists())


if __name__ == "__main__":
    unittest.main()
