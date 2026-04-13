from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VAULT_ROOT = PROJECT_ROOT / "OBSMEM"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "build" / "devtools" / "memory_lint"
IMPORTANT_DIRS = {"analyses", "concepts", "decisions", "mirrors", "projects", "sources"}
SYSTEM_FILENAMES = {"index.md", "log.md", "AGENTS.md"}
VALID_TYPES = {
    "analysis",
    "concept",
    "decision",
    "mirror",
    "project-note",
    "source-summary",
}
VALID_STATUS = {"active", "draft", "superseded", "archived"}
SPECIAL_ROOT_TARGETS = {
    "readme": "README.md",
    "agents": "AGENTS.md",
    "index": "index.md",
    "log": "log.md",
}

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
HEADING_RE = re.compile(r"(?ms)^##\s+Read next\s*$\n(.*?)(?=^##\s+|\Z)")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(slots=True)
class PageRecord:
    path: Path
    rel_path: str
    title: str
    type: str
    status: str
    source_of_truth: str
    aliases: list[str] = field(default_factory=list)
    repo_refs: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    last_verified: str = ""
    body: str = ""
    has_frontmatter: bool = False
    outbound: set[str] = field(default_factory=set)
    inbound: set[str] = field(default_factory=set)
    canonical_names: set[str] = field(default_factory=set)
    read_next_links: list[str] = field(default_factory=list)
    internal_links: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Finding:
    severity: str
    code: str
    path: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


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


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _strip_wrappers(value: str) -> str:
    text = value.strip().strip('"').strip("'")
    if text.startswith("[[") and text.endswith("]]"):
        text = text[2:-2]
    if "|" in text:
        text = text.split("|", 1)[0]
    if "#" in text:
        text = text.split("#", 1)[0]
    return text.strip()


def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str, bool]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text, False
    block, body = match.groups()
    data: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line.startswith("  - ") and current_key:
            data.setdefault(current_key, [])
            if not isinstance(data[current_key], list):
                data[current_key] = [data[current_key]]
            data[current_key].append(_strip_wrappers(stripped[2:].strip()))
            continue
        if ":" in line and not line.startswith("  "):
            key, value = line.split(":", 1)
            current_key = key.strip()
            value = value.strip()
            if value == "" or value == "[]":
                data[current_key] = []
            else:
                data[current_key] = value.strip().strip('"').strip("'")
    return data, body, True


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text == "[]":
        return []
    return [text]


def _is_important_page(path: Path, vault_root: Path) -> bool:
    rel = path.relative_to(vault_root)
    if rel.name in SYSTEM_FILENAMES:
        return False
    if rel.parts and rel.parts[0] in IMPORTANT_DIRS:
        return True
    return rel.name == "README.md" and len(rel.parts) == 1


def _page_title(body: str, fallback: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def _extract_read_next_links(body: str, vault_root: Path) -> list[str]:
    match = HEADING_RE.search(body)
    if not match:
        return []
    section = match.group(1)
    return _extract_internal_links(section, vault_root)


def _extract_internal_links(text: str, vault_root: Path) -> list[str]:
    links: list[str] = []
    for match in WIKILINK_RE.finditer(text):
        raw = match.group(1)
        target = _strip_wrappers(raw)
        if target:
            links.append(target)
    for match in MD_LINK_RE.finditer(text):
        href = match.group(1).strip()
        if href.startswith(("http://", "https://", "mailto:", "obsidian://")):
            continue
        href = href.split("#", 1)[0].strip()
        if not href:
            continue
        candidate = Path(href)
        if candidate.is_absolute():
            if candidate.exists() and vault_root in candidate.parents:
                links.append(str(candidate))
            continue
        resolved = (vault_root / candidate).with_suffix(candidate.suffix or ".md")
        if resolved.exists():
            links.append(str(resolved))
    return links


def _resolve_note_target(
    target: str,
    *,
    vault_root: Path,
    path_index: dict[str, list[Path]],
) -> list[Path]:
    cleaned = _strip_wrappers(target)
    if not cleaned:
        return []

    raw_path = Path(cleaned)
    if raw_path.is_absolute() and raw_path.exists() and vault_root in raw_path.parents:
        return [raw_path]

    key = _normalize_name(cleaned)
    if not key:
        return []
    if key in SPECIAL_ROOT_TARGETS:
        special = vault_root / SPECIAL_ROOT_TARGETS[key]
        return [special] if special.exists() else []

    direct = path_index.get(key, [])
    if direct:
        return direct

    if "/" in cleaned or "\\" in cleaned:
        rel_candidate = (vault_root / cleaned).with_suffix(".md")
        if rel_candidate.exists():
            return [rel_candidate]
        rel_candidate = vault_root / cleaned
        if rel_candidate.exists():
            return [rel_candidate]
    return []


def _page_key_candidates(page: PageRecord) -> set[str]:
    keys: set[str] = set()
    rel_without_suffix = Path(page.rel_path).with_suffix("")
    keys.add(_normalize_name(rel_without_suffix.as_posix()))
    if page.title:
        keys.add(_normalize_name(page.title))
    for alias in page.aliases:
        keys.add(_normalize_name(alias))
    if not page.title and not page.aliases:
        keys.add(_normalize_name(Path(page.rel_path).stem))
    return {key for key in keys if key}


def _collect_pages(vault_root: Path) -> list[PageRecord]:
    pages: list[PageRecord] = []
    for path in sorted(vault_root.rglob("*.md")):
        if ".obsidian" in path.parts:
            continue
        if not _is_important_page(path, vault_root):
            continue
        text = _load_text(path)
        frontmatter, body, has_frontmatter = _parse_frontmatter(text)
        rel_path = path.relative_to(vault_root).as_posix()
        title = _page_title(body, Path(rel_path).stem)
        page = PageRecord(
            path=path,
            rel_path=rel_path,
            title=title,
            type=str(frontmatter.get("type", "")).strip(),
            status=str(frontmatter.get("status", "")).strip(),
            source_of_truth=str(frontmatter.get("source_of_truth", "")).strip(),
            aliases=_as_list(frontmatter.get("aliases")),
            repo_refs=_as_list(frontmatter.get("repo_refs")),
            related=_as_list(frontmatter.get("related")),
            last_verified=str(frontmatter.get("last_verified", "")).strip(),
            body=body,
            has_frontmatter=has_frontmatter,
        )
        page.canonical_names = _page_key_candidates(page)
        page.read_next_links = _extract_read_next_links(body, vault_root)
        page.internal_links = _extract_internal_links(body, vault_root)
        pages.append(page)
    return pages


def _lint_page(page: PageRecord, *, stale_days: int, today: date) -> list[Finding]:
    findings: list[Finding] = []
    prefix = page.rel_path

    if not page.has_frontmatter:
        findings.append(
            Finding(
                severity="error",
                code="missing_frontmatter",
                path=prefix,
                message="Important page is missing mandatory frontmatter.",
            )
        )
        return findings

    if page.type not in VALID_TYPES:
        findings.append(
            Finding(
                severity="error",
                code="invalid_type",
                path=prefix,
                message=f"Invalid type '{page.type}' in frontmatter.",
            )
        )
    if page.status not in VALID_STATUS:
        findings.append(
            Finding(
                severity="error",
                code="invalid_status",
                path=prefix,
                message=f"Invalid status '{page.status}' in frontmatter.",
            )
        )
    if page.source_of_truth != "repo":
        findings.append(
            Finding(
                severity="error",
                code="invalid_source_of_truth",
                path=prefix,
                message="source_of_truth must be repo for important OBSMEM pages.",
            )
        )
    if not page.repo_refs:
        findings.append(
            Finding(
                severity="error",
                code="missing_repo_refs",
                path=prefix,
                message="Important page is missing repo_refs.",
            )
        )
    if not page.related:
        findings.append(
            Finding(
                severity="error",
                code="missing_related",
                path=prefix,
                message="Important page is missing related links.",
            )
        )
    if not page.read_next_links:
        findings.append(
            Finding(
                severity="error",
                code="missing_read_next",
                path=prefix,
                message="Important page is missing Read next links.",
            )
        )
    if not page.last_verified:
        findings.append(
            Finding(
                severity="error",
                code="missing_last_verified",
                path=prefix,
                message="Important page is missing last_verified.",
            )
        )
    elif not DATE_RE.match(page.last_verified):
        findings.append(
            Finding(
                severity="error",
                code="invalid_last_verified",
                path=prefix,
                message="last_verified must use YYYY-MM-DD.",
            )
        )
    else:
        verified_date = date.fromisoformat(page.last_verified)
        age = (today - verified_date).days
        if age > stale_days:
            findings.append(
                Finding(
                    severity="warning",
                    code="stale_last_verified",
                    path=prefix,
                    message=(
                        f"last_verified is {age} days old; threshold is {stale_days} days."
                    ),
                    details={"age_days": age, "threshold_days": stale_days},
                )
            )

    if page.type == "mirror":
        if not page.repo_refs:
            findings.append(
                Finding(
                    severity="error",
                    code="stale_mirror_missing_refs",
                    path=prefix,
                    message="Mirror page is missing repo_refs.",
                )
            )
        if page.last_verified and DATE_RE.match(page.last_verified):
            verified_date = date.fromisoformat(page.last_verified)
            age = (today - verified_date).days
            if age > stale_days:
                findings.append(
                    Finding(
                        severity="warning",
                        code="stale_mirror",
                        path=prefix,
                        message=f"Mirror page was last verified {age} days ago.",
                        details={"age_days": age, "threshold_days": stale_days},
                    )
                )

    for ref in page.repo_refs:
        candidate = Path(ref)
        if not candidate.exists():
            findings.append(
                Finding(
                    severity="error",
                    code="broken_repo_ref",
                    path=prefix,
                    message=f"repo_ref does not exist: {ref}",
                    details={"repo_ref": ref},
                )
            )

    if page.path.name != "README.md" and not page.inbound:
        findings.append(
            Finding(
                severity="warning",
                code="orphan_page",
                path=prefix,
                message="Page has no inbound internal links.",
            )
        )

    return findings


def _duplicate_findings(pages: list[PageRecord]) -> list[Finding]:
    clusters: dict[str, list[PageRecord]] = {}
    for page in pages:
        for key in page.canonical_names:
            clusters.setdefault(key, []).append(page)

    findings: list[Finding] = []
    for key, cluster in sorted(clusters.items()):
        unique_paths = {page.rel_path for page in cluster}
        if len(unique_paths) <= 1:
            continue
        titles = sorted({page.title for page in cluster})
        findings.append(
            Finding(
                severity="warning",
                code="duplicate_canonical_topic",
                path="; ".join(sorted(unique_paths)),
                message=(
                    f"Canonical topic '{titles[0] if titles else key}' appears on "
                    "multiple pages."
                ),
                details={
                    "canonical_name": key,
                    "pages": sorted(unique_paths),
                    "titles": titles,
                },
            )
        )
    return findings


def _write_summary_files(output_dir: Path, summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "summary.json"
    md_path = output_dir / "summary.md"
    findings = summary["findings"]
    lines = [
        "# OBSMEM Memory Lint",
        "",
        f"- Status: {summary['status']}",
        f"- Vault root: {summary['vault_root']}",
        f"- Pages scanned: {summary['pages_scanned']}",
        f"- Important pages scanned: {summary['important_pages_scanned']}",
        f"- Errors: {summary['error_count']}",
        f"- Warnings: {summary['warning_count']}",
        f"- Stale threshold days: {summary['stale_days']}",
        "",
        "## Findings",
        "| Severity | Code | Page | Message |",
        "| --- | --- | --- | --- |",
    ]
    if findings:
        for item in findings:
            lines.append(
                f"| {item['severity']} | {item['code']} | {item['path']} | {item['message']} |"
            )
    else:
        lines.append("| info | clean | — | No issues found. |")

    pages = summary["pages"]
    if pages:
        lines.extend(
            [
                "",
                "## Pages",
                "| Page | Type | Verified | Inbound | Outbound |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for page in pages:
            lines.append(
                f"| {page['path']} | {page['type']} | {page['last_verified'] or '—'} | "
                f"{page['inbound_internal_count']} | {page['outbound_internal_count']} |"
            )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary["output_dir"] = str(output_dir)
    summary["summary_json"] = str(json_path)
    summary["summary_md"] = str(md_path)
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def lint_obsmem(
    vault_root: Path = DEFAULT_VAULT_ROOT,
    *,
    stale_days: int = 60,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    today: date | None = None,
) -> dict[str, Any]:
    if not vault_root.exists():
        raise FileNotFoundError(f"OBSMEM vault not found: {vault_root}")

    page_records = _collect_pages(vault_root)
    pages_by_path = {page.path.resolve(): page for page in page_records}
    path_index: dict[str, list[Path]] = {}
    for page in page_records:
        for key in page.canonical_names:
            path_index.setdefault(key, []).append(page.path.resolve())

    for page in page_records:
        targets: list[str] = []
        targets.extend(page.related)
        targets.extend(page.read_next_links)
        targets.extend(page.internal_links)
        for target in targets:
            for resolved in _resolve_note_target(
                target,
                vault_root=vault_root,
                path_index=path_index,
            ):
                target_page = pages_by_path.get(resolved.resolve())
                if target_page is None:
                    continue
                if target_page.path.resolve() == page.path.resolve():
                    continue
                page.outbound.add(target_page.rel_path)
                target_page.inbound.add(page.rel_path)

    check_date = today or datetime.now(UTC).date()
    findings: list[Finding] = []
    for page in page_records:
        findings.extend(_lint_page(page, stale_days=stale_days, today=check_date))
    findings.extend(_duplicate_findings(page_records))

    error_count = sum(1 for item in findings if item.severity == "error")
    warning_count = sum(1 for item in findings if item.severity == "warning")
    status = "PASS" if error_count == 0 and warning_count == 0 else "WARN"

    page_summaries = [
        {
            "path": page.rel_path,
            "type": page.type,
            "status": page.status,
            "title": page.title,
            "aliases": page.aliases,
            "repo_refs": page.repo_refs,
            "related": page.related,
            "last_verified": page.last_verified,
            "inbound_internal_count": len(page.inbound),
            "outbound_internal_count": len(page.outbound),
            "has_read_next": bool(page.read_next_links),
        }
        for page in page_records
    ]
    summary: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "vault_root": str(vault_root),
        "stale_days": stale_days,
        "pages_scanned": len(page_records),
        "important_pages_scanned": len(page_records),
        "error_count": error_count,
        "warning_count": warning_count,
        "status": status,
        "findings": [asdict(item) for item in findings],
        "pages": page_summaries,
    }

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    run_dir = output_root / timestamp
    _write_summary_files(run_dir, summary)
    summary["output_dir"] = str(run_dir)
    summary["summary_json"] = str(run_dir / "summary.json")
    summary["summary_md"] = str(run_dir / "summary.md")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint the OBSMEM wiki layer.")
    parser.add_argument(
        "--vault",
        type=Path,
        default=DEFAULT_VAULT_ROOT,
        help="Path to the OBSMEM vault root.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Base directory for lint reports.",
    )
    parser.add_argument(
        "--stale-days",
        type=int,
        default=60,
        help="Warn when last_verified is older than this many days.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return exit code 1 when any errors are found.",
    )
    args = parser.parse_args(argv)

    summary = lint_obsmem(
        args.vault,
        stale_days=args.stale_days,
        output_root=args.output_root,
    )
    _print_console_text("OBSMEM Memory Lint")
    _print_console_text(
        f"- Status: {summary['status']} | Errors: {summary['error_count']} | "
        f"Warnings: {summary['warning_count']}"
    )
    _print_console_text(f"- Output: {summary['summary_md']}")
    if summary["findings"]:
        for item in summary["findings"][:12]:
            _print_console_text(
                f"  - [{item['severity']}] {item['code']} :: {item['path']} :: {item['message']}"
            )
    return 1 if args.strict and summary["error_count"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
