from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from ciscoautoflash.devtools import session_return_triage


def _sample_manifest(
    session_dir: Path,
    log_path: Path,
    report_path: Path,
    transcript_path: Path,
    bundle_path: Path,
    event_timeline_path: Path,
    dashboard_snapshot_path: Path,
    *,
    operator_message: dict[str, object] | None = None,
) -> dict[str, object]:
    operator_message = operator_message or {
        "code": "timeout",
        "severity": "error",
        "title": "Операция превысила таймаут",
        "detail": "Таймаут установки: этап 2 не завершился в отведённое время",
        "next_step": "Проверьте устройство и соберите session bundle.",
    }
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
        "operator_message": operator_message,
        "operator_text": (
            f"{operator_message.get('title', '')} | "
            f"{operator_message.get('detail', '')} | "
            f"{operator_message.get('next_step', '')}"
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
            "event_timeline_path": str(event_timeline_path),
            "dashboard_snapshot_path": str(dashboard_snapshot_path),
        },
        "stage_durations": {
            "Scan Duration": "00:00:03",
            "Stage 1 Duration": "00:00:15",
            "Stage 2 Duration": "00:10:00",
            "Stage 3 Duration": "—",
        },
        "stage_durations_seconds": {"scan": 3.0, "stage1": 15.0, "stage2": 600.0, "stage3": None},
    }


def _write_fixture(
    root: Path,
    *,
    mode: str = "timeout",
    include_report: bool = True,
) -> tuple[Path, Path]:
    session_dir = root / "20260330_123456"
    session_dir.mkdir()
    log_path = root / "ciscoautoflash_20260330_123456.log"
    report_path = root / "install_report_20260330_123456.txt"
    transcript_path = root / "transcript_20260330_123456.log"
    bundle_path = session_dir / "session_bundle_20260330_123456.zip"
    event_timeline_path = session_dir / "event_timeline.json"
    dashboard_snapshot_path = session_dir / "dashboard_snapshot_failed.png"

    if mode == "firmware_missing":
        operator_message = {
            "code": "firmware_missing",
            "severity": "error",
            "title": "Файл образа не найден",
            "detail": "Файл c2960x.tar не найден на USB",
            "next_step": "Проверьте имя файла и содержимое usbflash0:/usbflash1:.",
        }
        log_lines = [
            "[2026-03-30 12:45:00] Проверка usbflash0: на наличие c2960x.tar",
            "[2026-03-30 12:45:01] Firmware file not found on usbflash0:",
        ]
        transcript_lines = [
            "2026-03-30 12:44:58 | READ     | Switch#",
            "2026-03-30 12:45:00 | WRITE    | dir usbflash0:",
            "2026-03-30 12:45:00 | READ     | Directory of usbflash0:/",
            "2026-03-30 12:45:00 | WRITE    | dir usbflash1:",
            "2026-03-30 12:45:00 | READ     | %Error opening usbflash1:c2960x.tar (No such file)",
        ]
    else:
        operator_message = {
            "code": "timeout",
            "severity": "error",
            "title": "Операция превысила таймаут",
            "detail": "Таймаут установки: этап 2 не завершился в отведённое время",
            "next_step": "Проверьте устройство и соберите session bundle.",
        }
        log_lines = [
            "[2026-03-30 12:45:00] Запуск archive download-sw для usbflash0:/c2960x.tar",
            "[2026-03-30 12:45:01] Операция превысила таймаут",
            "[2026-03-30 12:45:02] [DEMO][UI] Smoke-mode open suppressed: ignored",
        ]
        transcript_lines = [
            "2026-03-30 12:44:58 | READ     | Switch#",
            (
                "2026-03-30 12:45:00 | WRITE    | archive download-sw "
                "/overwrite /reload usbflash0:/c2960x.tar"
            ),
            "2026-03-30 12:45:00 | READ     | installing",
        ]

    log_path.write_text("\n".join(log_lines), encoding="utf-8")
    if include_report:
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
    transcript_path.write_text("\n".join(transcript_lines), encoding="utf-8")
    event_timeline_path.write_text(
        json.dumps(
            [
                {
                    "timestamp": "2026-03-30 12:45:00",
                    "kind": "state_changed",
                    "state": "FAILED",
                    "current_stage": "Этап 2",
                    "selected_target_id": "COM7",
                    "operator_message_code": operator_message["code"],
                    "progress_percent": 60,
                    "paths": {"report_path": str(report_path)},
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    dashboard_snapshot_path.write_bytes(b"fakepng")
    (session_dir / "settings_snapshot.json").write_text("{}", encoding="utf-8")
    manifest = _sample_manifest(
        session_dir,
        log_path,
        report_path,
        transcript_path,
        bundle_path,
        event_timeline_path,
        dashboard_snapshot_path,
        operator_message=operator_message,
    )
    (session_dir / "session_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(session_dir / "session_manifest.json", arcname="session_manifest.json")
        archive.write(session_dir / "settings_snapshot.json", arcname="settings_snapshot.json")
        archive.write(log_path, arcname=log_path.name)
        if include_report:
            archive.write(report_path, arcname=report_path.name)
        archive.write(transcript_path, arcname=transcript_path.name)
        archive.write(event_timeline_path, arcname=event_timeline_path.name)
        archive.write(dashboard_snapshot_path, arcname=dashboard_snapshot_path.name)
    return session_dir, bundle_path


class SessionReturnTriageTests(unittest.TestCase):
    def test_build_triage_summary_from_session_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir, _bundle_path = _write_fixture(Path(temp_dir))

            summary = session_return_triage.build_triage_summary(session_dir)

            self.assertEqual(summary["source"]["kind"], "directory")
            self.assertEqual(summary["session"]["final_state"], "FAILED")
            self.assertEqual(summary["session"]["failure_class"], "timeout")
            self.assertEqual(summary["session"]["selected_target_id"], "COM7")
            self.assertTrue(summary["artifacts"]["log"]["present"])
            self.assertTrue(summary["artifacts"]["event_timeline"]["present"])
            self.assertTrue(summary["artifacts"]["dashboard_snapshot"]["present"])
            self.assertEqual(summary["timeline"]["last_state"], "FAILED")
            self.assertTrue(summary["signatures"]["errors"])
            self.assertTrue(summary["diagnosis"]["inspect_next"][0].startswith("event_timeline"))
            self.assertIn("Compare the failure", "\n".join(summary["next_steps"]))
            self.assertIn("archive download-sw", "\n".join(summary["tails"]["transcript"]))

    def test_build_triage_summary_from_bundle_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _session_dir, bundle_path = _write_fixture(Path(temp_dir))

            summary = session_return_triage.build_triage_summary(bundle_path)

            self.assertEqual(summary["source"]["kind"], "bundle-zip")
            self.assertTrue(summary["artifacts"]["bundle"]["present"])
            self.assertTrue(summary["artifacts"]["report"]["present"])
            self.assertIn("session_manifest.json", summary["source"]["inventory"])
            self.assertIn("event_timeline.json", summary["source"]["inventory"])

    def test_build_triage_summary_classifies_firmware_missing_and_missing_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir, _bundle_path = _write_fixture(
                Path(temp_dir),
                mode="firmware_missing",
                include_report=False,
            )

            summary = session_return_triage.build_triage_summary(session_dir)

            self.assertEqual(summary["session"]["failure_class"], "firmware_missing")
            self.assertFalse(summary["artifacts"]["report"]["present"])
            self.assertIn("Missing report artifact.", summary["issues"])
            next_steps = "\n".join(summary["next_steps"])
            self.assertIn("Verify the exact firmware filename", next_steps)
            self.assertIn("session_bundle.zip", next_steps)

    def test_render_markdown_summary_contains_core_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir, _bundle_path = _write_fixture(Path(temp_dir))
            summary = session_return_triage.build_triage_summary(session_dir)

            markdown = session_return_triage.render_markdown_summary(summary)

            self.assertIn("# CiscoAutoFlash Session Triage", markdown)
            self.assertIn("## Artifacts", markdown)
            self.assertIn("## Event Timeline", markdown)
            self.assertIn("## Error Signatures", markdown)
            self.assertIn("Failure class", markdown)
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

    def test_main_prints_safely_to_cp1252_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_dir, _bundle_path = _write_fixture(root)
            output_dir = root / "triage"
            stdout_bytes = io.BytesIO()
            stdout = io.TextIOWrapper(stdout_bytes, encoding="cp1252", errors="strict")

            with patch("sys.stdout", stdout):
                exit_code = session_return_triage.main(
                    [str(session_dir), "--output-dir", str(output_dir)]
                )

            stdout.flush()
            rendered = stdout_bytes.getvalue().decode("cp1252", errors="replace")
            self.assertEqual(exit_code, 0)
            self.assertIn("CiscoAutoFlash Session Triage", rendered)
            self.assertIn("JSON:", rendered)


if __name__ == "__main__":
    unittest.main()
