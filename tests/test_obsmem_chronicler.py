from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ciscoautoflash.devtools import obsmem_chronicler


def _make_vault(root: Path) -> Path:
    vault = root / "OBSMEM"
    (vault / "mirrors").mkdir(parents=True, exist_ok=True)
    (vault / "daily").mkdir(parents=True, exist_ok=True)
    (vault / "concepts").mkdir(parents=True, exist_ok=True)
    (vault / "log.md").write_text("# OBSMEM Log\n", encoding="utf-8")
    return vault


def _fake_run_command(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 30,
) -> tuple[int, str, str]:
    del cwd, timeout
    mapping = {
        ("git", "branch", "--show-current"): (0, "main", ""),
        ("git", "rev-parse", "HEAD"): (0, "1234567890abcdef1234567890abcdef12345678", ""),
        ("git", "log", "-1", "--pretty=%s"): (0, "Test commit subject", ""),
        (
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ): (0, " M ciscoautoflash/ui/app.py\n M tests/test_ui_app.py", ""),
    }
    return mapping.get(tuple(args), (1, "", "unexpected command"))


class ObsmemChroniclerTests(unittest.TestCase):
    def test_run_snapshot_writes_current_work_and_daily_note(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vault = _make_vault(root)
            output_root = root / "build" / "devtools" / "obsmem_chronicler"
            state_path = output_root / "runtime" / "state.json"
            runtime_root = output_root / "runtime"

            with (
                patch.object(obsmem_chronicler, "_run_command", side_effect=_fake_run_command),
                patch.object(
                    obsmem_chronicler,
                    "_helper_statuses",
                    return_value={
                        "bootstrap": {"status": "READY", "path": "a", "completed_at": "now"},
                        "memory_lint": {"status": "PASS", "path": "b", "completed_at": "now"},
                        "session_close": {"status": "CLEAN", "path": "c", "completed_at": "now"},
                        "ui_smoke": {"status": "OK", "path": "d", "completed_at": "now"},
                    },
                ),
            ):
                summary = obsmem_chronicler.run_snapshot(
                    project_root=root,
                    vault_root=vault,
                    output_root=output_root,
                    state_path=state_path,
                    runtime_root=runtime_root,
                    session_label="UI polish",
                )

            self.assertEqual("UPDATED", summary["status"])
            current_work = vault / "mirrors" / "Current_Work.md"
            daily_note = vault / "daily" / f"{obsmem_chronicler._today_str()}.md"
            self.assertTrue(current_work.exists())
            self.assertTrue(daily_note.exists())
            self.assertIn("UI polish", current_work.read_text(encoding="utf-8"))
            self.assertIn("Current Work", current_work.read_text(encoding="utf-8"))
            self.assertIn("Victories", daily_note.read_text(encoding="utf-8"))
            self.assertTrue(state_path.exists())

    def test_run_manual_event_appends_log_and_preserves_manual_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vault = _make_vault(root)
            output_root = root / "build" / "devtools" / "obsmem_chronicler"
            state_path = output_root / "runtime" / "state.json"
            runtime_root = output_root / "runtime"
            daily_note = vault / "daily" / f"{obsmem_chronicler._today_str()}.md"
            daily_note.write_text(
                "\n".join(
                    [
                        "# Existing",
                        obsmem_chronicler.MANUAL_NOTES_START,
                        "- Keep this note",
                        obsmem_chronicler.MANUAL_NOTES_END,
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            with (
                patch.object(obsmem_chronicler, "_run_command", side_effect=_fake_run_command),
                patch.object(
                    obsmem_chronicler,
                    "_helper_statuses",
                    return_value={
                        "bootstrap": {
                            "status": "READY",
                            "path": "a",
                            "completed_at": "now",
                        }
                    },
                ),
            ):
                summary = obsmem_chronicler.run_manual_event(
                    project_root=root,
                    vault_root=vault,
                    output_root=output_root,
                    state_path=state_path,
                    runtime_root=runtime_root,
                    event_type="win",
                    message="UI block became readable",
                    session_label="UI polish",
                )

            self.assertEqual("EVENT_RECORDED", summary["status"])
            log_text = (vault / "log.md").read_text(encoding="utf-8")
            self.assertIn("Victory | UI block became readable", log_text)
            updated_daily = daily_note.read_text(encoding="utf-8")
            self.assertIn("UI block became readable", updated_daily)
            self.assertIn("- Keep this note", updated_daily)

    def test_run_watch_records_session_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            vault = _make_vault(root)
            output_root = root / "build" / "devtools" / "obsmem_chronicler"
            state_path = output_root / "runtime" / "state.json"
            runtime_root = output_root / "runtime"

            with (
                patch.object(obsmem_chronicler, "_run_command", side_effect=_fake_run_command),
                patch.object(
                    obsmem_chronicler,
                    "_helper_statuses",
                    return_value={
                        "bootstrap": {
                            "status": "READY",
                            "path": "a",
                            "completed_at": "now",
                        }
                    },
                ),
            ):
                summary = obsmem_chronicler.run_watch(
                    project_root=root,
                    vault_root=vault,
                    output_root=output_root,
                    state_path=state_path,
                    runtime_root=runtime_root,
                    session_label="Background chronicle",
                    interval_seconds=1,
                    max_cycles=1,
                )

            self.assertEqual("WATCH_STOPPED", summary["status"])
            events = obsmem_chronicler._load_events(runtime_root / "events.jsonl")
            event_types = [event["event_type"] for event in events]
            self.assertIn("session_start", event_types)
            self.assertIn("snapshot", event_types)
            self.assertIn("session_stop", event_types)
            state = obsmem_chronicler._load_json(state_path, {})
            self.assertEqual("", state.get("active_session_id", ""))


if __name__ == "__main__":
    unittest.main()
