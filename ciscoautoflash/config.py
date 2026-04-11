from __future__ import annotations

import json
import os
import sys
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
    sessions_dir: Path
    session_dir: Path
    session_id: str
    started_at: datetime
    log_path: Path
    report_path: Path
    transcript_path: Path
    settings_path: Path
    settings_snapshot_path: Path
    manifest_path: Path
    bundle_path: Path
    event_timeline_path: Path
    dashboard_snapshot_path: Path | None


@dataclass(slots=True)
class AppSettings:
    firmware_name: str = ""
    preferred_target_id: str = ""
    selected_transport: str = "serial"
    demo_scenario_name: str = ""
    window_geometry: str = ""


@dataclass(slots=True)
class AppConfig:
    app_name: str = "CiscoAutoFlash"
    app_version: str = "4.1"
    theme_name: str = "litera"
    project_root: Path = field(default_factory=lambda: default_project_root())
    runtime_root: Path = field(default_factory=lambda: default_runtime_root())
    timing: WorkflowTiming = field(default_factory=WorkflowTiming)

    def create_session_paths(self) -> SessionPaths:
        base_dir = self._resolve_runtime_base_dir()
        try:
            logs_dir, reports_dir, transcripts_dir, sessions_dir, settings_dir = (
                self._ensure_runtime_directories(base_dir)
            )
        except FileExistsError:
            base_dir = self.runtime_root / "_runtime"
            logs_dir, reports_dir, transcripts_dir, sessions_dir, settings_dir = (
                self._ensure_runtime_directories(base_dir)
            )
        started_at = datetime.now()
        session_id = started_at.strftime("%Y%m%d_%H%M%S")
        session_dir = sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return SessionPaths(
            base_dir=base_dir,
            logs_dir=logs_dir,
            reports_dir=reports_dir,
            transcripts_dir=transcripts_dir,
            sessions_dir=sessions_dir,
            session_dir=session_dir,
            session_id=session_id,
            started_at=started_at,
            log_path=logs_dir / f"ciscoautoflash_{session_id}.log",
            report_path=reports_dir / f"install_report_{session_id}.txt",
            transcript_path=transcripts_dir / f"transcript_{session_id}.log",
            settings_path=settings_dir / "settings.json",
            settings_snapshot_path=session_dir / "settings_snapshot.json",
            manifest_path=session_dir / "session_manifest.json",
            bundle_path=session_dir / f"session_bundle_{session_id}.zip",
            event_timeline_path=session_dir / "event_timeline.json",
            dashboard_snapshot_path=None,
        )

    def _resolve_runtime_base_dir(self) -> Path:
        if self.runtime_root.exists() and not self.runtime_root.is_dir():
            return self.runtime_root.parent / f"{self.runtime_root.name}_runtime"
        conflict_names = ("logs", "reports", "transcripts", "sessions", "settings")
        has_conflicts = any(
            (self.runtime_root / name).exists() and not (self.runtime_root / name).is_dir()
            for name in conflict_names
        )
        if has_conflicts:
            return self.runtime_root / "_runtime"
        return self.runtime_root

    def _ensure_runtime_directories(self, base_dir: Path) -> tuple[Path, Path, Path, Path, Path]:
        logs_dir = base_dir / "logs"
        reports_dir = base_dir / "reports"
        transcripts_dir = base_dir / "transcripts"
        sessions_dir = base_dir / "sessions"
        settings_dir = base_dir / "settings"
        for path in (
            base_dir,
            logs_dir,
            reports_dir,
            transcripts_dir,
            sessions_dir,
            settings_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return logs_dir, reports_dir, transcripts_dir, sessions_dir, settings_dir


def default_runtime_root() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "CiscoAutoFlash"
    return Path.home() / ".ciscoautoflash"


def default_project_root() -> Path:
    if getattr(sys, "frozen", False):
        bundle_root = getattr(sys, "_MEIPASS", "")
        if bundle_root:
            return Path(bundle_root)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


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
        demo_scenario_name=str(data.get("demo_scenario_name", "")),
        window_geometry=str(data.get("window_geometry", "")),
    )


def save_settings(path: Path, settings: AppSettings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
