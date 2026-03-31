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
            "2026-03-30 12:45:00 | WRITE    | archive download-sw /overwrite /reload usbflash0:/c2960x.tar",
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
    (session_dir / "settings_snapshot.json").write_text("{}", encoding="utf-8")
    manifest = _sample_manifest(
        session_dir,
        log_path,
        report_path,
        transcript_path,
        bundle_path,
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
            self.assertTrue(summary["signatures"]["errors"])
            self.assertIn("stalled", summary["diagnosis"]["most_likely_cause"])
            self.assertIn("dashboard screenshot", summary["diagnosis"]["recommended_next_capture"])
            self.assertIn("archive download-sw", "\n".join(summary["diagnosis"]["inspect_next"]))
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
            self.assertIn("requested firmware tar", summary["diagnosis"]["most_likely_cause"])
            self.assertIn("dir usbflash0:", summary["diagnosis"]["recommended_next_capture"])
            next_steps = "\n".join(summary["next_steps"])
            self.assertIn("Verify the exact firmware filename", next_steps)
            self.assertIn("session_bundle.zip", next_steps)

    def test_build_triage_summary_prefers_timeout_over_generic_failed_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir, _bundle_path = _write_fixture(Path(temp_dir))
            manifest_path = session_dir / "session_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["operator_message"]["code"] = "failed"
            manifest["operator_text"] = (
                "Сбой на этапе 2 | Операция превысила таймаут | Проверьте устройство и соберите session bundle."
            )
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

            summary = session_return_triage.build_triage_summary(session_dir)

            self.assertEqual(summary["session"]["failure_class"], "timeout")
            self.assertIn("stalled", summary["diagnosis"]["most_likely_cause"])

    def test_build_triage_summary_flags_log_transcript_disagreement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir, _bundle_path = _write_fixture(Path(temp_dir))
            manifest_path = session_dir / "session_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["operator_message"]["code"] = "other"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            log_path = Path(manifest["artifacts"]["log_path"])
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write("\n[2026-03-30 12:45:03] Firmware file not found on usbflash0:\n")

            summary = session_return_triage.build_triage_summary(session_dir)

            self.assertEqual(summary["session"]["failure_class"], "timeout")
            self.assertIn(
                "Log and transcript disagree: firmware missing was reported after the install command had already started.",
                summary["issues"],
            )

    def test_build_triage_summary_flags_report_mismatch_as_artifact_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir, _bundle_path = _write_fixture(Path(temp_dir))
            manifest_path = session_dir / "session_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["final_state"] = "DONE"
            manifest["current_state"] = "DONE"
            manifest["current_stage"] = "Этап 3"
            manifest["operator_severity"] = "info"
            manifest["operator_message"] = {
                "code": "info",
                "severity": "info",
                "title": "Этап 3 завершён",
                "detail": "Сформирован финальный install report.",
                "next_step": "Откройте отчёт и транскрипт.",
            }
            manifest["operator_text"] = "Этап 3 завершён | Сформирован финальный install report. | Откройте отчёт и транскрипт."
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

            report_path = Path(manifest["artifacts"]["report_path"])
            report_path.write_text(
                "\n".join(
                    [
                        "Run Mode: Real",
                        "Workflow Mode: Verify-only",
                        "Current State: FAILED",
                        "Current Stage: Этап 3",
                        r"Transcript: C:\broken\transcript.log",
                    ]
                ),
                encoding="utf-8",
            )

            summary = session_return_triage.build_triage_summary(session_dir)

            self.assertEqual(summary["session"]["failure_class"], "artifact_incomplete")
            self.assertIn(
                "Report Transcript field does not match transcript artifact.",
                summary["issues"],
            )
            self.assertIn(
                "Report Current State does not match manifest final_state.",
                summary["issues"],
            )
            self.assertIn("whole session folder", summary["diagnosis"]["recommended_next_capture"])

    def test_render_markdown_summary_contains_core_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir, _bundle_path = _write_fixture(Path(temp_dir))
            summary = session_return_triage.build_triage_summary(session_dir)

            markdown = session_return_triage.render_markdown_summary(summary)

            self.assertIn("# CiscoAutoFlash Session Triage", markdown)
            self.assertIn("## Artifacts", markdown)
            self.assertIn("## Error Signatures", markdown)
            self.assertIn("## Inspect Next", markdown)
            self.assertIn("Failure class", markdown)
            self.assertIn("Most likely cause", markdown)
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

    def test_main_writes_output_files_for_incomplete_session_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session_dir, _bundle_path = _write_fixture(
                root,
                mode="firmware_missing",
                include_report=False,
            )
            output_dir = root / "triage"

            exit_code = session_return_triage.main(
                [str(session_dir), "--output-dir", str(output_dir)]
            )

            self.assertEqual(exit_code, 0)
            payload = json.loads(
                (output_dir / "20260330_123456_triage.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["session"]["failure_class"], "firmware_missing")
            self.assertIn("Missing report artifact.", payload["issues"])


if __name__ == "__main__":
    unittest.main()
