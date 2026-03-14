from __future__ import annotations

import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import serial
import serial.tools.list_ports

from ..config import WorkflowTiming
from .logging_utils import append_transcript_line
from .models import ConnectionTarget, ScanResult
from .transport import Transport, TransportError, TransportFactory, TransportType

PROMPT_PRIV = "Switch#"
PROMPT_USER = "Switch>"
PROMPT_REDUCED = "switch:"


class _PortLeaseRegistry:
    _guard = Lock()
    _leases: dict[str, object] = {}

    @classmethod
    def acquire(cls, port: str, owner: object) -> bool:
        with cls._guard:
            if port in cls._leases:
                return False
            cls._leases[port] = owner
            return True

    @classmethod
    def release(cls, port: str, owner: object) -> None:
        with cls._guard:
            current = cls._leases.get(port)
            if current is owner:
                cls._leases.pop(port, None)


@dataclass(slots=True)
class SerialSettings:
    baudrate: int = 9600
    bytesize: int = serial.EIGHTBITS
    parity: str = serial.PARITY_NONE
    stopbits: int = serial.STOPBITS_ONE


class SerialTransport(Transport):
    def __init__(
        self,
        port: str,
        timing: WorkflowTiming,
        settings: SerialSettings | None = None,
        transcript_path: Path | None = None,
    ):
        self.port = port
        self.timing = timing
        self.settings = settings or SerialSettings()
        self.transcript_path = transcript_path
        self._serial: serial.Serial | None = None
        self._stop_requested = False
        self._lease_owner = object()
        self._lease_acquired = False

    def connect(self) -> None:
        if self.is_connected():
            return
        if not self._lease_acquired:
            if not _PortLeaseRegistry.acquire(self.port, self._lease_owner):
                raise TransportError(f"Порт {self.port} уже используется другой активной операцией")
            self._lease_acquired = True
        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.settings.baudrate,
                bytesize=self.settings.bytesize,
                parity=self.settings.parity,
                stopbits=self.settings.stopbits,
                timeout=self.timing.serial_timeout,
                write_timeout=self.timing.serial_write_timeout,
            )
            try:
                self._serial.reset_input_buffer()
                self._serial.reset_output_buffer()
            except serial.SerialException:
                pass
        except serial.SerialException as exc:
            self._release_lease()
            raise TransportError(f"Не удалось открыть {self.port}: {exc}") from exc

    def disconnect(self) -> None:
        try:
            if self._serial is not None:
                try:
                    if self._serial.is_open:
                        self._serial.close()
                except serial.SerialException:
                    pass
        finally:
            self._serial = None
            self._release_lease()

    def write(self, data: str) -> None:
        payload = data if data.endswith("\r\n") else f"{data}\r\n"
        self.connect()
        serial_conn = self._serial
        if serial_conn is None:
            raise TransportError(f"Serial transport is not connected for {self.port}")
        display = data if data else "<ENTER>"
        if self.transcript_path is not None:
            append_transcript_line(self.transcript_path, "WRITE", display)
        try:
            serial_conn.write(payload.encode("utf-8", errors="ignore"))
        except serial.SerialException as exc:
            raise TransportError(f"Ошибка записи в {self.port}: {exc}") from exc

    def read_available(self) -> str:
        if not self.is_connected():
            return ""
        serial_conn = self._serial
        if serial_conn is None:
            return ""
        try:
            waiting = serial_conn.in_waiting
            if waiting <= 0:
                return ""
            chunk = serial_conn.read(waiting).decode("utf-8", errors="ignore")
            if chunk and self.transcript_path is not None:
                append_transcript_line(self.transcript_path, "READ", chunk)
            return chunk
        except serial.SerialException as exc:
            raise TransportError(f"Ошибка чтения из {self.port}: {exc}") from exc

    def read_until(self, markers: Sequence[str], timeout: float) -> tuple[str | None, str]:
        end_time = time.time() + timeout
        buffer = ""
        while time.time() < end_time and not self._stop_requested:
            chunk = self.read_available()
            if chunk:
                buffer += chunk
                for marker in markers:
                    if marker and marker in buffer:
                        return marker, buffer
            time.sleep(0.2)
        return None, buffer

    def send_command(self, command: str, wait: float = 1.0) -> str:
        self.flush_input()
        self.write(command)
        if wait > 0:
            time.sleep(wait)
        return self.read_available()

    def flush_input(self) -> None:
        if not self.is_connected():
            return
        serial_conn = self._serial
        if serial_conn is None:
            return
        try:
            serial_conn.reset_input_buffer()
        except serial.SerialException:
            pass

    def interrupt(self) -> None:
        self._stop_requested = True

    def reset_interrupt(self) -> None:
        self._stop_requested = False

    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def _release_lease(self) -> None:
        if self._lease_acquired:
            _PortLeaseRegistry.release(self.port, self._lease_owner)
            self._lease_acquired = False


class SerialTransportFactory(TransportFactory):
    transport_type = TransportType.SERIAL

    def __init__(self, timing: WorkflowTiming, transcript_path: Path | None = None):
        self.timing = timing
        self.transcript_path = transcript_path

    def list_targets(self) -> list[ConnectionTarget]:
        targets: list[ConnectionTarget] = []
        for port in serial.tools.list_ports.comports():
            description = port.description or ""
            manufacturer = getattr(port, "manufacturer", "") or ""
            score = self._metadata_score(description, manufacturer)
            targets.append(
                ConnectionTarget(
                    id=port.device,
                    label=port.device,
                    metadata={
                        "description": description,
                        "manufacturer": manufacturer,
                        "heuristic_score": score,
                    },
                )
            )
        targets.sort(
            key=lambda item: (
                -int(item.metadata.get("heuristic_score", 0)),
                item.id,
            )
        )
        return targets

    def probe(self, target: ConnectionTarget, markers: Sequence[str], timeout: float) -> ScanResult:
        lease_owner = object()
        if not _PortLeaseRegistry.acquire(target.id, lease_owner):
            return self._result(
                target,
                available=False,
                status_message="Порт занят другой программой или активной сессией",
                prompt_type=None,
                connection_state="busy",
                recommended_next_action=(
                    "Закройте терминал/PuTTY или дождитесь завершения другой операции "
                    "и повторите сканирование."
                ),
                error_code="port_busy",
                score=-100,
            )

        handle: serial.Serial | None = None
        buffer = ""
        try:
            handle = serial.Serial(
                port=target.id,
                baudrate=9600,
                timeout=self.timing.serial_timeout,
                write_timeout=self.timing.serial_write_timeout,
            )
            try:
                handle.reset_input_buffer()
                handle.reset_output_buffer()
            except serial.SerialException:
                pass

            start_time = time.time()
            last_ping = 0.0
            while time.time() - start_time < timeout:
                if time.time() - last_ping > 1.0:
                    handle.write(b"\r\n")
                    handle.write(b"")
                    last_ping = time.time()
                waiting = handle.in_waiting
                if waiting > 0:
                    chunk = handle.read(waiting).decode("utf-8", errors="ignore")
                    buffer += chunk
                    result = self._classify_buffer(target, buffer)
                    if result is not None:
                        return result
                time.sleep(0.2)

            stripped = buffer.strip()
            if not stripped:
                return self._result(
                    target,
                    available=False,
                    status_message="Нет ответа от устройства",
                    prompt_type=None,
                    connection_state="no_response",
                    recommended_next_action=(
                        "Проверьте питание свитча, USB-RJ45 кабель и то, что выбран "
                        "правильный COM-порт."
                    ),
                    error_code="no_response",
                    score=-20,
                )
            preview = stripped.splitlines()[-1][-120:]
            return self._result(
                target,
                available=False,
                status_message="Получены данные, но prompt не распознан",
                prompt_type="unknown",
                connection_state="unknown_prompt",
                recommended_next_action=(
                    "Нажмите ENTER ещё раз, проверьте baudrate и повторите сканирование."
                ),
                error_code="unknown_prompt",
                score=-10,
                raw_preview=preview,
            )
        except serial.SerialException as exc:
            message = str(exc)
            if "PermissionError" in message or "Access is denied" in message:
                return self._result(
                    target,
                    available=False,
                    status_message="Порт занят другой программой",
                    prompt_type=None,
                    connection_state="busy",
                    recommended_next_action=(
                        "Закройте PuTTY/терминал, освободите COM-порт и повторите сканирование."
                    ),
                    error_code="port_busy",
                    score=-100,
                )
            return self._result(
                target,
                available=False,
                status_message=f"Ошибка: {message}",
                prompt_type=None,
                connection_state="error",
                recommended_next_action="Проверьте доступность COM-порта и драйвер USB-Serial.",
                error_code="serial_error",
                score=-50,
            )
        finally:
            try:
                if handle and handle.is_open:
                    handle.close()
            except Exception:
                handle = None
            _PortLeaseRegistry.release(target.id, lease_owner)

    def create(self, target: ConnectionTarget) -> Transport:
        return SerialTransport(target.id, timing=self.timing, transcript_path=self.transcript_path)

    def _metadata_score(self, description: str, manufacturer: str) -> int:
        text = f"{description} {manufacturer}".lower()
        score = 0
        if "cisco" in text:
            score += 120
        if any(word in text for word in ("usb serial", "uart", "console", "serial")):
            score += 80
        if "com port" in text:
            score += 20
        if any(
            word in text for word in ("ftdi", "prolific", "silicon labs", "ch340", "cp210", "wch")
        ):
            score += 40
        if "bluetooth" in text:
            score -= 120
        return score

    def _combined_score(self, target: ConnectionTarget, prompt_type: str | None) -> int:
        heuristic = int(target.metadata.get("heuristic_score", 0))
        prompt_weight = {
            "priv": 100,
            "user": 80,
            "config_dialog": 60,
            "press_return": 50,
            "login": 45,
            "rommon": 35,
            "unknown": 10,
        }
        return heuristic + prompt_weight.get(prompt_type or "", 0)

    def _classify_buffer(self, target: ConnectionTarget, buffer: str) -> ScanResult | None:
        preview = buffer.strip().splitlines()[-1][-120:] if buffer.strip() else ""
        if PROMPT_PRIV in buffer:
            version = self._extract_version(buffer)
            message = "Коммутатор готов (Switch#)"
            if version:
                message += f" - FW: {version}"
            return self._result(
                target,
                available=True,
                status_message=message,
                prompt_type="priv",
                version=version,
                connection_state="ready",
                recommended_next_action="Устройство готово. Можно запускать этап 1 или этап 3.",
                error_code="",
                score=self._combined_score(target, "priv"),
                raw_preview=preview,
            )
        if PROMPT_USER in buffer:
            version = self._extract_version(buffer)
            return self._result(
                target,
                available=True,
                status_message="Устройство в пользовательском режиме (Switch>)",
                prompt_type="user",
                version=version,
                connection_state="user_mode",
                recommended_next_action=(
                    "Устройство отвечает. При запуске Stage будет выполнен переход в enable."
                ),
                error_code="",
                score=self._combined_score(target, "user"),
                raw_preview=preview,
            )
        if PROMPT_REDUCED in buffer:
            return self._result(
                target,
                available=True,
                status_message="Устройство в ROMMON режиме",
                prompt_type="rommon",
                connection_state="rommon",
                recommended_next_action=(
                    "Переведите свитч в нормальный IOS-режим или выполните recovery перед Stage 1."
                ),
                error_code="rommon",
                score=self._combined_score(target, "rommon"),
                raw_preview=preview,
            )
        if "Would you like to enter the initial configuration dialog" in buffer:
            return self._result(
                target,
                available=True,
                status_message="Активен initial config dialog",
                prompt_type="config_dialog",
                connection_state="config_dialog",
                recommended_next_action=(
                    "Ответьте 'no' в консоли или запустите Stage 1, где диалог "
                    "будет обработан автоматически."
                ),
                error_code="config_dialog",
                score=self._combined_score(target, "config_dialog"),
                raw_preview=preview,
            )
        if "Press RETURN to get started" in buffer:
            return self._result(
                target,
                available=True,
                status_message="Устройство ожидает ENTER",
                prompt_type="press_return",
                connection_state="press_return",
                recommended_next_action=(
                    "Нажмите ENTER в консоли или просто запустите Stage 1 после "
                    "повторного сканирования."
                ),
                error_code="press_return",
                score=self._combined_score(target, "press_return"),
                raw_preview=preview,
            )
        if any(
            marker in buffer for marker in ("User Access Verification", "Username:", "Password:")
        ):
            return self._result(
                target,
                available=True,
                status_message="Требуется авторизация на устройстве",
                prompt_type="login",
                connection_state="login_required",
                recommended_next_action=(
                    "Выполните вход вручную по serial и затем повторите сканирование или Stage 3."
                ),
                error_code="login_required",
                score=self._combined_score(target, "login"),
                raw_preview=preview,
            )
        if re.search(r"switch\s*$", buffer, re.IGNORECASE):
            return self._result(
                target,
                available=True,
                status_message="Обнаружен неполный prompt устройства",
                prompt_type="unknown",
                connection_state="partial_prompt",
                recommended_next_action=(
                    "Нажмите ENTER ещё раз и повторите сканирование. Если не поможет, "
                    "проверьте baudrate и состояние консоли."
                ),
                error_code="partial_prompt",
                score=self._combined_score(target, "unknown"),
                raw_preview=preview,
            )
        return None

    def _extract_version(self, buffer: str) -> str:
        match = re.search(r"Version\s+([\w()./-]+)", buffer)
        return match.group(1) if match else ""

    def _result(
        self,
        target: ConnectionTarget,
        *,
        available: bool,
        status_message: str,
        prompt_type: str | None,
        version: str = "",
        connection_state: str,
        recommended_next_action: str,
        error_code: str,
        score: int,
        raw_preview: str = "",
    ) -> ScanResult:
        return ScanResult(
            target=target,
            available=available,
            status_message=status_message,
            prompt_type=prompt_type,
            version=version,
            connection_state=connection_state,
            recommended_next_action=recommended_next_action,
            error_code=error_code,
            score=score,
            raw_preview=raw_preview,
        )
