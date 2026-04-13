from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ciscoautoflash.devtools import session_close


def _make_repo_layout(root: Path) -> None:
    (root / "OBSMEM" / "analyses").mkdir(parents=True, exist_ok=True)
    (root / "OBSMEM" / "mirrors").mkdir(parents=True, exist_ok=True)
    (root / "OBSMEM" / "inbox").mkdir(parents=True, exist_ok=True)
    (root / "OBSMEM" / "analyses" / "Memory_Lint_Checklist.md").write_text(
        "# Memory Lint Checklist\n",
        encoding="utf-8",
    )
    for name in (
        "CiscoAutoFlash_Current_State.md",
        "Active_Risks.md",
        "Open_Architecture_Questions.md",
        "Hardware_Smoke_Gate.md",
    ):
        (root / "OBSMEM" / "mirrors" / name).write_text(f"# {name}\n", encoding="utf-8")


class SessionCloseTests(unittest.TestCase):
    def test_collect_obsmem_mirror_checks_ignores_dirty_mirror_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _make_repo_layout(root)
            checks = session_close._collect_obsmem_mirror_checks(
                root,
                root / "OBSMEM",
                [
                    {
                        "status": " M",
                        "path": "OBSMEM/mirrors/CiscoAutoFlash_Current_State.md",
                        "old_path": "",
                        "raw": " M OBSMEM/mirrors/CiscoAutoFlash_Current_State.md",
                    },
                    {
                        "status": " M",
                        "path": "OBSMEM/mirrors/Active_Risks.md",
                        "old_path": "",
                        "raw": " M OBSMEM/mirrors/Active_Risks.md",
                    },
                ],
            )
            self.assertEqual([], checks["gaps"])
            self.assertTrue(all(item["status"] == "ok" for item in checks["checks"]))

    def test_main_writes_summary_files_for_clean_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _make_repo_layout(root)
            build_root = root / "build" / "devtools" / "session_close"

            with (
                patch.object(session_close, "PROJECT_ROOT", root),
                patch.object(session_close, "OBSMEM_ROOT", root / "OBSMEM"),
                patch.object(session_close, "BUILD_ROOT", build_root),
                patch.object(
                    session_close,
                    "_collect_dirty_files",
                    return_value={
                        "ok": True,
                        "summary": "no dirty files",
                        "items": [],
                        "error": "",
                    },
                ),
                patch.object(
                    session_close,
                    "_collect_obsmem_mirror_checks",
                    return_value={
                        "checks": [
                            {
                                "path": str(
                                    root / "OBSMEM" / "mirrors" / "CiscoAutoFlash_Current_State.md"
                                ),
                                "exists": True,
                                "size_bytes": 18,
                                "status": "ok",
                                "reason": "mirror note exists and is current enough",
                                "target_sources": [],
                            }
                        ],
                        "gaps": [],
                        "summary": "no OBSMEM mirror gaps",
                    },
                ),
                patch.object(
                    session_close,
                    "_memory_lint_presence",
                    return_value={
                        "path": str(root / "OBSMEM" / "analyses" / "Memory_Lint_Checklist.md"),
                        "present": True,
                        "size_bytes": 24,
                        "summary": "Memory_Lint_Checklist present",
                    },
                ),
                patch.object(
                    session_close,
                    "_check_continuity_readiness",
                    return_value={
                        "ok": True,
                        "summary": "EchoVault continuity looks ready",
                        "memory_exe": "C:\\Python314\\Scripts\\memory.exe",
                        "stdout": "pointer",
                        "stderr": "",
                        "returncode": 0,
                    },
                ),
            ):
                exit_code = session_close.main([])

            self.assertEqual(exit_code, 0)
            output_dirs = list(build_root.iterdir())
            self.assertEqual(1, len(output_dirs))
            summary_json = output_dirs[0] / "summary.json"
            summary_md = output_dirs[0] / "summary.md"
            self.assertTrue(summary_json.exists())
            self.assertTrue(summary_md.exists())
            summary = json.loads(summary_json.read_text(encoding="utf-8"))
            self.assertEqual("CLEAN", summary["status"])
            self.assertEqual(4, len(summary["checks"]))
            self.assertIn("Session Close", summary_md.read_text(encoding="utf-8"))

    def test_main_writes_obsmem_draft_and_calls_memory_save(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _make_repo_layout(root)
            build_root = root / "build" / "devtools" / "session_close"
            memory_exe = r"C:\Python314\Scripts\memory.exe"
            run_calls: list[list[str]] = []

            def fake_run_command(args: list[str], *, cwd: Path | None = None, timeout: int = 30):
                run_calls.append(list(args))
                if len(args) >= 2 and args[1] == "save":
                    return session_close.CommandResult(0, "saved", "Memory saved without vector.")
                return session_close.CommandResult(0, "", "")

            with (
                patch.object(session_close, "PROJECT_ROOT", root),
                patch.object(session_close, "OBSMEM_ROOT", root / "OBSMEM"),
                patch.object(session_close, "BUILD_ROOT", build_root),
                patch.object(session_close, "INBOX_ROOT", root / "OBSMEM" / "inbox"),
                patch.object(
                    session_close,
                    "_collect_dirty_files",
                    return_value={
                        "ok": True,
                        "summary": "no dirty files",
                        "items": [],
                        "error": "",
                    },
                ),
                patch.object(
                    session_close,
                    "_collect_obsmem_mirror_checks",
                    return_value={"checks": [], "gaps": [], "summary": "no OBSMEM mirror gaps"},
                ),
                patch.object(
                    session_close,
                    "_memory_lint_presence",
                    return_value={
                        "path": str(root / "OBSMEM" / "analyses" / "Memory_Lint_Checklist.md"),
                        "present": True,
                        "size_bytes": 24,
                        "summary": "Memory_Lint_Checklist present",
                    },
                ),
                patch.object(
                    session_close,
                    "_check_continuity_readiness",
                    return_value={
                        "ok": True,
                        "summary": "EchoVault continuity looks ready",
                        "memory_exe": memory_exe,
                        "stdout": "pointer",
                        "stderr": "",
                        "returncode": 0,
                    },
                ),
                patch.object(
                    session_close.shutil,
                    "which",
                    side_effect=lambda name: memory_exe if name == "memory" else None,
                ),
                patch.object(session_close, "_run_command", side_effect=fake_run_command),
            ):
                exit_code = session_close.main(["--save-echovault", "--write-obsmem-draft"])

            self.assertEqual(exit_code, 0)
            self.assertTrue(any(call[:2] == [memory_exe, "save"] for call in run_calls))
            draft_files = list((root / "OBSMEM" / "inbox").glob("session_close_*.md"))
            self.assertEqual(1, len(draft_files))
            draft_text = draft_files[0].read_text(encoding="utf-8")
            self.assertIn("Session Close Draft", draft_text)
            self.assertIn("source_of_truth: repo", draft_text)
            output_dirs = list(build_root.iterdir())
            self.assertEqual(1, len(output_dirs))
            summary = json.loads((output_dirs[0] / "summary.json").read_text(encoding="utf-8"))
            self.assertTrue(summary["continuity"]["echovault_save"]["ok"])
            self.assertIn("obsmem_draft", summary["artifacts"])

    def test_main_reports_dirty_files_and_returns_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _make_repo_layout(root)
            build_root = root / "build" / "devtools" / "session_close"
            dirty_item = {
                "status": " M",
                "path": "ciscoautoflash/ui/app.py",
                "old_path": "",
                "raw": " M ciscoautoflash/ui/app.py",
            }

            with (
                patch.object(session_close, "PROJECT_ROOT", root),
                patch.object(session_close, "OBSMEM_ROOT", root / "OBSMEM"),
                patch.object(session_close, "BUILD_ROOT", build_root),
                patch.object(
                    session_close,
                    "_collect_dirty_files",
                    return_value={
                        "ok": True,
                        "summary": "1 dirty file(s) detected",
                        "items": [dirty_item],
                        "error": "",
                    },
                ),
                patch.object(
                    session_close,
                    "_collect_obsmem_mirror_checks",
                    return_value={
                        "checks": [
                            {
                                "path": str(
                                    root / "OBSMEM" / "mirrors" / "CiscoAutoFlash_Current_State.md"
                                ),
                                "exists": True,
                                "size_bytes": 18,
                                "status": "stale",
                                "reason": "mirror note is older than recent repo changes",
                                "target_sources": ["ciscoautoflash/ui/app.py"],
                            }
                        ],
                        "gaps": [
                            {
                                "path": str(
                                    root / "OBSMEM" / "mirrors" / "CiscoAutoFlash_Current_State.md"
                                ),
                                "exists": True,
                                "size_bytes": 18,
                                "status": "stale",
                                "reason": "mirror note is older than recent repo changes",
                                "target_sources": ["ciscoautoflash/ui/app.py"],
                            }
                        ],
                        "summary": "1 OBSMEM mirror gap(s) detected",
                    },
                ),
                patch.object(
                    session_close,
                    "_memory_lint_presence",
                    return_value={
                        "path": str(root / "OBSMEM" / "analyses" / "Memory_Lint_Checklist.md"),
                        "present": True,
                        "size_bytes": 24,
                        "summary": "Memory_Lint_Checklist present",
                    },
                ),
                patch.object(
                    session_close,
                    "_check_continuity_readiness",
                    return_value={
                        "ok": False,
                        "summary": "EchoVault continuity is not ready",
                        "memory_exe": "",
                        "stdout": "",
                        "stderr": "missing",
                        "returncode": 127,
                    },
                ),
            ):
                exit_code = session_close.main([])

            self.assertEqual(exit_code, 1)
            output_dirs = list(build_root.iterdir())
            self.assertEqual(1, len(output_dirs))
            summary = json.loads((output_dirs[0] / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual("ACTION_REQUIRED", summary["status"])
            self.assertTrue(summary["mirror_gaps"])
            self.assertTrue(summary["recommendations"])


if __name__ == "__main__":
    unittest.main()
