from __future__ import annotations

from .models import DeviceSnapshot, ScanResult


def snapshot_from_scan_result(result: ScanResult, *, manual_override: bool) -> DeviceSnapshot:
    return DeviceSnapshot(
        port=result.target.id,
        description=str(result.target.metadata.get("description", "")),
        status_text=result.status_message,
        connection_state=result.connection_state,
        prompt_type=result.prompt_type or "",
        firmware=result.version or "Не определена",
        model="Не определена",
        flash="Не определена",
        uptime="Не определено",
        usb_state="unknown",
        recommended_next_action=result.recommended_next_action
        or "Повторите сканирование и выберите устройство.",
        is_manual_override=manual_override,
    )


def empty_snapshot(*, status_text: str, next_step: str) -> DeviceSnapshot:
    return DeviceSnapshot(status_text=status_text, recommended_next_action=next_step)
