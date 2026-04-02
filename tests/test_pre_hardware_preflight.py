from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from scripts import pre_hardware_preflight


class PreHardwarePreflightTests(unittest.TestCase):
    def test_main_writes_ready_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            step_outputs = [
                CompletedProcess(args=["check"], returncode=0, stdout="mcp ok\n", stderr=""),
                CompletedProcess(args=["tests"], returncode=0, stdout="tests ok\n", stderr=""),
                CompletedProcess(args=["build"], returncode=0, stdout="build ok\n", stderr=""),
                CompletedProcess(args=["smoke"], returncode=0, stdout="smoke ok\n", stderr=""),
            ]

            with (
                patch.object(pre_hardware_preflight, "PROJECT_ROOT", output_root),
                patch.object(
                    pre_hardware_preflight,
                    "BUILD_ROOT",
                    output_root / "build" / "preflight",
                ),
                patch(
                    "scripts.pre_hardware_preflight.subprocess.run",
                    side_effect=step_outputs,
                ),
                patch.dict("os.environ", {"LOCALAPPDATA": str(output_root / "localappdata")}),
                patch(
                    "scripts.pre_hardware_preflight._load_hardware_day_helpers",
                    return_value=(
                        lambda **_: {"status": "NOT_READY", "next_steps": []},
                        lambda **_: {},
                        lambda _: {},
                        pre_hardware_preflight._load_hardware_day_helpers()[3],
                    ),
                ),
            ):
                exit_code = pre_hardware_preflight.main([])

            self.assertEqual(exit_code, 0)
            summary_files = list(
                (output_root / "build" / "preflight").rglob(
                    "preflight_summary.json"
                )
            )
            self.assertEqual(len(summary_files), 1)
            summary = json.loads(summary_files[0].read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "READY")
            self.assertEqual(len(summary["steps"]), 4)
            self.assertEqual(summary["failing_step"], "")
            self.assertTrue(Path(summary["artifacts"]["runtime_summary_json"]).exists())
            self.assertTrue(Path(summary["artifacts"]["runtime_summary_md"]).exists())
            self.assertTrue(Path(summary["artifacts"]["runtime_latest_summary_json"]).exists())

    def test_main_stops_on_first_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            step_outputs = [
                CompletedProcess(args=["check"], returncode=0, stdout="mcp ok\n", stderr=""),
                CompletedProcess(
                    args=["tests"],
                    returncode=1,
                    stdout="tests bad\n",
                    stderr="boom\n",
                ),
            ]

            with (
                patch.object(pre_hardware_preflight, "PROJECT_ROOT", output_root),
                patch.object(
                    pre_hardware_preflight,
                    "BUILD_ROOT",
                    output_root / "build" / "preflight",
                ),
                patch(
                    "scripts.pre_hardware_preflight.subprocess.run",
                    side_effect=step_outputs,
                ),
                patch.dict("os.environ", {"LOCALAPPDATA": str(output_root / "localappdata")}),
                patch(
                    "scripts.pre_hardware_preflight._load_hardware_day_helpers",
                    return_value=(
                        lambda **_: {"status": "NOT_READY", "next_steps": []},
                        lambda **_: {},
                        lambda _: {},
                        pre_hardware_preflight._load_hardware_day_helpers()[3],
                    ),
                ),
            ):
                exit_code = pre_hardware_preflight.main([])

            self.assertEqual(exit_code, 1)
            summary_files = list(
                (output_root / "build" / "preflight").rglob(
                    "preflight_summary.json"
                )
            )
            self.assertEqual(len(summary_files), 1)
            summary = json.loads(summary_files[0].read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "NOT_READY")
            self.assertEqual(summary["failing_step"], "unittest")

    def test_main_hardware_day_rehearsal_writes_ready_for_hardware_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            step_outputs = [
                CompletedProcess(args=["check"], returncode=0, stdout="mcp ok\n", stderr=""),
                CompletedProcess(args=["tests"], returncode=0, stdout="tests ok\n", stderr=""),
                CompletedProcess(args=["build"], returncode=0, stdout="build ok\n", stderr=""),
                CompletedProcess(args=["smoke"], returncode=0, stdout="smoke ok\n", stderr=""),
            ]
            snapshot = {
                "console": {"ready": True, "items": [{"device": "COM7"}]},
                "network": {"ethernet_up": ["Ethernet"]},
                "ping": {"attempted": False},
                "ssh_probe": {"attempted": False},
            }
            describe_result = {
                "console": "COM7",
                "ethernet": "Ethernet up",
                "ssh": "not checked",
                "live_run_path": "console -> scan -> stage1 -> stage2 -> stage3 -> bundle",
                "return_path": (
                    "session bundle -> session folder -> "
                    "triage_session_return.py"
                ),
            }
            readiness_result = {
                "status": "READY_FOR_HARDWARE",
                "next_steps": ["Можно идти в serial-first live run."],
            }

            with (
                patch.object(pre_hardware_preflight, "PROJECT_ROOT", output_root),
                patch.object(
                    pre_hardware_preflight,
                    "BUILD_ROOT",
                    output_root / "build" / "preflight",
                ),
                patch(
                    "scripts.pre_hardware_preflight.subprocess.run",
                    side_effect=step_outputs,
                ),
                patch(
                    "scripts.pre_hardware_preflight._load_hardware_day_helpers",
                    return_value=(
                        lambda **_: readiness_result,
                        lambda **_: snapshot,
                        lambda _: describe_result,
                        pre_hardware_preflight._load_hardware_day_helpers()[3],
                    ),
                ),
                patch.dict("os.environ", {"LOCALAPPDATA": str(output_root / "localappdata")}),
            ):
                exit_code = pre_hardware_preflight.main(["--hardware-day-rehearsal"])

            self.assertEqual(exit_code, 0)
            summary_files = list(
                (output_root / "build" / "preflight").rglob("preflight_summary.json")
            )
            self.assertEqual(len(summary_files), 1)
            summary = json.loads(summary_files[0].read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "READY")
            self.assertEqual(summary["hardware_day_status"], "READY_FOR_HARDWARE")
            self.assertTrue(
                Path(summary["artifacts"]["connection_snapshot_json"]).exists()
            )
            self.assertTrue(Path(summary["artifacts"]["runtime_latest_summary_json"]).exists())

    def test_main_hardware_day_rehearsal_reports_not_ready_without_console(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            step_outputs = [
                CompletedProcess(args=["check"], returncode=0, stdout="mcp ok\n", stderr=""),
                CompletedProcess(args=["tests"], returncode=0, stdout="tests ok\n", stderr=""),
                CompletedProcess(args=["build"], returncode=0, stdout="build ok\n", stderr=""),
                CompletedProcess(args=["smoke"], returncode=0, stdout="smoke ok\n", stderr=""),
            ]
            snapshot = {
                "console": {"ready": False, "items": []},
                "network": {"ethernet_up": []},
                "ping": {"attempted": False},
                "ssh_probe": {"attempted": False},
            }
            describe_result = {
                "console": "COM не видны",
                "ethernet": "Ethernet down",
                "ssh": "not checked",
                "live_run_path": "console -> scan -> stage1 -> stage2 -> stage3 -> bundle",
                "return_path": (
                    "session bundle -> session folder -> "
                    "triage_session_return.py"
                ),
            }
            readiness_result = {
                "status": "NOT_READY",
                "next_steps": ["Подключите основной console path."],
            }

            with (
                patch.object(pre_hardware_preflight, "PROJECT_ROOT", output_root),
                patch.object(
                    pre_hardware_preflight,
                    "BUILD_ROOT",
                    output_root / "build" / "preflight",
                ),
                patch(
                    "scripts.pre_hardware_preflight.subprocess.run",
                    side_effect=step_outputs,
                ),
                patch(
                    "scripts.pre_hardware_preflight._load_hardware_day_helpers",
                    return_value=(
                        lambda **_: readiness_result,
                        lambda **_: snapshot,
                        lambda _: describe_result,
                        pre_hardware_preflight._load_hardware_day_helpers()[3],
                    ),
                ),
                patch.dict("os.environ", {"LOCALAPPDATA": str(output_root / "localappdata")}),
            ):
                exit_code = pre_hardware_preflight.main(["--hardware-day-rehearsal"])

            self.assertEqual(exit_code, 1)
            summary_files = list(
                (output_root / "build" / "preflight").rglob("preflight_summary.json")
            )
            summary = json.loads(summary_files[0].read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "READY")
            self.assertEqual(summary["hardware_day_status"], "NOT_READY")


if __name__ == "__main__":
    unittest.main()
