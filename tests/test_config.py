from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ciscoautoflash.config import AppConfig


class AppConfigTests(unittest.TestCase):
    def test_create_session_paths_uses_localappdata_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            local_appdata = str(Path(tempdir) / "LocalAppData")
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


if __name__ == "__main__":
    unittest.main()
