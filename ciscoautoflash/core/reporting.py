from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ..config import SessionPaths
from ..profiles.c2960x import DeviceProfile
from .logging_utils import timestamp
from .models import InstallStatus, StorageInfo, VersionInfo


def build_install_report(
    *,
    session: SessionPaths,
    profile: DeviceProfile,
    selected_target_id: str,
    install_status: InstallStatus,
    version_info: VersionInfo,
    storage: StorageInfo,
    version_output: str,
    boot_output: str,
    dir_output: str,
    audit_results: Iterable[dict[str, str]],
) -> str:
    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("CISCO AUTOFLASH INSTALLATION REPORT")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Generated: {timestamp()}")
    lines.append(f"Profile: {profile.display_name}")
    lines.append(f"Port: {selected_target_id or 'N/A'}")
    lines.append(f"Log file: {session.log_path}")
    lines.append(f"Transcript: {session.transcript_path}")
    lines.append("")
    lines.append("-" * 80)
    lines.append("SYSTEM INFORMATION")
    lines.append("-" * 80)
    lines.append(f"Software Version: {version_info.version or 'N/A'}")
    lines.append(f"System Image: {version_info.image or 'N/A'}")
    lines.append(f"Model: {version_info.model or 'N/A'}")
    lines.append(f"Uptime: {version_info.uptime or 'N/A'}")
    if storage.total_bytes:
        lines.append(f"Flash Total: {storage.total_mb:.1f} MB")
        lines.append(f"Flash Free: {storage.free_mb:.1f} MB")
    lines.append("")
    lines.append("-" * 80)
    lines.append("INSTALLATION STAGES")
    lines.append("-" * 80)
    for title, completed in install_status.as_rows():
        marker = "COMPLETED" if completed else "NOT COMPLETED"
        lines.append(f"{title}: {marker}")
    lines.append("")
    lines.append("-" * 80)
    lines.append("SHOW VERSION OUTPUT")
    lines.append("-" * 80)
    lines.append(version_output)
    lines.append("")
    lines.append("-" * 80)
    lines.append("SHOW BOOT OUTPUT")
    lines.append("-" * 80)
    lines.append(boot_output)
    lines.append("")
    lines.append("-" * 80)
    lines.append("DIR FLASH OUTPUT")
    lines.append("-" * 80)
    lines.append(dir_output)
    lines.append("")
    lines.append("-" * 80)
    lines.append("AUDIT OUTPUT")
    lines.append("-" * 80)
    for result in audit_results:
        lines.append(result["title"])
        lines.append(result["output"])
        lines.append("")
    return "\r\n".join(lines).strip() + "\r\n"


def write_install_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", errors="replace")
