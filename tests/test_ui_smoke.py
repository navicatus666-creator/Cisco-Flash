from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from ciscoautoflash.devtools import ui_smoke


class UISmokeTests(unittest.TestCase):
    def test_build_command_includes_demo_scenario(self) -> None:
        command = ui_smoke.build_command(python_exe="python", demo_scenario="stage3_verify")
        self.assertIn("--demo", command)
        self.assertEqual(command[-2:], ["--demo-scenario", "stage3_verify"])

    def test_build_env_sets_smoke_flags(self) -> None:
        env = ui_smoke.build_env(close_ms=1800)
        self.assertEqual(env["CISCOAUTOFLASH_UI_SMOKE"], "1")
        self.assertEqual(env["CISCOAUTOFLASH_UI_SMOKE_CLOSE_MS"], "1800")

    def test_run_ui_smoke_writes_ready_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "ui-smoke"
            with patch(
                "ciscoautoflash.devtools.ui_smoke.subprocess.run",
                return_value=CompletedProcess(
                    args=["python"],
                    returncode=0,
                    stdout="ok\n",
                    stderr="",
                ),
            ):
                summary = ui_smoke.run_ui_smoke(
                    output_dir=output_dir,
                    python_exe="python",
                    demo_scenario="stage2_install_success",
                    close_ms=1200,
                )
            self.assertEqual(summary["status"], "READY")
            self.assertEqual(summary["demo_scenario"], "stage2_install_success")
            self.assertTrue(Path(summary["artifacts"]["process_log"]).exists())

    def test_run_ui_smoke_marks_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "ui-smoke"
            with patch(
                "ciscoautoflash.devtools.ui_smoke.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["python"], timeout=20),
            ):
                summary = ui_smoke.run_ui_smoke(output_dir=output_dir, python_exe="python")

        self.assertEqual(summary["status"], "NOT_READY")
        self.assertTrue(summary["timed_out"])
        self.assertEqual(summary["returncode"], 124)

    def test_main_writes_json_summary(self) -> None:
        fake_summary = {
            "status": "READY",
            "started_at": "2026-04-12T00:00:00+00:00",
            "completed_at": "2026-04-12T00:00:10+00:00",
            "elapsed_seconds": 1.5,
            "timed_out": False,
            "returncode": 0,
            "command": ["python", "main.py", "--demo"],
            "demo_scenario": "default",
            "close_ms": 1500,
            "artifacts": {"process_log": "x"},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            json_out = Path(temp_dir) / "summary.json"
            with (
                patch.object(ui_smoke, "run_ui_smoke", return_value=fake_summary),
                patch.object(ui_smoke, "render_markdown", return_value="# ok\n"),
            ):
                rc = ui_smoke.main(["--json-out", str(json_out)])
            saved = json.loads(json_out.read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        self.assertEqual(saved["status"], "READY")


if __name__ == "__main__":
    unittest.main()
