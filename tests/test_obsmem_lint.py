from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ciscoautoflash.devtools import obsmem_lint


def _write_page(path: Path, *, frontmatter: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{frontmatter}\n{body}\n", encoding="utf-8")


def _write_repo_file(repo_root: Path, relative: str) -> str:
    target = repo_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# repo file\n", encoding="utf-8")
    return str(target)


def _good_frontmatter(
    *,
    repo_ref: str,
    aliases: list[str],
    related: list[str],
    last_verified: str,
) -> str:
    alias_lines = "\n".join(f"  - {item}" for item in aliases)
    related_lines = "\n".join(f"  - \"{item}\"" for item in related)
    return "\n".join(
        [
            "---",
            "type: project-note",
            "status: active",
            "source_of_truth: repo",
            "repo_refs:",
            f"  - {repo_ref}",
            "aliases:",
            alias_lines,
            "related:",
            related_lines,
            f"last_verified: {last_verified}",
            "---",
        ]
    )


class ObsmemLintTests(unittest.TestCase):
    def test_lint_obsmem_passes_for_well_linked_vault(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            vault = Path(temp_dir) / "OBSMEM"
            readme_ref = _write_repo_file(repo_root, "README.md")
            agents_ref = _write_repo_file(repo_root, "AGENTS.md")
            _write_page(
                vault / "README.md",
                frontmatter="\n".join(
                    [
                        "---",
                        "type: mirror",
                        "status: active",
                        "source_of_truth: repo",
                        "repo_refs:",
                        f"  - {readme_ref}",
                        "related:",
                        "  - \"[[CiscoAutoFlash]]\"",
                        "last_verified: 2026-04-12",
                        "---",
                    ]
                ),
                body="# OBSMEM\n\n## Read next\n- [[CiscoAutoFlash]]",
            )
            _write_page(
                vault / "projects" / "CiscoAutoFlash.md",
                frontmatter=_good_frontmatter(
                    repo_ref=readme_ref,
                    aliases=["CiscoAutoFlash"],
                    related=["[[Knowledge_System_Model]]"],
                    last_verified="2026-04-12",
                ),
                body="# CiscoAutoFlash\n\n## Read next\n- [[Knowledge_System_Model]]",
            )
            _write_page(
                vault / "concepts" / "Knowledge_System_Model.md",
                frontmatter="\n".join(
                    [
                        "---",
                        "type: concept",
                        "status: active",
                        "source_of_truth: repo",
                        "repo_refs:",
                        f"  - {agents_ref}",
                        "aliases:",
                        "  - Knowledge System Model",
                        "related:",
                        "  - \"[[CiscoAutoFlash]]\"",
                        "last_verified: 2026-04-12",
                        "---",
                    ]
                ),
                body="# Knowledge System Model\n\n## Read next\n- [[CiscoAutoFlash]]",
            )

            summary = obsmem_lint.lint_obsmem(vault, output_root=Path(temp_dir) / "build")

            self.assertEqual(0, summary["error_count"])
            self.assertGreaterEqual(summary["warning_count"], 0)
            self.assertTrue(Path(summary["summary_json"]).exists())
            self.assertTrue(Path(summary["summary_md"]).exists())
            payload = json.loads(Path(summary["summary_json"]).read_text(encoding="utf-8"))
            self.assertEqual("PASS", payload["status"])
            self.assertEqual(3, payload["important_pages_scanned"])

    def test_lint_obsmem_reports_errors_and_strict_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            vault = Path(temp_dir) / "OBSMEM"
            valid_readme_ref = _write_repo_file(repo_root, "README.md")
            _write_page(
                vault / "projects" / "CiscoAutoFlash.md",
                frontmatter=_good_frontmatter(
                    repo_ref=valid_readme_ref,
                    aliases=["CiscoAutoFlash"],
                    related=["[[Duplicate Topic]]"],
                    last_verified="2026-04-12",
                ),
                body="# CiscoAutoFlash\n\n## Read next\n- [[Duplicate Topic]]",
            )
            _write_page(
                vault / "concepts" / "Duplicate_One.md",
                frontmatter="\n".join(
                    [
                        "---",
                        "type: concept",
                        "status: active",
                        "source_of_truth: repo",
                        "repo_refs:",
                        "  - C:\\PROJECT\\missing\\nowhere.md",
                        "aliases:",
                        "  - Duplicate Topic",
                        "related:",
                        "  - \"[[CiscoAutoFlash]]\"",
                        "last_verified: 2025-01-01",
                        "---",
                    ]
                ),
                body="# Duplicate One\n\n## Read next\n- [[CiscoAutoFlash]]",
            )
            _write_page(
                vault / "concepts" / "Duplicate_Two.md",
                frontmatter="\n".join(
                    [
                        "---",
                        "type: concept",
                        "status: active",
                        "source_of_truth: repo",
                        "repo_refs:",
                        f"  - {valid_readme_ref}",
                        "aliases:",
                        "  - Duplicate Topic",
                        "related:",
                        "  - \"[[CiscoAutoFlash]]\"",
                        "last_verified: 2026-04-12",
                        "---",
                    ]
                ),
                body="# Duplicate Two\n\n## Read next\n- [[CiscoAutoFlash]]",
            )
            _write_page(
                vault / "mirrors" / "Orphan.md",
                frontmatter="\n".join(
                    [
                        "---",
                        "type: mirror",
                        "status: active",
                        "source_of_truth: repo",
                        "repo_refs:",
                        f"  - {valid_readme_ref}",
                        "related:",
                        "  - \"[[CiscoAutoFlash]]\"",
                        "last_verified: 2024-01-01",
                        "---",
                    ]
                ),
                body="# Orphan\n\n## Read next\n- [[CiscoAutoFlash]]",
            )

            summary = obsmem_lint.lint_obsmem(vault, output_root=Path(temp_dir) / "build")
            exit_code = obsmem_lint.main(
                [
                    "--vault",
                    str(vault),
                    "--output-root",
                    str(Path(temp_dir) / "build"),
                ]
            )
            strict_exit = obsmem_lint.main(
                [
                    "--vault",
                    str(vault),
                    "--output-root",
                    str(Path(temp_dir) / "build"),
                    "--strict",
                ]
            )

        warning_codes = {
            item["code"]
            for item in summary["findings"]
            if item["severity"] == "warning"
        }
        self.assertIn("duplicate_canonical_topic", warning_codes)
        self.assertIn("stale_mirror", warning_codes)
        self.assertIn("orphan_page", warning_codes)
        self.assertEqual(0, exit_code)
        self.assertEqual(1, strict_exit)

    def test_lint_obsmem_flags_missing_frontmatter_and_related_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repo"
            vault = Path(temp_dir) / "OBSMEM"
            missing_ref = str(repo_root / "missing" / "bad.md")
            _write_page(
                vault / "projects" / "Bad.md",
                frontmatter="\n".join(
                    [
                        "---",
                        "type: project-note",
                        "status: active",
                        "source_of_truth: repo",
                        "repo_refs:",
                        f"  - {missing_ref}",
                        "related: []",
                        "last_verified: 2026-04-12",
                        "---",
                    ]
                ),
                body="# Bad\n",
            )
            _write_page(
                vault / "concepts" / "NoFrontmatter.md",
                frontmatter="",
                body="# No Frontmatter\n\n## Read next\n- [[Bad]]",
            )

            summary = obsmem_lint.lint_obsmem(vault, output_root=Path(temp_dir) / "build")

        error_codes = {item["code"] for item in summary["findings"] if item["severity"] == "error"}
        self.assertIn("missing_related", error_codes)
        self.assertIn("missing_read_next", error_codes)
        self.assertIn("missing_frontmatter", error_codes)


if __name__ == "__main__":
    unittest.main()
