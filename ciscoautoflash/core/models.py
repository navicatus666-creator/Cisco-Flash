from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class VersionInfo:
    version: str = ""
    image: str = ""
    model: str = ""
    uptime: str = ""


@dataclass(slots=True)
class StorageInfo:
    total_bytes: int = 0
    free_bytes: int = 0

    @property
    def total_mb(self) -> float:
        return self.total_bytes / (1024 * 1024) if self.total_bytes else 0.0

    @property
    def free_mb(self) -> float:
        return self.free_bytes / (1024 * 1024) if self.free_bytes else 0.0


@dataclass(slots=True)
class AuditCommand:
    command: str
    title: str
    wait_time: float


@dataclass(slots=True)
class OperatorMessage:
    code: str = ""
    title: str = ""
    detail: str = ""
    next_step: str = ""
    severity: str = "info"


@dataclass(slots=True)
class ConnectionTarget:
    id: str
    label: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScanResult:
    target: ConnectionTarget
    available: bool
    status_message: str
    prompt_type: str | None = None
    version: str = ""
    connection_state: str = "unknown"
    recommended_next_action: str = ""
    error_code: str = ""
    score: int = 0
    raw_preview: str = ""


@dataclass(slots=True)
class DeviceSnapshot:
    port: str = ""
    description: str = ""
    status_text: str = "Ожидание сканирования"
    connection_state: str = "idle"
    prompt_type: str = ""
    firmware: str = "Не определена"
    model: str = "Не определена"
    flash: str = "Не определена"
    uptime: str = "Не определено"
    usb_state: str = "unknown"
    recommended_next_action: str = "Выполните Scan и выберите устройство"
    is_manual_override: bool = False


@dataclass(slots=True)
class InstallStatus:
    examining: bool = False
    extracting: bool = False
    installing: bool = False
    deleting_old: bool = False
    signature_verified: bool = False
    reload_requested: bool = False

    def as_rows(self) -> list[tuple[str, bool]]:
        return [
            ("Examining", self.examining),
            ("Extracting", self.extracting),
            ("Installing", self.installing),
            ("Deleting old", self.deleting_old),
            ("Signature verified", self.signature_verified),
            ("Reload requested", self.reload_requested),
        ]
