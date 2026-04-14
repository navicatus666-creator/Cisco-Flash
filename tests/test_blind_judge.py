from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ciscoautoflash.devtools import blind_judge


def _evidence_payload() -> dict[str, object]:
    return {
        "case_id": "session-close-1",
        "generated_at": "2026-04-14T12:00:00+00:00",
        "task_type": "session-close",
        "status": "READY_FOR_JUDGE",
        "repo": {
            "branch": "main",
            "head_sha": "abc123",
            "head_subject": "Test commit",
            "dirty_count": 2,
            "dirty_files": [{"status": " M", "path": "README.md"}],
        },
        "live_checks": {
            "session_close": {
                "current_work_freshness": {
                    "ok": False,
                    "summary": "Current_Work is stale against live git state",
                }
            }
        },
        "unknowns": ["missing helper artifact: bootstrap"],
        "hypotheses": [
            {
                "id": "dirty_repo_state",
                "summary": "Dirty tree blocks a clean close.",
                "severity": "error",
                "status": "supported",
                "recommended_action": "Commit or stash dirty files.",
                "supporting_evidence": ["git reports 2 dirty file(s)"],
                "contradicting_evidence": [],
                "unknowns": [],
            },
            {
                "id": "current_work_stale",
                "summary": "Current_Work may be stale.",
                "severity": "error",
                "status": "supported",
                "recommended_action": "Refresh Current_Work with the chronicler.",
                "supporting_evidence": ["Current_Work mismatches live git state (head)"],
                "contradicting_evidence": [],
                "unknowns": [],
            },
            {
                "id": "ui_or_runtime_uncertain",
                "summary": "UI smoke evidence is missing.",
                "severity": "warning",
                "status": "unknown",
                "recommended_action": "Refresh UI smoke evidence.",
                "supporting_evidence": [],
                "contradicting_evidence": [],
                "unknowns": ["ui_smoke helper artifact missing"],
            },
        ],
    }


class BlindJudgeTests(unittest.TestCase):
    def test_evaluate_evidence_ranks_supported_error_hypotheses(self) -> None:
        verdict = blind_judge.evaluate_evidence(_evidence_payload())
        self.assertEqual("ACTION_REQUIRED", verdict["status"])
        self.assertEqual("stale", verdict["freshness_verdict"]["status"])
        self.assertEqual("NOT_READY", verdict["close_readiness"]["status"])
        self.assertEqual("dirty_repo_state", verdict["hypothesis_ranking"][0]["id"])

    def test_main_loads_latest_evidence_and_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evidence_root = root / "build" / "devtools" / "evidence_pack" / "20260414_120000"
            evidence_root.mkdir(parents=True, exist_ok=True)
            evidence_json = evidence_root / "summary.json"
            evidence_json.write_text(
                json.dumps(_evidence_payload(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            latest_summary = root / "build" / "devtools" / "evidence_pack" / "latest_summary.json"
            latest_summary.write_text(
                json.dumps(_evidence_payload(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            with (
                patch.object(
                    blind_judge,
                    "EVIDENCE_ROOT",
                    root / "build" / "devtools" / "evidence_pack",
                ),
                patch.object(blind_judge, "LATEST_EVIDENCE_PATH", latest_summary),
                patch.object(
                    blind_judge,
                    "OUTPUT_ROOT",
                    root / "build" / "devtools" / "blind_judge",
                ),
            ):
                rc = blind_judge.main([])

            self.assertEqual(1, rc)
            output_dirs = list((root / "build" / "devtools" / "blind_judge").iterdir())
            self.assertEqual(1, len(output_dirs))
            saved = json.loads((output_dirs[0] / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual("session-close-1", saved["case_id"])
            self.assertEqual("ACTION_REQUIRED", saved["status"])


if __name__ == "__main__":
    unittest.main()
