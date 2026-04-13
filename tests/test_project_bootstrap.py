from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ciscoautoflash.devtools import project_bootstrap


class ProjectBootstrapTests(unittest.TestCase):
    def test_run_bootstrap_writes_ready_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "bootstrap"

            def fake_run(command: list[str], **_: object) -> project_bootstrap.CommandResult:
                text = " ".join(command)
                if command[:3] == ["git", "status", "--short"]:
                    return project_bootstrap.CommandResult(0, "", "")
                if command[:2] == ["uv", "--version"]:
                    return project_bootstrap.CommandResult(0, "uv 1.0.0", "")
                return project_bootstrap.CommandResult(0, f"ok: {text}", "")

            with patch.object(project_bootstrap, "run_command", side_effect=fake_run):
                summary = project_bootstrap.run_bootstrap(output_dir, python_exe="python")
            self.assertEqual(summary["status"], "READY")
            self.assertEqual(summary["failing_step"], "")
            self.assertEqual(len(summary["steps"]), 8)
            self.assertTrue((output_dir / "ruff.log").exists())

    def test_run_bootstrap_marks_first_required_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "bootstrap"

            def fake_run(command: list[str], **_: object) -> project_bootstrap.CommandResult:
                if command[:3] == ["git", "status", "--short"]:
                    return project_bootstrap.CommandResult(0, " M ciscoautoflash/ui/app.py", "")
                if command[:2] == ["uv", "--version"]:
                    return project_bootstrap.CommandResult(0, "uv 1.0.0", "")
                if "mypy" in command:
                    return project_bootstrap.CommandResult(1, "", "mypy failed")
                return project_bootstrap.CommandResult(0, "ok", "")

            with patch.object(project_bootstrap, "run_command", side_effect=fake_run):
                summary = project_bootstrap.run_bootstrap(output_dir, python_exe="python")

        self.assertEqual(summary["status"], "NOT_READY")
        self.assertEqual(summary["failing_step"], "mypy")
        self.assertTrue(summary["runtime"]["git_dirty"])

    def test_main_writes_json_summary(self) -> None:
        fake_summary = {
            "status": "READY",
            "started_at": "2026-04-12T00:00:00+00:00",
            "completed_at": "2026-04-12T00:01:00+00:00",
            "runtime": {
                "project_root": "C:/PROJECT",
                "python_executable": "python",
                "python_version": "3.14.0",
                "platform": "Windows",
                "started_at": "2026-04-12T00:00:00+00:00",
                "git_dirty": False,
                "git_status": [],
                "uv_version": "uv 1.0.0",
            },
            "steps": [],
            "failing_step": "",
            "artifacts": {},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            json_out = Path(temp_dir) / "summary.json"
            with (
                patch.object(project_bootstrap, "run_bootstrap", return_value=fake_summary),
                patch.object(project_bootstrap, "render_markdown", return_value="# ok\n"),
            ):
                rc = project_bootstrap.main(["--json-out", str(json_out)])
            saved = json.loads(json_out.read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        self.assertEqual(saved["status"], "READY")


if __name__ == "__main__":
    unittest.main()
