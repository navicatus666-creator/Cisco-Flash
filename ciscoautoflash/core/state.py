from __future__ import annotations

from enum import StrEnum


class WorkflowState(StrEnum):
    IDLE = "IDLE"
    DISCOVERING = "DISCOVERING"
    CONNECTING = "CONNECTING"
    PRECHECK = "PRECHECK"
    ERASING = "ERASING"
    INSTALLING = "INSTALLING"
    REBOOTING = "REBOOTING"
    VERIFYING = "VERIFYING"
    DONE = "DONE"
    FAILED = "FAILED"
