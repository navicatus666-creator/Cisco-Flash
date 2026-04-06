from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from types import SimpleNamespace
from unittest.mock import patch

from ciscoautoflash.devtools import hardware_day


class HardwareDayTests(unittest.TestCase):
    def test_hidden_subprocess_kwargs_uses_no_window_on_windows(self) -> None:
        with patch("ciscoautoflash.devtools.hardware_day.sys.platform", "win32"):
            kwargs = hardware_day._hidden_subprocess_kwargs()

        self.assertIn("startupinfo", kwargs)
        self.assertIn("creationflags", kwargs)

    def test_build_connection_snapshot_collects_console_and_network(self) -> None:
        ports = [
            SimpleNamespace(
                device="COM7",
                description="USB Serial Port",
                manufacturer="Cisco",
                product="Console",
                hwid="USB VID:PID=1234",
                vid=1,
                pid=2,
                serial_number="abc",
                location="Port_1",
            ),
            SimpleNamespace(
                device="COM8",
                description="UART Bridge",
                manufacturer="Acme",
                product="Bridge",
                hwid="PCI",
                vid=None,
                pid=None,
                serial_number="",
                location="PCIROOT",
            ),
        ]
        adapter_stdout = json.dumps(
            [
                {
                    "Name": "Ethernet",
                    "InterfaceDescription": "Intel(R) Ethernet Connection",
                    "Status": "Up",
                    "MacAddress": "00-11",
                    "LinkSpeed": "1 Gbps",
                    "MediaType": "802.3",
                },
                {
                    "Name": "Wi-Fi",
                    "InterfaceDescription": "Intel(R) Wireless",
                    "Status": "Up",
                    "MacAddress": "00-22",
                    "LinkSpeed": "300 Mbps",
                    "MediaType": "Native 802.11",
                },
            ]
        )

        with (
            patch("ciscoautoflash.devtools.hardware_day.sys.platform", "win32"),
            patch(
                "ciscoautoflash.devtools.hardware_day.list_ports.comports",
                return_value=ports,
            ),
            patch(
                "ciscoautoflash.devtools.hardware_day.subprocess.run",
                return_value=CompletedProcess(
                    args=["powershell"],
                    returncode=0,
                    stdout=adapter_stdout,
                    stderr="",
                ),
            ),
        ):
            snapshot = hardware_day.build_connection_snapshot()

        self.assertTrue(snapshot["console"]["ready"])
        self.assertEqual(snapshot["console"]["recommended_primary"], "COM7")
        self.assertEqual(snapshot["network"]["ethernet_up"], ["Ethernet"])

    def test_assess_hardware_day_readiness_requires_green_gate_and_console(self) -> None:
        snapshot = {
            "console": {"ready": False, "recommended_primary": "", "items": []},
            "network": {"ethernet_up": []},
            "ping": {"attempted": False},
            "ssh_probe": {"attempted": False},
        }

        result = hardware_day.assess_hardware_day_readiness(
            preflight_status="READY",
            snapshot=snapshot,
        )

        self.assertEqual(result["status"], "NOT_READY")
        self.assertTrue(
            any("console path" in step for step in result["next_steps"])
        )

    def test_load_latest_preflight_summary_picks_newest_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            build_root = Path(temp_dir)
            older_dir = build_root / "20260401_010000"
            newer_dir = build_root / "20260401_020000"
            older_dir.mkdir(parents=True)
            newer_dir.mkdir(parents=True)
            (older_dir / "preflight_summary.json").write_text(
                json.dumps({"status": "NOT_READY"}),
                encoding="utf-8",
            )
            newer_file = newer_dir / "preflight_summary.json"
            newer_file.write_text(
                json.dumps({"status": "READY"}),
                encoding="utf-8",
            )
            os.utime(older_dir / "preflight_summary.json", (1, 1))
            os.utime(newer_file, (2, 2))

            latest = hardware_day.load_latest_preflight_summary(build_root)

        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest["status"], "READY")

    def test_load_operator_preflight_summary_prefers_runtime_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            runtime_root = temp_root / "runtime"
            project_root = temp_root / "project"
            runtime_paths = hardware_day.resolve_runtime_preflight_paths(
                "20260402_222644",
                runtime_root=runtime_root,
            )
            runtime_paths["output_dir"].mkdir(parents=True)
            runtime_paths["latest_summary_json"].write_text(
                json.dumps({"status": "READY", "source": "runtime"}),
                encoding="utf-8",
            )
            repo_dir = project_root / "build" / "preflight" / "20260401_010000"
            repo_dir.mkdir(parents=True)
            (repo_dir / "preflight_summary.json").write_text(
                json.dumps({"status": "NOT_READY", "source": "repo"}),
                encoding="utf-8",
            )

            latest = hardware_day.load_operator_preflight_summary(
                runtime_root=runtime_root,
                project_root=project_root,
            )

        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest["source"], "runtime")


if __name__ == "__main__":
    unittest.main()
