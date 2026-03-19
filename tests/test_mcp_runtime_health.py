from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ciscoautoflash.devtools import mcp_runtime_health as health


class MCPPuntimeHealthTests(unittest.TestCase):
    def test_parse_simple_yaml_reads_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "embedding:",
                        "  provider: ollama",
                        "  model: nomic-embed-text",
                        "context:",
                        "  semantic: auto",
                    ]
                ),
                encoding="utf-8",
            )

            parsed = health.parse_simple_yaml(config_path)

        self.assertEqual("ollama", parsed["embedding"]["provider"])
        self.assertEqual("nomic-embed-text", parsed["embedding"]["model"])
        self.assertEqual("auto", parsed["context"]["semantic"])

    def test_build_degraded_memory_home_writes_expected_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_home = health.build_degraded_memory_home(Path(temp_dir), base_url="http://127.0.0.1:9")
            config_text = (memory_home / "config.yaml").read_text(encoding="utf-8")

        self.assertIn("provider: ollama", config_text)
        self.assertIn("model: nomic-embed-text", config_text)
        self.assertIn("base_url: http://127.0.0.1:9", config_text)

    def test_probe_echovault_reports_nonfatal_degraded_embedding(self) -> None:
        fake_ok = {
            "save": {"returncode": 0, "stdout": "saved", "stderr": ""},
            "search": {"returncode": 0, "stdout": "found", "stderr": ""},
        }
        fake_degraded = {
            "save": {
                "returncode": 0,
                "stdout": "saved",
                "stderr": "Warning: embedding failed (...). Memory saved without vector.",
            },
            "search": {"returncode": 0, "stdout": "found", "stderr": ""},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_home = Path(temp_dir) / ".memory"
            memory_home.mkdir()
            (memory_home / "config.yaml").write_text(
                "embedding:\n  provider: ollama\n  model: nomic-embed-text\n",
                encoding="utf-8",
            )
            with patch.object(health, "probe_memory_cli", side_effect=[fake_ok, fake_degraded]):
                report = health.probe_echovault(
                    memory_exe=Path(r"C:\fake\memory.exe"),
                    memory_home=memory_home,
                )

        self.assertTrue(report["healthy_save_ok"])
        self.assertTrue(report["degraded_save_ok"])
        self.assertTrue(report["degraded_embedding_nonfatal"])
        self.assertEqual("ollama", report["config"]["embedding"]["provider"])

    def test_summarize_health_marks_all_green(self) -> None:
        report = {
            "ollama": {"api_ok": True, "required_model_present": True},
            "echovault": {
                "healthy_save_ok": True,
                "degraded_save_ok": True,
                "degraded_embedding_nonfatal": True,
            },
            "vector_memory": {"db_exists": True, "db_size_bytes": 128},
            "codex_logs": {"log_root_exists": True, "latest": [{"path": "x"}]},
        }

        summary = health.summarize_health(report)

        self.assertIn("Ollama: healthy", summary)
        self.assertIn("EchoVault save/read: healthy", summary)
        self.assertIn(
            "EchoVault degraded path: save succeeds without vectors when Ollama is unreachable",
            summary,
        )
        self.assertIn("vector-memory: healthy", summary)
        self.assertIn("Codex logs: present", summary)

    def test_main_writes_json_report(self) -> None:
        fake_report = {
            "summary": ["Ollama: healthy"],
            "mcp_servers": {},
            "ollama": {},
            "echovault": {},
            "vector_memory": {},
            "codex_logs": {},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "health.json"
            with patch.object(health, "build_health_report", return_value=fake_report):
                rc = health.main(["--json-out", str(output_path)])
            saved = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(0, rc)
        self.assertEqual(fake_report, saved)


if __name__ == "__main__":
    unittest.main()
