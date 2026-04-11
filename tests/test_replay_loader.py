from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ciscoautoflash.replay import loader

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ReplayLoaderTests(unittest.TestCase):
    def test_default_scenario_dir_uses_project_root(self) -> None:
        fake_root = Path(r"C:\temp\portable-root")
        with patch("ciscoautoflash.replay.loader.default_project_root", return_value=fake_root):
            self.assertEqual(loader.default_scenario_dir(), fake_root / "replay_scenarios")

    def test_load_scenarios_uses_frozen_safe_default_directory(self) -> None:
        source = (PROJECT_ROOT / "replay_scenarios" / "stage3_verify.toml").read_text(
            encoding="utf-8"
        )
        with tempfile.TemporaryDirectory(prefix="ciscoautoflash-replay-loader-") as temp_dir:
            root = Path(temp_dir)
            scenario_dir = root / "replay_scenarios"
            scenario_dir.mkdir(parents=True)
            scenario_path = scenario_dir / "stage3_verify.toml"
            scenario_path.write_text(source, encoding="utf-8")

            with patch("ciscoautoflash.replay.loader.default_project_root", return_value=root):
                resolved = loader.resolve_scenario_path("stage3_verify")
                scenarios = loader.load_scenarios()

        self.assertEqual(resolved, scenario_path)
        self.assertEqual([scenario.name for scenario in scenarios], ["stage3_verify"])


if __name__ == "__main__":
    unittest.main()
