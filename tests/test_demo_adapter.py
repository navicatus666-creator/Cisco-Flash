from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ciscoautoflash.config import AppConfig
from ciscoautoflash.replay.adapter import DemoReplayController


class DemoScheduler:
    def __init__(self) -> None:
        self.calls: list[tuple[int, object]] = []

    def after(self, delay: int, callback) -> None:
        self.calls.append((delay, callback))

    def run_all(self) -> None:
        for _, callback in sorted(self.calls, key=lambda item: item[0]):
            callback()
        self.calls.clear()


class DemoReplayControllerTests(unittest.TestCase):
    def make_controller(
        self, scenario_name: str = "scan_ready"
    ) -> tuple[DemoReplayController, list, DemoScheduler]:
        runtime_root = Path(tempfile.mkdtemp(prefix="ciscoautoflash-demo-test-"))
        session = AppConfig(runtime_root=runtime_root).create_session_paths()
        events = []
        scheduler = DemoScheduler()
        controller = DemoReplayController(
            session=session,
            runtime_root=runtime_root,
            event_handler=events.append,
            schedule=scheduler.after,
            scenario_name=scenario_name,
            playback_delay_ms=1,
        )
        return controller, events, scheduler

    def test_initialize_emits_demo_bootstrap_events(self) -> None:
        controller, events, _scheduler = self.make_controller()

        controller.initialize()

        event_kinds = [event.kind for event in events]
        self.assertIn("session_paths", event_kinds)
        self.assertIn("device_snapshot", event_kinds)
        self.assertIn("operator_message", event_kinds)
        self.assertIn("actions_changed", event_kinds)
        self.assertEqual(controller.current_scenario.name, "scan_ready")

    def test_scan_playback_emits_replay_events_and_restores_actions(self) -> None:
        controller, events, scheduler = self.make_controller("scan_ready")

        controller.initialize()
        events.clear()

        started = controller.scan_devices()
        self.assertTrue(started)
        self.assertTrue(scheduler.calls)
        scheduler.run_all()

        event_kinds = [event.kind for event in events]
        self.assertIn("scan_results", event_kinds)
        self.assertIn("selected_target_changed", event_kinds)
        self.assertEqual(controller.select_target("COM5"), True)

    def test_stop_cancels_pending_playback(self) -> None:
        controller, events, scheduler = self.make_controller("stage2_install_success")

        controller.initialize()
        events.clear()
        controller.run_stage2("c2960x-universalk9-tar.152-7.E13.tar")
        controller.stop()
        scheduler.run_all()

        state_events = [event for event in events if event.kind == "state_changed"]
        self.assertTrue(any(event.payload.get("state") == "IDLE" for event in state_events))
        self.assertTrue(any(event.kind == "operator_message" for event in events))

    def test_unsupported_action_emits_warning_message(self) -> None:
        controller, events, _scheduler = self.make_controller("scan_ready")

        controller.initialize()
        events.clear()
        started = controller.run_stage3()

        self.assertFalse(started)
        warning = [event for event in events if event.kind == "operator_message"][-1]
        self.assertEqual(warning.payload["message"].severity, "warning")


if __name__ == "__main__":
    unittest.main()
