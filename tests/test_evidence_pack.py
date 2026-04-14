from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ciscoautoflash.devtools import evidence_pack


def _session_close_summary(*, dirty_count: int = 0, stale: bool = False) -> dict[str, object]:
    return {
        "generated_at": "2026-04-14T12:00:00+00:00",
        "status": "ACTION_REQUIRED" if dirty_count or stale else "CLEAN",
        "checks": [
            {
                "name": "dirty_files",
                "ok": dirty_count == 0,
                "details": [f"{dirty_count} dirty file(s)"] if dirty_count else [],
            },
            {
                "name": "current_work_freshness",
                "ok": not stale,
                "details": ["head mismatch"] if stale else [],
            },
        ],
        "continuity": {
            "ok": True,
            "summary": "EchoVault continuity looks ready",
        },
        "current_work_freshness": {
            "ok": not stale,
            "summary": (
                "Current_Work is stale against live git state"
                if stale
                else "Current_Work matches the live git state"
            ),
            "mismatches": ["head"] if stale else [],
        },
    }


def _memory_lint_summary(*, errors: int = 0, warnings: int = 0, root: Path) -> dict[str, object]:
    output_dir = root / "build" / "devtools" / "memory_lint" / "20260414_120000"
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_json = output_dir / "summary.json"
    summary_json.write_text("{}", encoding="utf-8")
    findings = []
    if errors:
        findings.append(
            {
                "severity": "error",
                "code": "missing_frontmatter",
                "path": "mirrors/Current_Work.md",
                "message": "missing frontmatter",
            }
        )
    return {
        "generated_at": "2026-04-14T12:00:01+00:00",
        "status": "FAIL" if errors else "PASS",
        "error_count": errors,
        "warning_count": warnings,
        "findings": findings,
        "summary_json": str(summary_json),
    }


class EvidencePackTests(unittest.TestCase):
    def test_build_evidence_pack_writes_structured_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "build" / "devtools" / "evidence_pack" / "case"
            bootstrap_dir = root / "build" / "devtools" / "bootstrap" / "20260414_120005"
            bootstrap_dir.mkdir(parents=True, exist_ok=True)
            bootstrap_log = bootstrap_dir / "mypy.log"
            bootstrap_log.write_text("line 1\nline 2\n", encoding="utf-8")

            bootstrap_summary = {
                "status": "NOT_READY",
                "completed_at": "2026-04-14T12:00:05+00:00",
                "_summary_path": str(bootstrap_dir / "summary.json"),
                "steps": [
                    {
                        "name": "mypy",
                        "ok": False,
                        "returncode": 1,
                        "required": True,
                        "log_path": str(bootstrap_log),
                    }
                ],
            }
            ui_smoke_summary = {
                "status": "OK",
                "completed_at": "2026-04-14T12:00:06+00:00",
                "_summary_path": str(root / "build" / "devtools" / "ui_smoke" / "summary.json"),
            }
            repo_state = {
                "branch": "main",
                "head_sha": "abc123def4567890",
                "head_subject": "Test subject",
                "dirty_files": [
                    {
                        "status": " M",
                        "path": "README.md",
                        "old_path": "",
                        "raw": " M README.md",
                    }
                ],
                "dirty_count": 1,
                "git_ok": True,
            }

            with (
                patch.object(evidence_pack, "PROJECT_ROOT", root),
                patch.object(evidence_pack, "OBSMEM_ROOT", root / "OBSMEM"),
                patch.object(
                    evidence_pack,
                    "OUTPUT_ROOT",
                    root / "build" / "devtools" / "evidence_pack",
                ),
                patch.dict(
                    evidence_pack.HELPER_ROOTS,
                    {
                        "bootstrap": root / "build" / "devtools" / "bootstrap",
                        "ui_smoke": root / "build" / "devtools" / "ui_smoke",
                    },
                    clear=True,
                ),
                patch.object(evidence_pack, "_collect_repo_state", return_value=repo_state),
                patch.object(
                    evidence_pack.session_close,
                    "analyze_session_close",
                    return_value=_session_close_summary(dirty_count=1, stale=False),
                ),
                patch.object(
                    evidence_pack.obsmem_lint,
                    "lint_obsmem",
                    return_value=_memory_lint_summary(errors=0, warnings=0, root=root),
                ),
                patch.object(
                    evidence_pack,
                    "_latest_summary",
                    side_effect=[bootstrap_summary, ui_smoke_summary],
                ),
            ):
                summary = evidence_pack.build_evidence_pack(output_dir)
                summary_json, summary_md, summary_toon = (
                    evidence_pack._write_summary_files(output_dir, summary)
                )

            self.assertEqual("READY_FOR_JUDGE", summary["status"])
            self.assertEqual("session-close", summary["task_type"])
            self.assertEqual(6, len(summary["hypotheses"]))
            dirty_hypothesis = next(
                item for item in summary["hypotheses"] if item["id"] == "dirty_repo_state"
            )
            self.assertEqual("supported", dirty_hypothesis["status"])
            self.assertTrue(summary_json.exists())
            self.assertTrue(summary_md.exists())
            self.assertTrue(summary_toon.exists())
            self.assertIn("CiscoAutoFlash Evidence Pack", summary_md.read_text(encoding="utf-8"))
            self.assertIn("helper_statuses[]:", summary_toon.read_text(encoding="utf-8"))

    def test_main_writes_explicit_json_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            json_out = root / "evidence.json"
            latest_summary = root / "build" / "devtools" / "evidence_pack" / "latest_summary.json"
            fake_summary = {
                "case_id": "session-close-1",
                "generated_at": "2026-04-14T12:00:00+00:00",
                "task_type": "session-close",
                "status": "READY_FOR_JUDGE",
                "project_root": str(root),
                "obsmem_root": str(root / "OBSMEM"),
                "repo": {
                    "branch": "main",
                    "head_sha": "abc123",
                    "head_subject": "Test",
                    "dirty_files": [],
                    "dirty_count": 0,
                    "git_ok": True,
                },
                "helper_statuses": [],
                "live_checks": {},
                "lint_findings": [],
                "test_failures": [],
                "relevant_logs": [],
                "relevant_code_refs": [],
                "hypotheses": [],
                "unknowns": [],
                "artifacts": {
                    "output_dir": str(root / "build"),
                    "summary_json": str(root / "build" / "summary.json"),
                    "summary_md": str(root / "build" / "summary.md"),
                    "summary_toon": str(root / "build" / "summary.toon"),
                },
            }

            with (
                patch.object(
                    evidence_pack,
                    "OUTPUT_ROOT",
                    root / "build" / "devtools" / "evidence_pack",
                ),
                patch.object(evidence_pack, "LATEST_SUMMARY_PATH", latest_summary),
                patch.object(evidence_pack, "build_evidence_pack", return_value=fake_summary),
            ):
                rc = evidence_pack.main(["--json-out", str(json_out)])

            self.assertEqual(0, rc)
            saved = json.loads(json_out.read_text(encoding="utf-8"))
            self.assertEqual("session-close-1", saved["case_id"])
            latest = json.loads(latest_summary.read_text(encoding="utf-8"))
            self.assertEqual("session-close-1", latest["case_id"])


if __name__ == "__main__":
    unittest.main()
