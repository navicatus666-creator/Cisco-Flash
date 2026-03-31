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
                patch.object(pre_hardware_preflight, "BUILD_ROOT", output_root / "build" / "preflight"),
                patch("scripts.pre_hardware_preflight.subprocess.run", side_effect=step_outputs),
            ):
                exit_code = pre_hardware_preflight.main([])

            self.assertEqual(exit_code, 0)
            summary_files = list((output_root / "build" / "preflight").rglob("preflight_summary.json"))
            self.assertEqual(len(summary_files), 1)
            summary = json.loads(summary_files[0].read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "READY")
            self.assertEqual(len(summary["steps"]), 4)
            self.assertEqual(summary["failing_step"], "")

    def test_main_stops_on_first_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            step_outputs = [
                CompletedProcess(args=["check"], returncode=0, stdout="mcp ok\n", stderr=""),
                CompletedProcess(args=["tests"], returncode=1, stdout="tests bad\n", stderr="boom\n"),
            ]

            with (
                patch.object(pre_hardware_preflight, "PROJECT_ROOT", output_root),
                patch.object(pre_hardware_preflight, "BUILD_ROOT", output_root / "build" / "preflight"),
                patch("scripts.pre_hardware_preflight.subprocess.run", side_effect=step_outputs),
            ):
                exit_code = pre_hardware_preflight.main([])

            self.assertEqual(exit_code, 1)
            summary_files = list((output_root / "build" / "preflight").rglob("preflight_summary.json"))
            self.assertEqual(len(summary_files), 1)
            summary = json.loads(summary_files[0].read_text(encoding="utf-8"))
            self.assertEqual(summary["status"], "NOT_READY")
            self.assertEqual(summary["failing_step"], "unittest")


if __name__ == "__main__":
    unittest.main()
