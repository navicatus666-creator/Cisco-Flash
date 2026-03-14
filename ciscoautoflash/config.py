from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class WorkflowTiming:
    serial_timeout: float = 1.0
    serial_write_timeout: float = 1.0
    command_wait_short: float = 1.0
    command_wait_medium: float = 2.0
    command_wait_long: float = 4.0
    prompt_timeout: float = 15.0
    enable_timeout: float = 10.0
    reload_confirm_timeout: float = 3.0
    stage1_prompt_timeout: float = 300.0
    install_timeout: float = 2400.0
    install_quiet_success: float = 90.0
    stage2_prompt_timeout: float = 900.0
    scan_probe_timeout: float = 10.0
    heartbeat_interval: float = 30.0


@dataclass(slots=True)
class SessionPaths:
    base_dir: Path
    logs_dir: Path
    reports_dir: Path
    transcripts_dir: Path
    session_id: str
    log_path: Path
    report_path: Path
    transcript_path: Path
    settings_path: Path


@dataclass(slots=True)
class AppSettings:
    firmware_name: str = ""
    preferred_target_id: str = ""
    selected_transport: str = "serial"
    window_geometry: str = ""


@dataclass(slots=True)
class AppConfig:
    app_name: str = "CiscoAutoFlash"
    app_version: str = "4.1"
    theme_name: str = "litera"
    project_root: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    runtime_root: Path = field(default_factory=lambda: default_runtime_root())
    timing: WorkflowTiming = field(default_factory=WorkflowTiming)

    def create_session_paths(self) -> SessionPaths:
        logs_dir = self.runtime_root / "logs"
        reports_dir = self.runtime_root / "reports"
        transcripts_dir = self.runtime_root / "transcripts"
        settings_dir = self.runtime_root / "settings"
        for path in (self.runtime_root, logs_dir, reports_dir, transcripts_dir, settings_dir):
            path.mkdir(parents=True, exist_ok=True)
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        return SessionPaths(
            base_dir=self.runtime_root,
            logs_dir=logs_dir,
            reports_dir=reports_dir,
            transcripts_dir=transcripts_dir,
            session_id=session_id,
            log_path=logs_dir / f"ciscoautoflash_{session_id}.log",
            report_path=reports_dir / f"install_report_{session_id}.txt",
            transcript_path=transcripts_dir / f"transcript_{session_id}.log",
            settings_path=settings_dir / "settings.json",
        )


def default_runtime_root() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "CiscoAutoFlash"
    return Path.home() / ".ciscoautoflash"


def load_settings(path: Path) -> AppSettings:
    if not path.exists():
        return AppSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return AppSettings()
    return AppSettings(
        firmware_name=str(data.get("firmware_name", "")),
        preferred_target_id=str(data.get("preferred_target_id", "")),
        selected_transport=str(data.get("selected_transport", "serial")),
        window_geometry=str(data.get("window_geometry", "")),
    )


def save_settings(path: Path, settings: AppSettings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
