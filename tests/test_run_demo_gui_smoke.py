from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

if "pyautogui" not in sys.modules:
    sys.modules["pyautogui"] = types.SimpleNamespace(
        click=lambda *args, **kwargs: None,
        hotkey=lambda *args, **kwargs: None,
        press=lambda *args, **kwargs: None,
        screenshot=lambda *args, **kwargs: None,
        FAILSAFE=False,
        PAUSE=0.0,
    )

if "pywinauto" not in sys.modules:
    sys.modules["pywinauto"] = types.SimpleNamespace(Desktop=object)

if "pywinauto.base_wrapper" not in sys.modules:
    sys.modules["pywinauto.base_wrapper"] = types.SimpleNamespace(BaseWrapper=object)

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_demo_gui_smoke.py"
SPEC = importlib.util.spec_from_file_location("run_demo_gui_smoke_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

DemoGuiSmokeRunner = MODULE.DemoGuiSmokeRunner
SmokeFailure = MODULE.SmokeFailure


class DemoGuiSmokeRunnerIdleGateTests(unittest.TestCase):
    def test_wait_for_demo_idle_requires_marker_and_ready_state(self) -> None:
        runner = object.__new__(DemoGuiSmokeRunner)
        ready_state = {
            "state": {
                "demo_busy": False,
                "stop_enabled": False,
                "last_demo_idle_marker": (
                    "[DEMO] Controller idle: "
                    "stage2_install_success (completed)"
                ),
            }
        }
        runner._refresh_automation_map = Mock(side_effect=[ready_state, ready_state])
        runner._wait_for_new_log_marker = Mock(
            return_value=(
                "[2026-03-22 00:30:35] "
                "[DEMO] Controller idle: stage2_install_success (completed)"
            )
        )

        evidence = DemoGuiSmokeRunner._wait_for_demo_idle(runner, timeout=0.2)

        self.assertIn("Controller idle: stage2_install_success", evidence[0])
        self.assertIn("busy=False", evidence[1])

    def test_wait_for_demo_idle_if_needed_skips_when_already_idle(self) -> None:
        runner = object.__new__(DemoGuiSmokeRunner)
        runner._refresh_automation_map = Mock(
            return_value={
                "state": {
                    "demo_busy": False,
                    "stop_enabled": False,
                    "last_demo_idle_marker": "",
                }
            }
        )
        runner._wait_for_new_log_marker = Mock()

        evidence = DemoGuiSmokeRunner._wait_for_demo_idle_if_needed(runner, timeout=0.2)

        self.assertEqual(evidence, [])
        runner._wait_for_new_log_marker.assert_not_called()

    def test_wait_for_demo_idle_times_out_when_ready_signal_never_matches(self) -> None:
        runner = object.__new__(DemoGuiSmokeRunner)
        stale_state = {
            "state": {
                "demo_busy": True,
                "stop_enabled": True,
                "last_demo_idle_marker": "",
            }
        }
        runner._refresh_automation_map = Mock(return_value=stale_state)
        runner._wait_for_new_log_marker = Mock(return_value="")

        with patch.object(MODULE.time, "sleep", return_value=None):
            with self.assertRaises(SmokeFailure):
                DemoGuiSmokeRunner._wait_for_demo_idle(runner, timeout=0.05)

    def test_scenario_selector_step_waits_for_idle_before_clicking(self) -> None:
        runner = object.__new__(DemoGuiSmokeRunner)
        runner.scenario_display_by_name = {
            "stage2_install_timeout": "Этап 2: timeout установки"
        }
        runner._last_marker_line = ""
        runner._wait_for_demo_idle_if_needed = Mock()
        runner._select_scenario = Mock()
        runner._refresh_automation_map = Mock(
            return_value={
                "selector": {
                    "current_name": "stage2_install_timeout",
                    "current_display": "Этап 2: timeout установки",
                }
            }
        )

        def run_step(name, verify, *, action=None, produced_paths=None):
            if action is not None:
                action()
            verify()

        runner._run_step = run_step

        DemoGuiSmokeRunner._scenario_selector_step(runner, "stage2_install_timeout")

        runner._wait_for_demo_idle_if_needed.assert_called_once()
        runner._select_scenario.assert_called_once_with("stage2_install_timeout")

    def test_stage3_step_waits_for_idle_before_passing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "install_report.txt"
            report_path.write_text("ok", encoding="utf-8")
            runner = object.__new__(DemoGuiSmokeRunner)
            runner.report_path = report_path
            calls: list[str] = []
            runner._click_button = Mock()
            runner._wait_for_file_exists = Mock(
                side_effect=lambda *args, **kwargs: calls.append("file") or report_path
            )
            runner._wait_for_manifest = Mock(
                side_effect=lambda *args, **kwargs: calls.append("manifest")
                or {"final_state": "DONE"}
            )
            runner._wait_for_new_log_marker = Mock(
                side_effect=lambda *args, **kwargs: calls.append("marker")
                or "[DEMO][UI] Запущен Stage 3"
            )
            runner._wait_for_demo_idle = Mock(
                side_effect=lambda *args, **kwargs: calls.append("idle")
                or ["idle marker", "idle state"]
            )

            def run_step(name, verify, *, action=None, produced_paths=None):
                if action is not None:
                    action()
                return verify()

            runner._run_step = run_step

            DemoGuiSmokeRunner._stage3_step(runner)

            runner._click_button.assert_called_once_with("stage3")
            runner._wait_for_demo_idle.assert_called_once()
            self.assertEqual(calls, ["file", "manifest", "marker", "idle"])

    def test_wait_for_smoke_open_path_returns_when_automation_map_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "install_report.txt"
            target.write_text("ok", encoding="utf-8")
            runner = object.__new__(DemoGuiSmokeRunner)
            runner._refresh_automation_map = Mock(
                return_value={
                    "state": {
                        "last_smoke_open_path": str(target.resolve()),
                    }
                }
            )

            evidence = DemoGuiSmokeRunner._wait_for_smoke_open_path(
                runner,
                target,
                timeout=0.05,
            )

            self.assertEqual(evidence, f"Automation map open confirmed: {target.resolve()}")

    def test_prime_smoke_open_retries_until_path_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "install_report.txt"
            target.write_text("ok", encoding="utf-8")
            runner = object.__new__(DemoGuiSmokeRunner)
            runner._lookup_control_point = Mock(return_value=(100, 200))
            runner._click_absolute = Mock()
            runner._wait_for_smoke_open_path = Mock(
                side_effect=[
                    "",
                    "",
                    f"Automation map open confirmed: {target.resolve()}",
                ]
            )

            DemoGuiSmokeRunner._prime_smoke_open(runner, "open_report", target)

            self.assertEqual(runner._click_absolute.call_count, 3)
            runner._wait_for_smoke_open_path.assert_called()

    def test_verify_smoke_open_accepts_automation_map_confirmation_without_marker(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "install_report.txt"
            target.write_text("ok", encoding="utf-8")
            runner = object.__new__(DemoGuiSmokeRunner)
            runner._wait_for_new_log_marker = Mock(return_value="")
            runner._wait_for_smoke_open_path = Mock(
                return_value=f"Automation map open confirmed: {target.resolve()}"
            )
            runner._refresh_paths = Mock()

            evidence = DemoGuiSmokeRunner._verify_smoke_open(runner, target)

            self.assertEqual(
                evidence,
                [f"Automation map open confirmed: {target.resolve()}"],
            )
            runner._refresh_paths.assert_called_once()


if __name__ == "__main__":
    unittest.main()
