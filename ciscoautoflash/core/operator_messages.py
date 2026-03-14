from __future__ import annotations

from .models import OperatorMessage, ScanResult


def message_from_scan_result(result: ScanResult) -> OperatorMessage:
    severity = (
        "info"
        if result.available and not result.error_code
        else "warn"
        if result.available
        else "error"
    )
    detail = result.raw_preview or result.target.label or result.target.id
    return OperatorMessage(
        code=result.error_code or result.connection_state,
        title=result.status_message or "Статус устройства обновлён",
        detail=detail,
        next_step=result.recommended_next_action
        or "Повторите сканирование или выберите другое устройство.",
        severity=severity,
    )


def message_from_exception(exc: BaseException) -> OperatorMessage:
    text = str(exc).strip() or exc.__class__.__name__
    lowered = text.lower()
    mapping = [
        (
            "enable password",
            "enable_password",
            "Требуется enable password",
            "Выполните вход вручную или используйте устройство без enable password.",
        ),
        (
            "rommon",
            "rommon",
            "Устройство в ROMMON режиме",
            "Переведите свитч в normal IOS mode или выполните recovery.",
        ),
        (
            "не найден на usb",
            "firmware_missing",
            "Файл образа не найден",
            "Проверьте имя файла и содержимое usbflash0:/usbflash1:.",
        ),
        (
            "timeout",
            "timeout",
            "Операция превысила таймаут",
            "Повторите шаг и проверьте реальное состояние устройства.",
        ),
        (
            "таймаут",
            "timeout",
            "Операция превысила таймаут",
            "Повторите шаг и проверьте реальное состояние устройства.",
        ),
        (
            "not found",
            "not_found",
            "Требуемый ресурс не найден",
            "Проверьте входные данные и доступность файла или устройства.",
        ),
    ]
    for needle, code, title, next_step in mapping:
        if needle in lowered:
            return OperatorMessage(
                code=code,
                title=title,
                detail=text,
                next_step=next_step,
                severity="error",
            )
    return OperatorMessage(
        code="runtime_error",
        title="Ошибка выполнения",
        detail=text,
        next_step="Проверьте журнал, транскрипт и затем повторите операцию.",
        severity="error",
    )


def message_for_stop() -> OperatorMessage:
    return OperatorMessage(
        code="stopped",
        title="Операция остановлена",
        detail="Текущая операция была остановлена пользователем.",
        next_step="Проведите повторное сканирование и запустите нужный этап заново.",
        severity="warn",
    )


def info_message(title: str, detail: str, next_step: str) -> OperatorMessage:
    return OperatorMessage(
        code="info",
        title=title,
        detail=detail,
        next_step=next_step,
        severity="info",
    )
