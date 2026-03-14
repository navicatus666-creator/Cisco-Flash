from __future__ import annotations

import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest.mock import Mock, patch

from ciscoautoflash.config import AppConfig, WorkflowTiming
from ciscoautoflash.core.models import ConnectionTarget
from ciscoautoflash.core.ssh_transport import SshTransport, SshTransportFactory
from ciscoautoflash.core.transport import TransportError
from ciscoautoflash.core.workflow import WorkflowController
from ciscoautoflash.profiles import build_c2960x_profile


class FakeAuthError(Exception):
    pass


class FakeTimeoutError(Exception):
    pass


class FakeConnection:
    def __init__(
        self,
        prompt: str = "Switch#",
        read_chunks: list[str] | None = None,
        *,
        command_outputs: dict[str, str] | None = None,
        default_output: Callable[[str], str] | str | None = None,
        send_error: Exception | None = None,
    ) -> None:
        self.prompt = prompt
        self.read_chunks = list(read_chunks or [])
        self.command_outputs = dict(command_outputs or {})
        self.default_output = default_output
        self.send_error = send_error
        self.writes: list[str] = []
        self.commands: list[tuple[str, float, float]] = []
        self.disconnected = False

    def disconnect(self) -> None:
        self.disconnected = True

    def write_channel(self, payload: str) -> None:
        self.writes.append(payload)

    def read_channel(self) -> str:
        if self.read_chunks:
            return self.read_chunks.pop(0)
        return ""

    def send_command_timing(
        self,
        command: str,
        *,
        last_read: float,
        read_timeout: float,
        strip_prompt: bool,
        strip_command: bool,
    ) -> str:
        self.commands.append((command, last_read, read_timeout))
        if self.send_error is not None:
            raise self.send_error
        if command in self.command_outputs:
            return self.command_outputs[command]
        if callable(self.default_output):
            return self.default_output(command)
        if isinstance(self.default_output, str):
            return self.default_output
        return f"output for {command}"

    def find_prompt(self) -> str:
        return self.prompt

    def is_alive(self):
        return True


class SshTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.target = ConnectionTarget(
            id="sw1",
            label="sw1",
            metadata={
                "host": "10.0.0.10",
                "username": "admin",
                "password": "secret",
                "secret": "enable",
                "device_type": "cisco_ios",
            },
        )
        self.timing = WorkflowTiming(prompt_timeout=5.0, enable_timeout=3.0)
        self.tempdir = tempfile.TemporaryDirectory()
        self.transcript_path = Path(self.tempdir.name) / "ssh-transcript.log"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_connect_send_command_and_disconnect(self) -> None:
        connection = FakeConnection(read_chunks=["booting\n", "Switch#"])
        connect_handler = Mock(return_value=connection)
        with patch(
            "ciscoautoflash.core.ssh_transport._load_netmiko",
            return_value=(connect_handler, Mock(), FakeAuthError, FakeTimeoutError),
        ):
            transport = SshTransport(self.target, self.timing, self.transcript_path)
            transport.connect()
            transport.write("terminal length 0")
            marker, buffer = transport.read_until(["Switch#"], timeout=0.5)
            output = transport.send_command("show version", wait=0.2)
            transport.disconnect()

        connect_handler.assert_called_once()
        self.assertEqual(marker, "Switch#")
        self.assertIn("booting", buffer)
        self.assertEqual(output, "output for show version")
        self.assertIn("terminal length 0\n", connection.writes)
        self.assertTrue(connection.disconnected)
        self.assertTrue(self.transcript_path.exists())

    def test_upload_file_uses_netmiko_file_transfer(self) -> None:
        connection = FakeConnection()
        transfer = Mock(return_value={"file_verified": True, "file_transferred": True})
        with patch(
            "ciscoautoflash.core.ssh_transport._load_netmiko",
            return_value=(Mock(return_value=connection), transfer, FakeAuthError, FakeTimeoutError),
        ):
            transport = SshTransport(self.target, self.timing)
            transport.connect()
            result = transport.upload_file("firmware.tar")

        self.assertTrue(result["file_verified"])
        transfer.assert_called_once()
        _, kwargs = transfer.call_args
        self.assertEqual(kwargs["file_system"], "flash:")
        self.assertEqual(kwargs["dest_file"], "firmware.tar")

    def test_upload_file_uses_target_default_file_system(self) -> None:
        target = ConnectionTarget(
            id="sw-bootflash",
            label="sw-bootflash",
            metadata={**self.target.metadata, "file_system": "bootflash:"},
        )
        connection = FakeConnection()
        transfer = Mock(return_value={"file_verified": True, "file_transferred": True})
        with patch(
            "ciscoautoflash.core.ssh_transport._load_netmiko",
            return_value=(Mock(return_value=connection), transfer, FakeAuthError, FakeTimeoutError),
        ):
            transport = SshTransport(target, self.timing)
            transport.connect()
            transport.upload_file("firmware.tar")

        _, kwargs = transfer.call_args
        self.assertEqual(kwargs["file_system"], "bootflash:")

    def test_upload_file_raises_transport_error_on_failure(self) -> None:
        connection = FakeConnection()
        transfer = Mock(side_effect=RuntimeError("copy failed"))
        with patch(
            "ciscoautoflash.core.ssh_transport._load_netmiko",
            return_value=(Mock(return_value=connection), transfer, FakeAuthError, FakeTimeoutError),
        ):
            transport = SshTransport(self.target, self.timing)
            transport.connect()
            with self.assertRaisesRegex(TransportError, "SSH file upload failed"):
                transport.upload_file("firmware.tar")

    def test_transcript_records_connect_write_read_and_scp(self) -> None:
        connection = FakeConnection(read_chunks=["Switch#"])
        transfer = Mock(return_value={"file_verified": True, "file_transferred": True})
        with patch(
            "ciscoautoflash.core.ssh_transport._load_netmiko",
            return_value=(Mock(return_value=connection), transfer, FakeAuthError, FakeTimeoutError),
        ):
            transport = SshTransport(self.target, self.timing, self.transcript_path)
            transport.connect()
            transport.write("")
            marker, _ = transport.read_until(["Switch#"], timeout=0.5)
            output = transport.send_command("show version", wait=0.2)
            transport.upload_file("firmware.tar")
            transport.disconnect()

        transcript = self.transcript_path.read_text(encoding="utf-8")
        self.assertEqual(marker, "Switch#")
        self.assertEqual(output, "output for show version")
        self.assertIn("| CONNECT", transcript)
        self.assertIn("| WRITE", transcript)
        self.assertIn("| READ", transcript)
        self.assertIn("| SCP", transcript)

    def test_factory_probe_detects_privileged_prompt(self) -> None:
        connection = FakeConnection(prompt="Switch#")
        connect_handler = Mock(return_value=connection)
        factory = SshTransportFactory(self.timing, [self.target])
        with patch(
            "ciscoautoflash.core.ssh_transport._load_netmiko",
            return_value=(connect_handler, Mock(), FakeAuthError, FakeTimeoutError),
        ):
            result = factory.probe(self.target, ("Switch#", "Switch>", "switch:"), timeout=1.0)

        self.assertTrue(result.available)
        self.assertEqual(result.prompt_type, "priv")
        self.assertEqual(result.connection_state, "ready")

    def test_factory_probe_detects_user_prompt(self) -> None:
        connection = FakeConnection(prompt="Switch>")
        connect_handler = Mock(return_value=connection)
        factory = SshTransportFactory(self.timing, [self.target])
        with patch(
            "ciscoautoflash.core.ssh_transport._load_netmiko",
            return_value=(connect_handler, Mock(), FakeAuthError, FakeTimeoutError),
        ):
            result = factory.probe(self.target, ("Switch#", "Switch>", "switch:"), timeout=1.0)

        self.assertTrue(result.available)
        self.assertEqual(result.prompt_type, "user")
        self.assertEqual(result.connection_state, "user_mode")

    def test_factory_probe_detects_rommon_prompt(self) -> None:
        connection = FakeConnection(prompt="switch:")
        connect_handler = Mock(return_value=connection)
        factory = SshTransportFactory(self.timing, [self.target])
        with patch(
            "ciscoautoflash.core.ssh_transport._load_netmiko",
            return_value=(connect_handler, Mock(), FakeAuthError, FakeTimeoutError),
        ):
            result = factory.probe(self.target, ("Switch#", "Switch>", "switch:"), timeout=1.0)

        self.assertFalse(result.available)
        self.assertEqual(result.prompt_type, "rommon")
        self.assertEqual(result.connection_state, "rommon")

    def test_factory_probe_detects_unknown_prompt(self) -> None:
        connection = FakeConnection(prompt="router$")
        connect_handler = Mock(return_value=connection)
        factory = SshTransportFactory(self.timing, [self.target])
        with patch(
            "ciscoautoflash.core.ssh_transport._load_netmiko",
            return_value=(connect_handler, Mock(), FakeAuthError, FakeTimeoutError),
        ):
            result = factory.probe(self.target, ("Switch#", "Switch>", "switch:"), timeout=1.0)

        self.assertFalse(result.available)
        self.assertEqual(result.prompt_type, "unknown")
        self.assertEqual(result.connection_state, "unknown_prompt")

    def test_factory_probe_maps_auth_failure_to_login_required(self) -> None:
        def boom(**kwargs):
            raise FakeAuthError("access denied")

        factory = SshTransportFactory(self.timing, [self.target])
        with patch(
            "ciscoautoflash.core.ssh_transport._load_netmiko",
            return_value=(boom, Mock(), FakeAuthError, FakeTimeoutError),
        ):
            result = factory.probe(self.target, ("Switch#", "Switch>", "switch:"), timeout=1.0)

        self.assertFalse(result.available)
        self.assertEqual(result.prompt_type, "login")
        self.assertEqual(result.connection_state, "login_required")

    def test_factory_probe_maps_timeout_to_timeout_state(self) -> None:
        def boom(**kwargs):
            raise FakeTimeoutError("timed out")

        factory = SshTransportFactory(self.timing, [self.target])
        with patch(
            "ciscoautoflash.core.ssh_transport._load_netmiko",
            return_value=(boom, Mock(), FakeAuthError, FakeTimeoutError),
        ):
            result = factory.probe(self.target, ("Switch#", "Switch>", "switch:"), timeout=1.0)

        self.assertFalse(result.available)
        self.assertEqual(result.connection_state, "timeout")
        self.assertEqual(result.error_code, "ssh_timeout")

    def test_connect_requires_ssh_dependencies_only_at_runtime(self) -> None:
        transport = SshTransport(self.target, self.timing)
        with patch(
            "ciscoautoflash.core.ssh_transport._load_netmiko",
            side_effect=TransportError("SSH dependencies are not installed."),
        ):
            with self.assertRaises(TransportError):
                transport.connect()

    def test_factory_probe_reports_missing_host(self) -> None:
        target = ConnectionTarget(
            id="sw-no-host",
            label="sw-no-host",
            metadata={"username": "admin", "password": "secret"},
        )
        factory = SshTransportFactory(self.timing, [target])
        result = factory.probe(target, ("Switch#", "Switch>", "switch:"), timeout=1.0)

        self.assertFalse(result.available)
        self.assertEqual(result.error_code, "missing_host")

    def test_factory_probe_reports_missing_credentials(self) -> None:
        target = ConnectionTarget(
            id="sw2",
            label="sw2",
            metadata={"host": "10.0.0.20"},
        )
        factory = SshTransportFactory(self.timing, [target])
        result = factory.probe(target, ("Switch#", "Switch>", "switch:"), timeout=1.0)
        self.assertFalse(result.available)
        self.assertEqual(result.connection_state, "login_required")


class SshWorkflowIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.target = ConnectionTarget(
            id="sw1",
            label="sw1",
            metadata={
                "host": "10.0.0.10",
                "username": "admin",
                "password": "secret",
                "secret": "enable",
                "device_type": "cisco_ios",
            },
        )
        self.timing = WorkflowTiming(
            command_wait_short=0.0,
            command_wait_medium=0.0,
            command_wait_long=0.0,
            prompt_timeout=0.1,
            enable_timeout=0.1,
            heartbeat_interval=0.01,
        )
        self.tempdir = tempfile.TemporaryDirectory()
        self.session = AppConfig(runtime_root=Path(self.tempdir.name)).create_session_paths()
        self.events = []

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def make_controller(self, factory: SshTransportFactory) -> WorkflowController:
        controller = WorkflowController(
            profile=build_c2960x_profile(),
            transport_factory=factory,
            session=self.session,
            event_handler=self.events.append,
            timing=self.timing,
        )
        controller.initialize()
        controller.selected_target = self.target
        return controller

    def make_stage3_connection(self, *, read_chunks: list[str]) -> FakeConnection:
        return FakeConnection(
            read_chunks=read_chunks,
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

    def test_workflow_stage3_over_ssh_generates_report_and_transcript(self) -> None:
        connection = self.make_stage3_connection(read_chunks=["Switch#"])
        factory = SshTransportFactory(
            self.timing,
            [self.target],
            transcript_path=self.session.transcript_path,
        )
        with patch(
            "ciscoautoflash.core.ssh_transport._load_netmiko",
            return_value=(Mock(return_value=connection), Mock(), FakeAuthError, FakeTimeoutError),
        ):
            controller = self.make_controller(factory)
            controller.run_stage3(background=False)

        transcript = self.session.transcript_path.read_text(encoding="utf-8")
        self.assertEqual(controller.state.value, "DONE")
        self.assertTrue(self.session.report_path.exists())
        self.assertIn("show version", transcript)
        self.assertIn("show inventory", transcript)
        self.assertTrue(any(event.kind == "report_ready" for event in self.events))

    def test_workflow_stage3_over_ssh_handles_user_prompt_and_enable(self) -> None:
        connection = self.make_stage3_connection(read_chunks=["Switch>", "Switch#"])
        factory = SshTransportFactory(
            self.timing,
            [self.target],
            transcript_path=self.session.transcript_path,
        )
        with patch(
            "ciscoautoflash.core.ssh_transport._load_netmiko",
            return_value=(Mock(return_value=connection), Mock(), FakeAuthError, FakeTimeoutError),
        ):
            controller = self.make_controller(factory)
            controller.run_stage3(background=False)

        self.assertEqual(controller.state.value, "DONE")
        self.assertTrue(any(payload.strip() == "enable" for payload in connection.writes))


if __name__ == "__main__":
    unittest.main()
