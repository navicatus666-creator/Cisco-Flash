from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ciscoautoflash.replay.loader import load_scenario
from ciscoautoflash.replay.runner import ReplayRunner
from ciscoautoflash.replay.runner import main as replay_main

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
SCENARIO_DIR = Path(r"C:\PROJECT\replay_scenarios")


class ReplayRunnerTests(unittest.TestCase):
    def run_named_scenario(self, name: str):
        scenario = load_scenario(name)
        runtime_root = Path(tempfile.mkdtemp(prefix="ciscoautoflash-replay-test-"))
        return ReplayRunner(scenario, runtime_root=runtime_root).run()

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

    def test_stage3_verify_scenario_writes_report_and_verification_transcript(self) -> None:
        result = self.run_named_scenario("stage3_verify")

        self.assert_event_contract(result)
        self.assertEqual(result.final_state, "DONE")
        self.assertTrue(result.report_path.exists())
        transcript = result.transcript_path.read_text(encoding="utf-8")
        self.assertIn("show version", transcript)
        self.assertIn("show boot", transcript)
        self.assertIn("dir flash:", transcript)

    def test_loader_resolves_bare_scenario_name(self) -> None:
        scenario = load_scenario("scan_ready")
        self.assertEqual(scenario.name, "scan_ready")
        self.assertEqual(scenario.target.id, "COM5")

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
            "stage2_install_success.toml",
            "stage2_install_timeout.toml",
            "stage3_verify.toml",
        }
        self.assertTrue(expected.issubset({path.name for path in SCENARIO_DIR.glob("*.toml")}))


if __name__ == "__main__":
    unittest.main()
