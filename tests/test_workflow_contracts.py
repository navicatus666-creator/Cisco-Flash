from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from ciscoautoflash.config import SessionPaths, WorkflowTiming
from ciscoautoflash.core.events import AppEvent
from ciscoautoflash.core.models import ConnectionTarget, ScanResult
from ciscoautoflash.core.transport import Transport, TransportFactory, TransportType
from ciscoautoflash.core.workflow import WorkflowController
from ciscoautoflash.profiles import build_c2960x_profile


class ScriptedTransport(Transport):
    def __init__(self) -> None:
        self.connected = False

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def write(self, data: str) -> None:
        return None

    def read_available(self) -> str:
        return ""

    def read_until(self, markers, timeout: float):
        return None, ""

    def send_command(self, command: str, wait: float = 1.0) -> str:
        return ""

    def interrupt(self) -> None:
        return None

    def is_connected(self) -> bool:
        return self.connected


class ScriptedFactory(TransportFactory):
    transport_type = TransportType.SERIAL

    def __init__(self, targets: list[ConnectionTarget], results: list[ScanResult]):
        self.targets = list(targets)
        self.results = list(results)

    def list_targets(self) -> list[ConnectionTarget]:
        return list(self.targets)

    def probe(self, target: ConnectionTarget, markers, timeout: float) -> ScanResult:
        return self.results.pop(0)

    def create(self, target: ConnectionTarget) -> Transport:
        return ScriptedTransport()


class WorkflowContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = build_c2960x_profile()
        self.events: list[AppEvent] = []
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        logs_dir = root / "logs"
        reports_dir = root / "reports"
        transcripts_dir = root / "transcripts"
        sessions_dir = root / "sessions"
        session_dir = root / "sessions" / "contract"
        for directory in (logs_dir, reports_dir, transcripts_dir, sessions_dir, session_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.session = SessionPaths(
            base_dir=root,
            sessions_dir=sessions_dir,
            session_dir=session_dir,
            logs_dir=logs_dir,
            reports_dir=reports_dir,
            transcripts_dir=transcripts_dir,
            session_id="contract",
            started_at=datetime(2026, 3, 15, 12, 0, 0),
            log_path=logs_dir / "session.log",
            report_path=reports_dir / "report.txt",
            transcript_path=transcripts_dir / "transcript.log",
            settings_path=root / "settings.json",
            settings_snapshot_path=session_dir / "settings_snapshot.json",
            manifest_path=session_dir / "session_manifest_contract.json",
            bundle_path=session_dir / "session_bundle_contract.zip",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def make_controller(self, factory: ScriptedFactory) -> WorkflowController:
        controller = WorkflowController(
            profile=self.profile,
            transport_factory=factory,
            session=self.session,
            event_handler=self.events.append,
            timing=WorkflowTiming(
                command_wait_short=0.0,
                command_wait_medium=0.0,
                command_wait_long=0.0,
            ),
        )
        controller.initialize()
        return controller

    def test_initialize_emits_session_paths_with_transcript_and_session_artifact_paths(
        self,
    ) -> None:
        target = ConnectionTarget("COM5", "COM5", {"description": "USB Serial"})
        factory = ScriptedFactory([target], [ScanResult(target, True, "ready", "priv")])
        self.make_controller(factory)

        session_event = next(event for event in self.events if event.kind == "session_paths")

        self.assertEqual(session_event.payload["log_path"], str(self.session.log_path))
        self.assertEqual(session_event.payload["report_path"], str(self.session.report_path))
        self.assertEqual(
            session_event.payload["transcript_path"],
            str(self.session.transcript_path),
        )
        self.assertEqual(session_event.payload["settings_path"], str(self.session.settings_path))
        self.assertEqual(session_event.payload["manifest_path"], str(self.session.manifest_path))
        self.assertEqual(session_event.payload["bundle_path"], str(self.session.bundle_path))
        self.assertEqual(session_event.payload["session_dir"], str(self.session.session_dir))

    def test_scan_devices_emits_scan_results_event(self) -> None:
        target = ConnectionTarget("COM5", "COM5", {"description": "USB Serial"})
        factory = ScriptedFactory(
            [target],
            [
                ScanResult(
                    target=target,
                    available=True,
                    status_message="Коммутатор готов (Switch#)",
                    prompt_type="priv",
                    connection_state="ready",
                    recommended_next_action="Можно запускать Stage 1.",
                    score=500,
                )
            ],
        )
        controller = self.make_controller(factory)

        controller.scan_devices(background=False)

        scan_event = next(event for event in self.events if event.kind == "scan_results")
        self.assertEqual(len(scan_event.payload["results"]), 1)
        self.assertEqual(scan_event.payload["results"][0].target.id, "COM5")

    def test_manual_selection_survives_scan_refresh(self) -> None:
        target_a = ConnectionTarget("COM5", "COM5", {"description": "USB Serial"})
        target_b = ConnectionTarget("COM7", "COM7", {"description": "USB Serial"})
        factory = ScriptedFactory(
            [target_a, target_b],
            [
                ScanResult(target_a, True, "ready", "priv", connection_state="ready", score=600),
                ScanResult(target_b, True, "ready", "priv", connection_state="ready", score=400),
                ScanResult(target_a, True, "ready", "priv", connection_state="ready", score=700),
                ScanResult(target_b, True, "ready", "priv", connection_state="ready", score=300),
            ],
        )
        controller = self.make_controller(factory)

        controller.scan_devices(background=False)
        self.assertEqual(controller.selected_target.id, "COM5")

        self.assertTrue(controller.select_target("COM7"))
        self.assertEqual(controller.selected_target.id, "COM7")

        controller.scan_devices(background=False)

        self.assertEqual(controller.selected_target.id, "COM7")
        self.assertTrue(controller.device_snapshot.is_manual_override)
        selected_event = [
            event for event in self.events if event.kind == "selected_target_changed"
        ][-1]
        self.assertEqual(selected_event.payload["target_id"], "COM7")


if __name__ == "__main__":
    unittest.main()
