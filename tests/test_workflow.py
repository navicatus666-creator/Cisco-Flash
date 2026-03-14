from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ciscoautoflash.config import SessionPaths, WorkflowTiming
from ciscoautoflash.core.events import AppEvent
from ciscoautoflash.core.logging_utils import append_transcript_line
from ciscoautoflash.core.models import ConnectionTarget, ScanResult
from ciscoautoflash.core.state import WorkflowState
from ciscoautoflash.core.transport import Transport, TransportFactory, TransportType
from ciscoautoflash.core.workflow import WorkflowController
from ciscoautoflash.profiles import build_c2960x_profile


class ScriptedTransport(Transport):
    def __init__(
        self,
        *,
        read_until_results=None,
        read_available_chunks=None,
        command_outputs=None,
        default_output="",
        transcript_path: Path | None = None,
    ):
        self.read_until_results = list(read_until_results or [])
        self.read_available_chunks = list(read_available_chunks or [])
        self.command_outputs = {
            key: (list(value) if isinstance(value, list) else [value])
            for key, value in (command_outputs or {}).items()
        }
        self.default_output = default_output
        self.transcript_path = transcript_path
        self.connected = False
        self.interrupted = False
        self.writes: list[str] = []

    def _transcript(self, direction: str, payload: str) -> None:
        if self.transcript_path is not None and payload:
            append_transcript_line(self.transcript_path, direction, payload)

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def write(self, data: str) -> None:
        self.writes.append(data)
        self._transcript("WRITE", data if data else "<ENTER>")

    def read_available(self) -> str:
        if self.read_available_chunks:
            chunk = self.read_available_chunks.pop(0)
            self._transcript("READ", chunk)
            return chunk
        return ""

    def read_until(self, markers, timeout: float) -> tuple[str | None, str]:
        if self.read_until_results:
            result = self.read_until_results.pop(0)
            self._transcript("READ", result[1])
            return result
        return None, ""

    def send_command(self, command: str, wait: float = 1.0) -> str:
        self.writes.append(command)
        self._transcript("WRITE", command)
        if command in self.command_outputs and self.command_outputs[command]:
            output = self.command_outputs[command].pop(0)
            self._transcript("READ", output)
            return output
        for key, values in self.command_outputs.items():
            if key.endswith("*") and command.startswith(key[:-1]) and values:
                output = values.pop(0)
                self._transcript("READ", output)
                return output
        if callable(self.default_output):
            output = self.default_output(command)
            self._transcript("READ", output)
            return output
        self._transcript("READ", self.default_output)
        return self.default_output

    def interrupt(self) -> None:
        self.interrupted = True

    def is_connected(self) -> bool:
        return self.connected

    def reset_interrupt(self) -> None:
        self.interrupted = False


class DisconnectAfterReloadTransport(ScriptedTransport):
    def send_command(self, command: str, wait: float = 1.0) -> str:
        output = super().send_command(command, wait=wait)
        if command == "reload":
            self.connected = False
        return output


class ScriptedFactory(TransportFactory):
    transport_type = TransportType.SERIAL

    def __init__(self, targets, probe_results, transports):
        self.targets = list(targets)
        self.probe_results = {result.target.id: result for result in probe_results}
        self.transports = list(transports)

    def list_targets(self):
        return list(self.targets)

    def probe(self, target, markers, timeout: float):
        return self.probe_results[target.id]

    def create(self, target):
        if not self.transports:
            raise AssertionError("No scripted transport left for create()")
        return self.transports.pop(0)


class WorkflowControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = build_c2960x_profile()
        self.events: list[AppEvent] = []
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        logs_dir = root / "logs"
        reports_dir = root / "reports"
        transcripts_dir = root / "transcripts"
        for directory in (logs_dir, reports_dir, transcripts_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.session = SessionPaths(
            base_dir=root,
            logs_dir=logs_dir,
            reports_dir=reports_dir,
            transcripts_dir=transcripts_dir,
            session_id="test",
            log_path=logs_dir / "session.log",
            report_path=reports_dir / "report.txt",
            transcript_path=transcripts_dir / "transcript.log",
            settings_path=root / "settings.json",
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def make_controller(
        self, factory: ScriptedFactory, timing: WorkflowTiming | None = None
    ) -> WorkflowController:
        controller = WorkflowController(
            profile=self.profile,
            transport_factory=factory,
            session=self.session,
            event_handler=self.events.append,
            timing=timing
            or WorkflowTiming(
                command_wait_short=0.0,
                command_wait_medium=0.0,
                command_wait_long=0.0,
                stage1_prompt_timeout=0.1,
                stage2_prompt_timeout=0.1,
            ),
        )
        controller.initialize()
        return controller

    def test_stage1_success_sets_stage1_complete(self) -> None:
        target = ConnectionTarget("COM5", "COM5", {"description": "USB Serial"})
        transport = ScriptedTransport(
            read_until_results=[
                ("Switch#", "Switch#"),
                ("[confirm]", "[confirm]"),
                ("Switch#", "Switch#"),
            ],
            command_outputs={
                "show startup-config": "startup-config is not present",
                "dir flash:": "Directory of flash:/\n2  -rw-  100 config.text",
                "reload": "",
            },
        )
        factory = ScriptedFactory(
            [target], [ScanResult(target, True, "ready", "priv")], [transport]
        )
        controller = self.make_controller(factory)
        controller.selected_target = target

        controller.run_stage1(background=False)

        self.assertTrue(controller.stage1_complete)
        self.assertEqual(controller.state, WorkflowState.DONE)

    def test_stage1_handles_config_dialog_after_reboot(self) -> None:
        target = ConnectionTarget("COM5", "COM5", {"description": "USB Serial"})
        transport = ScriptedTransport(
            read_until_results=[
                ("Switch#", "Switch#"),
                ("[confirm]", "[confirm]"),
                (None, "Would you like to enter the initial configuration dialog? [yes/no]:"),
                ("Switch#", "Switch#"),
            ],
            command_outputs={
                "show startup-config": "startup-config is not present",
                "dir flash:": "Directory of flash:/\n2  -rw-  100 config.text",
                "reload": "",
            },
        )
        factory = ScriptedFactory(
            [target], [ScanResult(target, True, "ready", "priv")], [transport]
        )
        controller = self.make_controller(factory)
        controller.selected_target = target

        controller.run_stage1(background=False)

        self.assertIn("no", transport.writes)
        self.assertTrue(controller.stage1_complete)

    def test_stage1_reconnects_after_reload_if_transport_drops(self) -> None:
        target = ConnectionTarget("COM5", "COM5", {"description": "USB Serial"})
        first = DisconnectAfterReloadTransport(
            read_until_results=[("Switch#", "Switch#"), ("[confirm]", "[confirm]")],
            command_outputs={
                "show startup-config": "startup-config is not present",
                "dir flash:": "Directory of flash:/\n2  -rw-  100 config.text",
                "reload": "",
            },
        )
        second = ScriptedTransport(read_until_results=[("Switch#", "Switch#")])
        factory = ScriptedFactory(
            [target],
            [ScanResult(target, True, "ready", "priv")],
            [first, second],
        )
        controller = self.make_controller(factory)
        controller.selected_target = target

        controller.run_stage1(background=False)

        self.assertTrue(controller.stage1_complete)
        self.assertFalse(first.connected)
        self.assertFalse(second.read_until_results)

    def test_stage1_writes_transcript(self) -> None:
        target = ConnectionTarget("COM5", "COM5", {"description": "USB Serial"})
        transport = ScriptedTransport(
            read_until_results=[
                ("Switch#", "Switch#"),
                ("[confirm]", "[confirm]"),
                ("Switch#", "Switch#"),
            ],
            command_outputs={
                "show startup-config": "startup-config is not present",
                "dir flash:": "Directory of flash:/\n2  -rw-  100 config.text",
                "reload": "",
            },
            transcript_path=self.session.transcript_path,
        )
        factory = ScriptedFactory(
            [target], [ScanResult(target, True, "ready", "priv")], [transport]
        )
        controller = self.make_controller(factory)
        controller.selected_target = target

        controller.run_stage1(background=False)

        transcript = self.session.transcript_path.read_text(encoding="utf-8")
        self.assertIn("show startup-config", transcript)
        self.assertIn("reload", transcript)

    def test_stage2_falls_back_to_usbflash1(self) -> None:
        target = ConnectionTarget("COM5", "COM5", {"description": "USB Serial"})
        transport = ScriptedTransport(
            read_until_results=[("Switch#", "Switch#"), ("Switch#", "Switch#")],
            read_available_chunks=[
                (
                    "examining\nextracting\ninstalling\ndeleting\n"
                    "signature\nall software images installed\n"
                )
            ],
            command_outputs={
                "show flash:": "123456789 bytes total (98765432 bytes free)",
                "dir usbflash0:": "Directory of usbflash0:/\n",
                "dir usbflash1:": (
                    "Directory of usbflash1:/\n1  -rw-  c2960x-universalk9-tar.152-7.E13.tar"
                ),
            },
        )
        factory = ScriptedFactory(
            [target], [ScanResult(target, True, "ready", "priv")], [transport]
        )
        controller = self.make_controller(factory)
        controller.selected_target = target
        controller.stage1_complete = True

        controller.run_stage2(self.profile.default_firmware, background=False)

        self.assertTrue(controller.stage2_complete)
        self.assertTrue(controller.install_status.extracting)
        self.assertTrue(any("usbflash1:" in write for write in transport.writes))

    def test_stage2_quiet_install_success_sets_complete(self) -> None:
        target = ConnectionTarget("COM5", "COM5", {"description": "USB Serial"})
        timing = WorkflowTiming(
            command_wait_short=0.0,
            command_wait_medium=0.0,
            command_wait_long=0.0,
            install_timeout=0.2,
            install_quiet_success=0.0,
            stage2_prompt_timeout=0.1,
        )
        transport = ScriptedTransport(
            read_until_results=[("Switch#", "Switch#"), ("Switch#", "Switch#")],
            read_available_chunks=["installing\n"],
            command_outputs={
                "show flash:": "123456789 bytes total (98765432 bytes free)",
                "dir usbflash0:": (
                    "Directory of usbflash0:/\n1  -rw-  c2960x-universalk9-tar.152-7.E13.tar"
                ),
            },
        )
        factory = ScriptedFactory(
            [target], [ScanResult(target, True, "ready", "priv")], [transport]
        )
        controller = self.make_controller(factory, timing=timing)
        controller.selected_target = target
        controller.stage1_complete = True

        controller.run_stage2(self.profile.default_firmware, background=False)

        self.assertTrue(controller.stage2_complete)
        self.assertTrue(controller.install_status.installing)

    def test_stage2_timeout_sets_failed_state(self) -> None:
        target = ConnectionTarget("COM5", "COM5", {"description": "USB Serial"})
        timing = WorkflowTiming(
            command_wait_short=0.0,
            command_wait_medium=0.0,
            command_wait_long=0.0,
            install_timeout=0.01,
            stage2_prompt_timeout=0.01,
        )
        transport = ScriptedTransport(
            read_until_results=[("Switch#", "Switch#")],
            command_outputs={
                "show flash:": "123456789 bytes total (98765432 bytes free)",
                "dir usbflash0:": (
                    "Directory of usbflash0:/\n1  -rw-  c2960x-universalk9-tar.152-7.E13.tar"
                ),
            },
        )
        factory = ScriptedFactory(
            [target],
            [ScanResult(target, True, "ready", "priv")],
            [transport],
        )
        controller = self.make_controller(factory, timing=timing)
        controller.selected_target = target
        controller.stage1_complete = True

        controller.run_stage2(self.profile.default_firmware, background=False)

        self.assertEqual(controller.state, WorkflowState.FAILED)
        self.assertFalse(controller.stage2_complete)

    def test_stage2_writes_transcript(self) -> None:
        target = ConnectionTarget("COM5", "COM5", {"description": "USB Serial"})
        transport = ScriptedTransport(
            read_until_results=[("Switch#", "Switch#"), ("Switch#", "Switch#")],
            read_available_chunks=[
                (
                    "examining\nextracting\ninstalling\ndeleting\n"
                    "signature\nall software images installed\n"
                )
            ],
            command_outputs={
                "show flash:": "123456789 bytes total (98765432 bytes free)",
                "dir usbflash0:": (
                    "Directory of usbflash0:/\n1  -rw-  c2960x-universalk9-tar.152-7.E13.tar"
                ),
            },
            transcript_path=self.session.transcript_path,
        )
        factory = ScriptedFactory(
            [target], [ScanResult(target, True, "ready", "priv")], [transport]
        )
        controller = self.make_controller(factory)
        controller.selected_target = target
        controller.stage1_complete = True

        controller.run_stage2(self.profile.default_firmware, background=False)

        transcript = self.session.transcript_path.read_text(encoding="utf-8")
        self.assertIn("archive download-sw /overwrite /reload usbflash0:", transcript)

    def test_stage3_generates_report(self) -> None:
        target = ConnectionTarget("COM5", "COM5", {"description": "USB Serial"})
        transport = ScriptedTransport(
            read_until_results=[("Switch#", "Switch#")],
            command_outputs={
                "terminal length 0": "",
                "show version": (
                    "Cisco IOS Software, Version 15.2(7)E13\n"
                    'System image file is "flash:/image.bin"\n'
                    "Model Number                    : WS-C2960X-48FPS-L\n"
                ),
                "show boot": "BOOT variable = flash:/image.bin",
                "dir flash:": "123456789 bytes total (98765432 bytes free)",
            },
            default_output=lambda command: f"output for {command}",
        )
        factory = ScriptedFactory(
            [target],
            [ScanResult(target, True, "ready", "priv")],
            [transport],
        )
        controller = self.make_controller(factory)
        controller.selected_target = target

        controller.run_stage3(background=False)

        self.assertEqual(controller.state, WorkflowState.DONE)
        self.assertTrue(self.session.report_path.exists())

    def test_stage3_writes_transcript(self) -> None:
        target = ConnectionTarget("COM5", "COM5", {"description": "USB Serial"})
        transport = ScriptedTransport(
            read_until_results=[("Switch#", "Switch#")],
            command_outputs={
                "terminal length 0": "",
                "show version": (
                    "Cisco IOS Software, Version 15.2(7)E13\n"
                    'System image file is "flash:/image.bin"\n'
                    "Model Number                    : WS-C2960X-48FPS-L\n"
                ),
                "show boot": "BOOT variable = flash:/image.bin",
                "dir flash:": "123456789 bytes total (98765432 bytes free)",
            },
            default_output=lambda command: f"output for {command}",
            transcript_path=self.session.transcript_path,
        )
        factory = ScriptedFactory(
            [target],
            [ScanResult(target, True, "ready", "priv")],
            [transport],
        )
        controller = self.make_controller(factory)
        controller.selected_target = target

        controller.run_stage3(background=False)

        transcript = self.session.transcript_path.read_text(encoding="utf-8")
        self.assertIn("show version", transcript)
        self.assertIn("show boot", transcript)
        self.assertIn("dir flash:", transcript)


if __name__ == "__main__":
    unittest.main()
