from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from ciscoautoflash import config as config_module
from ciscoautoflash.config import AppConfig


class AppConfigTests(unittest.TestCase):
    def make_temp_dir(self) -> Path:
        tempdir = Path("C:/PROJECT/tests/_runtime_config") / uuid.uuid4().hex
        tempdir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, tempdir, ignore_errors=True)
        return tempdir

    def test_default_project_root_uses_meipass_when_frozen(self) -> None:
        tempdir = self.make_temp_dir()
        with (
            patch.object(config_module.sys, "frozen", True, create=True),
            patch.object(config_module.sys, "_MEIPASS", str(tempdir), create=True),
        ):
            self.assertEqual(config_module.default_project_root(), tempdir)
            self.assertEqual(AppConfig().project_root, tempdir)

    def test_create_session_paths_uses_localappdata_runtime_root(self) -> None:
        tempdir = self.make_temp_dir()
        local_appdata = str(tempdir / "LocalAppData")
        with patch.dict("os.environ", {"LOCALAPPDATA": local_appdata}, clear=False):
            config = AppConfig()
            session = config.create_session_paths()

        expected_root = Path(local_appdata) / "CiscoAutoFlash"
        self.assertEqual(session.base_dir, expected_root)
        self.assertTrue(session.logs_dir.exists())
        self.assertTrue(session.reports_dir.exists())
        self.assertTrue(session.transcripts_dir.exists())
        self.assertTrue(session.sessions_dir.exists())
        self.assertTrue(session.session_dir.exists())
        self.assertEqual(session.settings_path.parent, expected_root / "settings")
        self.assertEqual(session.session_dir.parent, expected_root / "sessions")
        self.assertEqual(session.manifest_path.parent, session.session_dir)
        self.assertEqual(session.bundle_path.parent, session.session_dir)
        self.assertEqual(session.settings_snapshot_path.parent, session.session_dir)
        self.assertTrue(str(session.log_path).startswith(str(expected_root)))
        self.assertTrue(str(session.report_path).startswith(str(expected_root)))
        self.assertTrue(str(session.transcript_path).startswith(str(expected_root)))
        self.assertTrue(str(session.manifest_path).startswith(str(expected_root)))
        self.assertTrue(str(session.bundle_path).startswith(str(expected_root)))

    def test_create_session_paths_falls_back_when_runtime_child_is_a_file(self) -> None:
        tempdir = self.make_temp_dir()
        runtime_root = tempdir / "CiscoAutoFlash"
        runtime_root.mkdir(parents=True, exist_ok=True)
        (runtime_root / "logs").write_text("conflict", encoding="utf-8")

        session = AppConfig(runtime_root=runtime_root).create_session_paths()

        expected_root = runtime_root / "_runtime"
        self.assertEqual(session.base_dir, expected_root)
        self.assertTrue(session.logs_dir.is_dir())
        self.assertTrue(session.sessions_dir.is_dir())
        self.assertEqual((runtime_root / "logs").read_text(encoding="utf-8"), "conflict")


if __name__ == "__main__":
    unittest.main()
