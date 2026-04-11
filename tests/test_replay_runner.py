from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ciscoautoflash.devtools import session_return_triage
from ciscoautoflash.replay.loader import load_scenario
from ciscoautoflash.replay.runner import ReplayRunner
from ciscoautoflash.replay.runner import main as replay_main

PROJECT_ROOT = Path(__file__).resolve().parents[1]

ALLOWED_EVENT_KINDS = {
    "actions_changed",
    "device_snapshot",
    "log",
    "operator_message",
    "progress",
    "report_ready",
    "scan_results",
    "selected_target_changed",
    "session_paths",
    "state_changed",
}
SCENARIO_DIR = PROJECT_ROOT / "replay_scenarios"


class ReplayRunnerTests(unittest.TestCase):
    def run_named_scenario_with_runtime(self, name: str) -> tuple[Path, object]:
        scenario = load_scenario(name)
        runtime_root = Path(tempfile.mkdtemp(prefix="ciscoautoflash-replay-test-"))
        result = ReplayRunner(scenario, runtime_root=runtime_root).run()
        return runtime_root, result

    def run_named_scenario(self, name: str):
        _, result = self.run_named_scenario_with_runtime(name)
        return result

    @staticmethod
    def session_dir_for_runtime(runtime_root: Path) -> Path:
        manifest_paths = sorted(runtime_root.rglob("session_manifest*.json"))
        if len(manifest_paths) != 1:
            raise AssertionError(
                f"Expected exactly one manifest under {runtime_root}, "
                f"got {manifest_paths}"
            )
        return manifest_paths[0].parent

    def assert_event_contract(self, result) -> None:
        self.assertTrue(set(result.event_counts).issubset(ALLOWED_EVENT_KINDS))
        self.assertIn("session_paths", result.event_counts)
        self.assertIn("device_snapshot", result.event_counts)
        self.assertIn("operator_message", result.event_counts)

    def test_scan_ready_scenario_emits_scan_events_and_selects_target(self) -> None:
        result = self.run_named_scenario("scan_ready")

        self.assert_event_contract(result)
        self.assertEqual(result.final_state, "IDLE")
        self.assertEqual(result.selected_target_id, "COM5")
        self.assertEqual(result.device_snapshot.prompt_type, "priv")
        self.assertEqual(result.device_snapshot.connection_state, "ready")
        self.assertEqual(result.operator_message.severity, "info")
        self.assertGreaterEqual(result.event_counts.get("scan_results", 0), 1)

    def test_scan_prompt_scenarios_map_operator_codes_and_prompt_types(self) -> None:
        expected = {
            "scan_user_prompt": ("user", "user_mode"),
            "scan_press_return": ("press_return", "press_return"),
            "scan_login": ("login", "login_required"),
            "scan_config_dialog": ("config_dialog", "config_dialog"),
            "scan_rommon": ("rommon", "rommon"),
        }

        for scenario_name, (prompt_type, operator_code) in expected.items():
            with self.subTest(scenario=scenario_name):
                result = self.run_named_scenario(scenario_name)
                self.assert_event_contract(result)
                self.assertEqual(result.final_state, "IDLE")
                self.assertEqual(result.selected_target_id, "COM5")
                self.assertEqual(result.device_snapshot.prompt_type, prompt_type)
                self.assertEqual(result.operator_message.code, operator_code)
                self.assertEqual(result.event_counts.get("selected_target_changed"), 1)

    def test_stage1_reboot_config_dialog_scenario_completes_and_writes_no(self) -> None:
        result = self.run_named_scenario("stage1_reboot_config_dialog")

        self.assert_event_contract(result)
        self.assertEqual(result.final_state, "DONE")
        self.assertTrue(result.stage1_complete)
        transcript = result.transcript_path.read_text(encoding="utf-8")
        self.assertIn("| WRITE", transcript)
        self.assertIn("| no", transcript)
        self.assertIn("Would you like to enter the initial configuration dialog", transcript)

    def test_stage2_install_success_scenario_marks_complete_and_progresses(self) -> None:
        result = self.run_named_scenario("stage2_install_success")

        self.assert_event_contract(result)
        self.assertEqual(result.final_state, "DONE")
        self.assertTrue(result.stage2_complete)
        progress_names = [
            event.payload.get("stage_name")
            for event in result.events
            if event.kind == "progress" and "stage_name" in event.payload
        ]
        self.assertIn("Installing", progress_names)
        transcript = result.transcript_path.read_text(encoding="utf-8")
        self.assertIn("archive download-sw /overwrite /reload usbflash0:", transcript)

    def test_stage2_timeout_scenario_fails_with_timeout_message(self) -> None:
        result = self.run_named_scenario("stage2_install_timeout")

        self.assert_event_contract(result)
        self.assertEqual(result.final_state, "FAILED")
        self.assertFalse(result.stage2_complete)
        self.assertEqual(result.operator_message.code, "timeout")
        self.assertIn("Повторите шаг", result.operator_message.next_step)
        transcript = result.transcript_path.read_text(encoding="utf-8")
        self.assertIn("dir usbflash0:", transcript)

    def test_stage2_firmware_missing_scenario_fails_before_install(self) -> None:
        runtime_root, result = self.run_named_scenario_with_runtime("stage2_firmware_missing")

        self.assert_event_contract(result)
        self.assertEqual(result.final_state, "FAILED")
        self.assertFalse(result.stage2_complete)
        self.assertEqual(result.operator_message.code, "firmware_missing")
        self.assertIn("usbflash0:/usbflash1:", result.operator_message.next_step)
        transcript = result.transcript_path.read_text(encoding="utf-8")
        self.assertIn("dir usbflash0:", transcript)
        self.assertIn("dir usbflash1:", transcript)
        self.assertNotIn("archive download-sw /overwrite /reload", transcript)
        manifest_paths = sorted(runtime_root.rglob("session_manifest*.json"))
        self.assertEqual(len(manifest_paths), 1)
        manifest = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
        self.assertEqual(manifest["current_state"], "FAILED")
        self.assertEqual(manifest["operator_message"]["code"], "firmware_missing")

    def test_stage2_log_transcript_disagreement_scenario_surfaces_issue(self) -> None:
        runtime_root, result = self.run_named_scenario_with_runtime(
            "stage2_log_transcript_disagreement"
        )

        self.assert_event_contract(result)
        self.assertEqual(result.final_state, "FAILED")
        self.assertEqual(result.operator_message.code, "timeout")

        summary = session_return_triage.build_triage_summary(
            self.session_dir_for_runtime(runtime_root)
        )
        self.assertEqual(summary["session"]["failure_class"], "timeout")
        self.assertIn(
            (
                "Log and transcript disagree: firmware missing was "
                "reported after the install command had already started."
            ),
            summary["issues"],
        )

    def test_stage3_verify_scenario_writes_report_and_verification_transcript(self) -> None:
        result = self.run_named_scenario("stage3_verify")

        self.assert_event_contract(result)
        self.assertEqual(result.final_state, "DONE")
        self.assertTrue(result.report_path.exists())
        report = result.report_path.read_text(encoding="utf-8")
        self.assertIn("Run Mode: Demo", report)
        self.assertIn("Workflow Mode: Verify-only", report)
        self.assertIn(
            "INSTALLATION STAGES may remain NOT COMPLETED intentionally",
            report,
        )
        transcript = result.transcript_path.read_text(encoding="utf-8")
        self.assertIn("show version", transcript)
        self.assertIn("show boot", transcript)
        self.assertIn("dir flash:", transcript)

    def test_stage3_artifact_incomplete_scenario_surfaces_artifact_incomplete_triage(self) -> None:
        runtime_root, result = self.run_named_scenario_with_runtime("stage3_artifact_incomplete")

        self.assert_event_contract(result)
        self.assertEqual(result.final_state, "DONE")
        self.assertFalse(result.report_path.exists())

        summary = session_return_triage.build_triage_summary(
            self.session_dir_for_runtime(runtime_root)
        )
        self.assertEqual(summary["session"]["failure_class"], "artifact_incomplete")
        self.assertIn("Missing report artifact.", summary["issues"])
        self.assertIn(
            "whole session folder",
            summary["diagnosis"]["recommended_next_capture"],
        )
        self.assertIn("report:", "\n".join(summary["diagnosis"]["inspect_next"]))

    def test_stage3_report_state_mismatch_scenario_surfaces_report_consistency_issue(self) -> None:
        runtime_root, result = self.run_named_scenario_with_runtime("stage3_report_state_mismatch")

        self.assert_event_contract(result)
        self.assertEqual(result.final_state, "DONE")
        self.assertTrue(result.report_path.exists())

        summary = session_return_triage.build_triage_summary(
            self.session_dir_for_runtime(runtime_root)
        )
        self.assertEqual(summary["session"]["failure_class"], "artifact_incomplete")
        self.assertIn(
            "Report Transcript field does not match transcript artifact.",
            summary["issues"],
        )
        self.assertIn(
            "Report Current State does not match manifest final_state.",
            summary["issues"],
        )

    def test_full_install_verify_scenario_runs_end_to_end_and_writes_manifest(self) -> None:
        runtime_root, result = self.run_named_scenario_with_runtime("full_install_verify")

        self.assert_event_contract(result)
        self.assertEqual(result.final_state, "DONE")
        self.assertTrue(result.stage1_complete)
        self.assertTrue(result.stage2_complete)
        self.assertTrue(result.report_path.exists())
        report = result.report_path.read_text(encoding="utf-8")
        self.assertIn("Run Mode: Demo", report)
        self.assertIn("Workflow Mode: Install+Verify", report)
        transcript = result.transcript_path.read_text(encoding="utf-8")
        self.assertIn("reload", transcript)
        self.assertIn("archive download-sw /overwrite /reload usbflash0:", transcript)
        self.assertIn("show version", transcript)

        manifest_paths = sorted(runtime_root.rglob("session_manifest*.json"))
        self.assertEqual(len(manifest_paths), 1)
        manifest = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
        self.assertEqual(manifest["current_state"], "DONE")
        self.assertEqual(manifest["final_state"], "DONE")
        self.assertEqual(manifest["current_stage"], "Этап 3")
        self.assertEqual(manifest["selected_target_id"], "COM5")
        self.assertEqual(
            manifest["requested_firmware_name"],
            "c2960x-universalk9-tar.152-7.E13.tar",
        )
        self.assertEqual(manifest["run_mode"], "Demo")
        self.assertTrue(any(value != "—" for value in manifest["stage_durations"].values()))

    def test_loader_resolves_bare_scenario_name(self) -> None:
        scenario = load_scenario("scan_ready")
        self.assertEqual(scenario.name, "scan_ready")
        self.assertEqual(scenario.display_name, "Сканирование: Switch# готов")
        self.assertEqual(scenario.supported_actions, ("scan",))
        self.assertEqual(scenario.target.id, "COM5")

    def test_loader_resolves_full_install_verify_scenario(self) -> None:
        scenario = load_scenario("full_install_verify")
        self.assertEqual(scenario.name, "full_install_verify")
        self.assertEqual(scenario.action, "full")
        self.assertEqual(scenario.supported_actions, ("scan", "stage1", "stage2", "stage3"))
        self.assertEqual(scenario.firmware_name, "c2960x-universalk9-tar.152-7.E13.tar")

    def test_loader_resolves_stage2_firmware_missing_scenario(self) -> None:
        scenario = load_scenario("stage2_firmware_missing")
        self.assertEqual(scenario.name, "stage2_firmware_missing")
        self.assertEqual(scenario.action, "stage2")
        self.assertEqual(scenario.supported_actions, ("scan", "stage2"))

    def test_cli_main_prints_summary_and_events(self) -> None:
        runtime_root = Path(tempfile.mkdtemp(prefix="ciscoautoflash-replay-cli-"))
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = replay_main(
                [
                    "scan_ready",
                    "--runtime-root",
                    str(runtime_root),
                    "--show-events",
                ]
            )
        output = buffer.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Scenario: scan_ready", output)
        self.assertIn("Selected target: COM5", output)
        self.assertIn("Events:", output)
        self.assertIn("scan_results", output)

    def test_replay_scenarios_directory_contains_expected_core_fixtures(self) -> None:
        expected = {
            "scan_ready.toml",
            "scan_user_prompt.toml",
            "scan_press_return.toml",
            "scan_login.toml",
            "scan_config_dialog.toml",
            "scan_rommon.toml",
            "stage1_reboot_config_dialog.toml",
            "stage2_firmware_missing.toml",
            "stage2_log_transcript_disagreement.toml",
            "stage2_install_success.toml",
            "stage2_install_timeout.toml",
            "stage3_artifact_incomplete.toml",
            "stage3_report_state_mismatch.toml",
            "stage3_verify.toml",
            "full_install_verify.toml",
        }
        self.assertTrue(expected.issubset({path.name for path in SCENARIO_DIR.glob("*.toml")}))


if __name__ == "__main__":
    unittest.main()
