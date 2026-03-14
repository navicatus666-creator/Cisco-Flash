from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ciscoautoflash.config import WorkflowTiming
from ciscoautoflash.core.models import ConnectionTarget
from ciscoautoflash.core.serial_transport import SerialTransportFactory, _PortLeaseRegistry


class SerialTransportFactoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.factory = SerialTransportFactory(WorkflowTiming())
        self.target = ConnectionTarget("COM5", "COM5", {"description": "USB Serial"})

    def test_list_targets_sorts_by_heuristic_score(self) -> None:
        ports = [
            SimpleNamespace(device="COM2", description="Bluetooth Link", manufacturer="Microsoft"),
            SimpleNamespace(device="COM7", description="USB Serial Port", manufacturer="FTDI"),
            SimpleNamespace(device="COM3", description="Standard COM Port", manufacturer="Unknown"),
        ]

        with patch(
            "ciscoautoflash.core.serial_transport.serial.tools.list_ports.comports",
            return_value=ports,
        ):
            targets = self.factory.list_targets()

        self.assertEqual([target.id for target in targets], ["COM7", "COM3", "COM2"])
        self.assertGreater(
            targets[0].metadata["heuristic_score"], targets[-1].metadata["heuristic_score"]
        )

    def test_probe_reports_port_busy_when_lease_is_held(self) -> None:
        owner = object()
        acquired = _PortLeaseRegistry.acquire(self.target.id, owner)
        self.assertTrue(acquired)
        try:
            result = self.factory.probe(
                self.target, ("Switch#", "Switch>", "switch:"), timeout=0.01
            )
        finally:
            _PortLeaseRegistry.release(self.target.id, owner)

        self.assertFalse(result.available)
        self.assertEqual(result.connection_state, "busy")
        self.assertEqual(result.error_code, "port_busy")

    def test_classify_buffer_detects_ready_prompt_in_noisy_output(self) -> None:
        buffer = "Booting...\nrandom text\nCisco IOS Software, Version 15.2(7)E13\nSwitch#"

        result = self.factory._classify_buffer(self.target, buffer)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.available)
        self.assertEqual(result.prompt_type, "priv")
        self.assertEqual(result.connection_state, "ready")
        self.assertEqual(result.version, "15.2(7)E13")

    def test_classify_buffer_detects_rommon(self) -> None:
        result = self.factory._classify_buffer(self.target, "switch:")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.prompt_type, "rommon")
        self.assertEqual(result.connection_state, "rommon")
        self.assertEqual(result.error_code, "rommon")

    def test_classify_buffer_detects_config_dialog(self) -> None:
        result = self.factory._classify_buffer(
            self.target,
            "Would you like to enter the initial configuration dialog? [yes/no]:",
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.prompt_type, "config_dialog")
        self.assertEqual(result.connection_state, "config_dialog")
        self.assertEqual(result.error_code, "config_dialog")

    def test_classify_buffer_detects_press_return(self) -> None:
        result = self.factory._classify_buffer(self.target, "Press RETURN to get started")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.prompt_type, "press_return")
        self.assertEqual(result.connection_state, "press_return")
        self.assertEqual(result.error_code, "press_return")

    def test_classify_buffer_detects_login_required(self) -> None:
        result = self.factory._classify_buffer(self.target, "User Access Verification\nUsername:")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.prompt_type, "login")
        self.assertEqual(result.connection_state, "login_required")
        self.assertEqual(result.error_code, "login_required")

    def test_classify_buffer_detects_partial_prompt(self) -> None:
        result = self.factory._classify_buffer(self.target, "switch   ")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.prompt_type, "unknown")
        self.assertEqual(result.connection_state, "partial_prompt")
        self.assertEqual(result.error_code, "partial_prompt")


if __name__ == "__main__":
    unittest.main()
