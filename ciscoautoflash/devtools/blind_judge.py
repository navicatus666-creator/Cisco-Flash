from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = PROJECT_ROOT / "build" / "devtools" / "evidence_pack"
LATEST_EVIDENCE_PATH = EVIDENCE_ROOT / "latest_summary.json"
OUTPUT_ROOT = PROJECT_ROOT / "build" / "devtools" / "blind_judge"

SEVERITY_WEIGHT = {
    "error": 4,
    "warning": 2,
    "info": 1,
}


@dataclass(slots=True)
class RankedHypothesis:
    id: str
    summary: str
    severity: str
    status: str
    score: int
    confidence: float
    recommended_action: str
    supporting_evidence: list[str]
    contradicting_evidence: list[str]
    unknowns: list[str]


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _print_console_text(text: str) -> None:
    output = text if text.endswith("\n") else f"{text}\n"
    stream = sys.stdout
    try:
        stream.write(output)
        stream.flush()
        return
    except UnicodeEncodeError:
        pass

    encoding = getattr(stream, "encoding", None) or "utf-8"
    payload = output.encode(encoding, errors="replace")
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(payload)
        buffer.flush()
        return

    stream.write(payload.decode(encoding, errors="replace"))
    stream.flush()


def _latest_evidence_json(root: Path) -> Path | None:
    if LATEST_EVIDENCE_PATH.exists():
        return LATEST_EVIDENCE_PATH
    if not root.exists():
        return None
    for candidate in sorted(
        (path for path in root.iterdir() if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    ):
        summary_path = candidate / "summary.json"
        if summary_path.exists():
            return summary_path
    return None


def _load_evidence(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Evidence pack must contain a JSON object.")
    return payload


def _score_hypothesis(item: dict[str, Any]) -> RankedHypothesis:
    severity = str(item.get("severity", "warning"))
    status = str(item.get("status", "unknown"))
    summary = str(item.get("summary", ""))
    recommended_action = str(item.get("recommended_action", ""))
    supporting = [str(entry) for entry in item.get("supporting_evidence", [])]
    contradicting = [str(entry) for entry in item.get("contradicting_evidence", [])]
    unknowns = [str(entry) for entry in item.get("unknowns", [])]
    weight = SEVERITY_WEIGHT.get(severity, 1)

    if status == "supported":
        score = weight * 10 + len(supporting) * 3 - len(contradicting) * 2
        confidence = min(0.95, 0.48 + len(supporting) * 0.12 - len(contradicting) * 0.05)
    elif status == "mixed":
        score = weight * 6 + len(supporting) * 2 - len(contradicting) * 2
        confidence = min(0.8, 0.42 + len(supporting) * 0.08)
    elif status == "contradicted":
        score = max(0, len(supporting) - len(contradicting))
        confidence = 0.2
    else:
        score = weight * 2 if unknowns else 0
        confidence = 0.35 if unknowns else 0.15

    return RankedHypothesis(
        id=str(item.get("id", "")),
        summary=summary,
        severity=severity,
        status=status,
        score=score,
        confidence=round(max(0.0, confidence), 2),
        recommended_action=recommended_action,
        supporting_evidence=supporting,
        contradicting_evidence=contradicting,
        unknowns=unknowns,
    )


def _freshness_verdict(evidence: dict[str, Any], ranking: list[RankedHypothesis]) -> dict[str, Any]:
    hypothesis = next((item for item in ranking if item.id == "current_work_stale"), None)
    if hypothesis is None:
        return {
            "status": "unknown",
            "summary": "Current_Work freshness hypothesis was not present in the evidence pack.",
        }
    if hypothesis.status == "supported":
        return {
            "status": "stale",
            "summary": "Current_Work is stale relative to live git state.",
        }
    if hypothesis.status == "contradicted":
        return {
            "status": "fresh",
            "summary": "Current_Work matches the live git state.",
        }
    live_session_close = evidence.get("live_checks", {}).get("session_close", {})
    current_work = live_session_close.get("current_work_freshness", {})
    if current_work:
        return {
            "status": "fresh" if current_work.get("ok", False) else "unknown",
            "summary": str(current_work.get("summary", "Current_Work freshness uncertain.")),
        }
    return {
        "status": "unknown",
        "summary": "Current_Work freshness is uncertain.",
    }


def _evidence_gaps(evidence: dict[str, Any], ranking: list[RankedHypothesis]) -> list[str]:
    gaps = [str(item) for item in evidence.get("unknowns", [])]
    for item in ranking:
        if item.status == "unknown":
            gaps.append(f"unknown hypothesis: {item.id}")
        gaps.extend(item.unknowns)
    return sorted(set(gaps))


def _recommended_action(ranking: list[RankedHypothesis], *, overall_status: str) -> str:
    for item in ranking:
        if item.status in {"supported", "mixed"} and item.recommended_action:
            return item.recommended_action
    if overall_status == "CLEAR":
        return "Proceed. No supported blocking hypothesis remains."
    return "Collect more evidence before making a high-stakes decision."


def evaluate_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    ranking = sorted(
        (_score_hypothesis(item) for item in evidence.get("hypotheses", [])),
        key=lambda item: (item.score, item.confidence),
        reverse=True,
    )
    supported_errors = [
        item
        for item in ranking
        if item.status in {"supported", "mixed"} and item.severity == "error"
    ]
    supported_warnings = [
        item
        for item in ranking
        if item.status in {"supported", "mixed"} and item.severity == "warning"
    ]
    overall_status = (
        "ACTION_REQUIRED"
        if supported_errors
        else "REVIEW" if supported_warnings else "CLEAR"
    )
    freshness = _freshness_verdict(evidence, ranking)
    gaps = _evidence_gaps(evidence, ranking)
    recommended_action = _recommended_action(ranking, overall_status=overall_status)

    verdict = {
        "generated_at": _iso_now(),
        "case_id": evidence.get("case_id", ""),
        "task_type": evidence.get("task_type", ""),
        "status": overall_status,
        "blindness": {
            "seen_only": ["evidence_pack"],
            "excluded": ["repo_code", "repo_docs", "full_logs", "explorer_drafts"],
        },
        "freshness_verdict": freshness,
        "hypothesis_ranking": [asdict(item) for item in ranking],
        "recommended_action": recommended_action,
        "evidence_gaps": gaps,
        "artifacts": {
            "output_dir": "",
            "summary_json": "",
            "summary_md": "",
            "summary_toon": "",
        },
    }
    if evidence.get("task_type") == "session-close":
        verdict["close_readiness"] = {
            "status": (
                "READY"
                if overall_status == "CLEAR" and freshness["status"] == "fresh"
                else "NOT_READY"
            ),
            "summary": (
                "Session is ready to close."
                if overall_status == "CLEAR" and freshness["status"] == "fresh"
                else "Session is not ready to close."
            ),
        }
    return verdict


def render_markdown(verdict: dict[str, Any]) -> str:
    lines = [
        "# CiscoAutoFlash Blind Judge",
        "",
        f"- Case ID: `{verdict['case_id']}`",
        f"- Task type: `{verdict['task_type']}`",
        f"- Status: `{verdict['status']}`",
        f"- Generated at: `{verdict['generated_at']}`",
        f"- Freshness: `{verdict['freshness_verdict']['status']}`",
        f"- Recommended action: {verdict['recommended_action']}",
        "",
        "## Hypothesis Ranking",
        "| ID | Severity | Status | Score | Confidence | Summary |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in verdict["hypothesis_ranking"]:
        lines.append(
            f"| {item['id']} | {item['severity']} | {item['status']} | {item['score']} | "
            f"{item['confidence']} | {item['summary']} |"
        )
    lines.extend(["", "## Evidence Gaps"])
    if verdict["evidence_gaps"]:
        lines.extend([f"- {item}" for item in verdict["evidence_gaps"]])
    else:
        lines.append("- none")
    if "close_readiness" in verdict:
        lines.extend(
            [
                "",
                "## Close Readiness",
                f"- Status: `{verdict['close_readiness']['status']}`",
                f"- Summary: {verdict['close_readiness']['summary']}",
            ]
        )
    return "\n".join(lines) + "\n"


def render_toon(verdict: dict[str, Any]) -> str:
    lines = [
        "meta:",
        f"  case_id: {verdict['case_id']}",
        f"  task_type: {verdict['task_type']}",
        f"  generated_at: {verdict['generated_at']}",
        f"  status: {verdict['status']}",
        "",
        "freshness:",
        f"  status: {verdict['freshness_verdict']['status']}",
        f"  summary: {verdict['freshness_verdict']['summary']}",
        "",
        "hypothesis_ranking[]:",
        "id | severity | status | score | confidence | recommended_action",
    ]
    for item in verdict["hypothesis_ranking"]:
        lines.append(
            f"{item['id']} | {item['severity']} | {item['status']} | {item['score']} | "
            f"{item['confidence']} | {item['recommended_action'] or '—'}"
        )
    lines.extend(["", "evidence_gaps[]:", "item"])
    if verdict["evidence_gaps"]:
        lines.extend(verdict["evidence_gaps"])
    else:
        lines.append("none")
    return "\n".join(lines) + "\n"


def _write_summary_files(output_dir: Path, verdict: dict[str, Any]) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_json = output_dir / "summary.json"
    summary_md = output_dir / "summary.md"
    summary_toon = output_dir / "summary.toon"
    summary_json.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_md.write_text(render_markdown(verdict), encoding="utf-8")
    summary_toon.write_text(render_toon(verdict), encoding="utf-8")
    return summary_json, summary_md, summary_toon


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a CiscoAutoFlash evidence pack without direct repo visibility."
    )
    parser.add_argument(
        "--evidence-json",
        default="",
        help=(
            "Optional explicit evidence pack JSON path. "
            "Default uses the latest build/devtools/evidence_pack artifact."
        ),
    )
    parser.add_argument(
        "--json-out",
        default="",
        help=(
            "Optional explicit blind judge JSON output path. Default uses "
            "build/devtools/blind_judge/<timestamp>/summary.json."
        ),
    )
    args = parser.parse_args(argv)

    evidence_json = (
        Path(args.evidence_json)
        if args.evidence_json
        else _latest_evidence_json(EVIDENCE_ROOT)
    )
    if evidence_json is None or not evidence_json.exists():
        _print_console_text("No evidence pack summary.json was found.")
        return 1

    evidence = _load_evidence(evidence_json)
    verdict = evaluate_evidence(evidence)
    verdict["evidence_pack_path"] = str(evidence_json)
    output_dir = OUTPUT_ROOT / _timestamp()
    verdict["artifacts"]["output_dir"] = str(output_dir)
    verdict["artifacts"]["summary_json"] = str(output_dir / "summary.json")
    verdict["artifacts"]["summary_md"] = str(output_dir / "summary.md")
    verdict["artifacts"]["summary_toon"] = str(output_dir / "summary.toon")

    summary_json, summary_md, summary_toon = _write_summary_files(output_dir, verdict)
    if args.json_out:
        explicit_json = Path(args.json_out)
        explicit_json.parent.mkdir(parents=True, exist_ok=True)
        verdict["artifacts"]["summary_json"] = str(explicit_json)
        explicit_json.write_text(
            json.dumps(verdict, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        summary_json = explicit_json

    _print_console_text(render_markdown(verdict))
    _print_console_text(f"evidence_json: {evidence_json}")
    _print_console_text(f"summary_json: {summary_json}")
    _print_console_text(f"summary_md: {summary_md}")
    _print_console_text(f"summary_toon: {summary_toon}")
    return 0 if verdict["status"] == "CLEAR" else 1


if __name__ == "__main__":
    raise SystemExit(main())
