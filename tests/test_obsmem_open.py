from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ciscoautoflash.devtools import obsmem_open


class ObsmemOpenTests(unittest.TestCase):
    def test_resolve_target_supports_canonical_current_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current_work = root / "mirrors" / "Current_Work.md"
            current_work.parent.mkdir(parents=True, exist_ok=True)
            current_work.write_text("# Current Work\n", encoding="utf-8")
            with patch.object(obsmem_open, "OBSMEM_ROOT", root):
                path = obsmem_open.resolve_target("current-work")
            self.assertEqual(current_work, path)

    def test_build_obsidian_uri_uses_open_path_scheme(self) -> None:
        path = Path(r"C:\PROJECT\OBSMEM\mirrors\Current_Work.md")
        uri = obsmem_open.build_obsidian_uri(path)
        self.assertTrue(uri.startswith("obsidian://open?path="))
        self.assertIn("Current_Work.md", uri)

    def test_main_opens_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "index.md"
            target.write_text("# Index\n", encoding="utf-8")
            with (
                patch.object(obsmem_open, "OBSMEM_ROOT", root),
                patch.object(obsmem_open.webbrowser, "open", return_value=True) as mocked_open,
            ):
                exit_code = obsmem_open.main(["index"])
            self.assertEqual(0, exit_code)
            mocked_open.assert_called_once()

    def test_main_fails_for_missing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch.object(obsmem_open, "OBSMEM_ROOT", root):
                exit_code = obsmem_open.main(["missing-note.md"])
            self.assertEqual(1, exit_code)


if __name__ == "__main__":
    unittest.main()
