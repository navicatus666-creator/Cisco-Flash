from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ..config import WorkflowTiming
from .logging_utils import append_transcript_line
from .models import ConnectionTarget, ScanResult
from .transport import Transport, TransportError, TransportFactory, TransportType


class SshTransport(Transport):
    def __init__(
        self,
        target: ConnectionTarget,
        timing: WorkflowTiming,
        transcript_path: Path | None = None,
    ) -> None:
        self.target = target
        self.timing = timing
        self.transcript_path = transcript_path
        self._connection: Any | None = None
        self._stop_requested = False

    def connect(self) -> None:
        if self.is_connected():
            return
        params = self._connection_params()
        ConnectHandler, _, _, _ = _load_netmiko()
        try:
            self._connection = ConnectHandler(**params)
        except Exception as exc:  # pragma: no cover - exercised via factory probe mapping
            raise _map_ssh_exception(exc) from exc
        self._append_transcript("CONNECT", f"{params['host']}:{params['port']}")

    def disconnect(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.disconnect()
        except Exception as exc:  # pragma: no cover - cleanup path
            raise TransportError(f"SSH disconnect failed for {self.target.id}: {exc}") from exc
        finally:
            self._connection = None

    def write(self, data: str) -> None:
        connection = self._require_connection()
        payload = data if data.endswith("\n") else f"{data}\n"
        display = data if data else "<ENTER>"
        self._append_transcript("WRITE", display)
        try:
            connection.write_channel(payload)
        except Exception as exc:
            raise TransportError(f"SSH write failed for {self.target.id}: {exc}") from exc

    def read_available(self) -> str:
        if not self.is_connected():
            return ""
        connection = self._require_connection()
        try:
            chunk = connection.read_channel()
        except Exception as exc:
            raise TransportError(f"SSH read failed for {self.target.id}: {exc}") from exc
        if chunk:
            self._append_transcript("READ", chunk.rstrip())
        return chunk

    def read_until(self, markers: Sequence[str], timeout: float) -> tuple[str | None, str]:
        deadline = time.time() + timeout
        buffer = ""
        while time.time() < deadline:
            self._ensure_not_interrupted()
            chunk = self.read_available()
            if chunk:
                buffer += chunk
                for marker in markers:
                    if marker and marker in buffer:
                        return marker, buffer
            else:
                time.sleep(0.1)
        return None, buffer

    def send_command(self, command: str, wait: float = 1.0) -> str:
        connection = self._require_connection()
        self._ensure_not_interrupted()
        self._append_transcript("WRITE", command)
        read_timeout = max(wait + 5.0, self.timing.prompt_timeout)
        try:
            output = connection.send_command_timing(
                command,
                last_read=max(wait, 0.1),
                read_timeout=read_timeout,
                strip_prompt=False,
                strip_command=False,
            )
        except Exception as exc:
            raise TransportError(f"SSH command failed for {self.target.id}: {exc}") from exc
        if output:
            self._append_transcript("READ", output.rstrip())
        return output

    def interrupt(self) -> None:
        self._stop_requested = True

    def reset_interrupt(self) -> None:
        self._stop_requested = False

    def is_connected(self) -> bool:
        if self._connection is None:
            return False
        is_alive = getattr(self._connection, "is_alive", None)
        if callable(is_alive):
            try:
                status = is_alive()
            except Exception:
                return True
            if isinstance(status, dict):
                return bool(status.get("is_alive", True))
            return bool(status)
        return True

    def upload_file(
        self,
        source_file: str,
        *,
        dest_file: str | None = None,
        file_system: str | None = None,
        overwrite_file: bool = True,
    ) -> dict[str, Any]:
        connection = self._require_connection()
        _, file_transfer, _, _ = _load_netmiko()
        destination = dest_file or Path(source_file).name
        resolved_file_system = file_system or str(
            self.target.metadata.get("file_system", "flash:")
        )
        try:
            result = file_transfer(
                connection,
                source_file=source_file,
                dest_file=destination,
                file_system=resolved_file_system,
                direction="put",
                overwrite_file=overwrite_file,
            )
        except Exception as exc:
            raise TransportError(f"SSH file upload failed for {self.target.id}: {exc}") from exc
        self._append_transcript("SCP", f"{source_file} -> {resolved_file_system}{destination}")
        return dict(result)

    def find_prompt(self) -> str:
        connection = self._require_connection()
        try:
            prompt = connection.find_prompt()
        except Exception as exc:
            raise TransportError(
                f"Failed to detect SSH prompt for {self.target.id}: {exc}"
            ) from exc
        self._append_transcript("READ", prompt)
        return prompt

    def _connection_params(self) -> dict[str, Any]:
        metadata = self.target.metadata
        host = str(metadata.get("host", "")).strip()
        username = str(metadata.get("username", "")).strip()
        password = str(metadata.get("password", ""))
        if not host:
            raise TransportError("SSH target is missing host/IP in target metadata")
        if not username or not password:
            raise TransportError("SSH target is missing username/password in target metadata")
        return {
            "device_type": str(metadata.get("device_type", "cisco_ios")),
            "host": host,
            "username": username,
            "password": password,
            "secret": str(metadata.get("secret", "")),
            "port": int(metadata.get("port", 22)),
            "conn_timeout": float(metadata.get("timeout", self.timing.prompt_timeout)),
            "banner_timeout": float(metadata.get("banner_timeout", self.timing.prompt_timeout)),
            "auth_timeout": float(metadata.get("auth_timeout", self.timing.enable_timeout)),
            "session_timeout": float(
                metadata.get("session_timeout", max(30.0, self.timing.stage2_prompt_timeout))
            ),
            "fast_cli": False,
        }

    def _require_connection(self) -> Any:
        if not self.is_connected() or self._connection is None:
            raise TransportError(f"SSH transport is not connected for {self.target.id}")
        return self._connection

    def _ensure_not_interrupted(self) -> None:
        if self._stop_requested:
            raise TransportError("SSH operation interrupted by operator")

    def _append_transcript(self, direction: str, payload: str) -> None:
        if self.transcript_path is None or not payload:
            return
        append_transcript_line(self.transcript_path, direction, payload)


class SshTransportFactory(TransportFactory):
    transport_type = TransportType.SSH

    def __init__(
        self,
        timing: WorkflowTiming,
        targets: list[ConnectionTarget] | None = None,
        transcript_path: Path | None = None,
    ) -> None:
        self.timing = timing
        self.targets = list(targets or [])
        self.transcript_path = transcript_path

    def list_targets(self) -> list[ConnectionTarget]:
        return list(self.targets)

    def probe(self, target: ConnectionTarget, markers: Sequence[str], timeout: float) -> ScanResult:
        if not str(target.metadata.get("host", "")).strip():
            return _probe_result(
                target,
                available=False,
                status_message="SSH target is missing host/IP",
                prompt_type=None,
                connection_state="error",
                recommended_next_action="Укажите host/IP для SSH цели и повторите попытку.",
                error_code="missing_host",
                score=-100,
            )
        transport = self.create(target)
        try:
            transport.connect()
            prompt = transport.find_prompt()
            return _scan_result_from_prompt(target, prompt, markers)
        except TransportError as exc:
            message = str(exc)
            lowered = message.lower()
            if "username/password" in lowered or "authentication" in lowered or "auth" in lowered:
                return _probe_result(
                    target,
                    available=False,
                    status_message="Требуется валидная SSH-аутентификация",
                    prompt_type="login",
                    connection_state="login_required",
                    recommended_next_action=(
                        "Проверьте username/password/secret и повторите попытку."
                    ),
                    error_code="login_required",
                    score=-60,
                    raw_preview=message,
                )
            if "timeout" in lowered:
                return _probe_result(
                    target,
                    available=False,
                    status_message="SSH-устройство не отвечает вовремя",
                    prompt_type=None,
                    connection_state="timeout",
                    recommended_next_action="Проверьте IP, доступность SSH и сетевой маршрут.",
                    error_code="ssh_timeout",
                    score=-50,
                    raw_preview=message,
                )
            return _probe_result(
                target,
                available=False,
                status_message=f"SSH probe failed: {message}",
                prompt_type=None,
                connection_state="error",
                recommended_next_action="Проверьте параметры SSH-цели и повторите попытку.",
                error_code="ssh_error",
                score=-40,
                raw_preview=message,
            )
        finally:
            try:
                transport.disconnect()
            except Exception:
                _ = transport

    def create(self, target: ConnectionTarget) -> SshTransport:
        return SshTransport(target, timing=self.timing, transcript_path=self.transcript_path)


def _load_netmiko():
    try:
        from netmiko import ConnectHandler, file_transfer
        from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise TransportError(
            "SSH dependencies are not installed. Install the project with ciscoautoflash[ssh]."
        ) from exc
    return ConnectHandler, file_transfer, NetmikoAuthenticationException, NetmikoTimeoutException


def _map_ssh_exception(exc: Exception) -> TransportError:
    _, _, auth_exc, timeout_exc = _load_netmiko()
    if isinstance(exc, auth_exc):
        return TransportError(f"SSH authentication failed: {exc}")
    if isinstance(exc, timeout_exc):
        return TransportError(f"SSH connection timeout: {exc}")
    return TransportError(f"SSH transport error: {exc}")


def _scan_result_from_prompt(
    target: ConnectionTarget,
    prompt: str,
    markers: Sequence[str],
) -> ScanResult:
    prompt = prompt.strip()
    if prompt.endswith("#") or (markers and markers[0] and markers[0] in prompt):
        return _probe_result(
            target,
            available=True,
            status_message="SSH устройство готово (privileged prompt)",
            prompt_type="priv",
            connection_state="ready",
            recommended_next_action="SSH соединение готово. Можно выполнять verify/show-команды.",
            error_code="",
            score=400,
            raw_preview=prompt,
        )
    if prompt.endswith(">") or (len(markers) > 1 and markers[1] and markers[1] in prompt):
        return _probe_result(
            target,
            available=True,
            status_message="SSH устройство отвечает в user mode",
            prompt_type="user",
            connection_state="user_mode",
            recommended_next_action="При запуске workflow будет выполнен переход в enable.",
            error_code="",
            score=300,
            raw_preview=prompt,
        )
    if prompt.endswith(":") or (len(markers) > 2 and markers[2] and markers[2] in prompt):
        return _probe_result(
            target,
            available=False,
            status_message="SSH цель находится в ROMMON/loader режиме",
            prompt_type="rommon",
            connection_state="rommon",
            recommended_next_action="Переведите устройство в IOS CLI и повторите попытку.",
            error_code="rommon",
            score=50,
            raw_preview=prompt,
        )
    return _probe_result(
        target,
        available=False,
        status_message="SSH prompt не распознан",
        prompt_type="unknown",
        connection_state="unknown_prompt",
        recommended_next_action="Проверьте баннер, shell и права пользователя.",
        error_code="unknown_prompt",
        score=0,
        raw_preview=prompt,
    )


def _probe_result(
    target: ConnectionTarget,
    *,
    available: bool,
    status_message: str,
    prompt_type: str | None,
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
        connection_state=connection_state,
        recommended_next_action=recommended_next_action,
        error_code=error_code,
        score=score,
        raw_preview=raw_preview,
    )
