from __future__ import annotations

import time
import traceback
from collections.abc import Callable
from threading import Lock, Thread

from ..config import SessionPaths, WorkflowTiming
from ..profiles.c2960x import DeviceProfile
from .events import AppEvent
from .logging_utils import append_session_log, timestamp
from .models import (
    ConnectionTarget,
    DeviceSnapshot,
    InstallStatus,
    OperatorMessage,
    ScanResult,
    StorageInfo,
    VersionInfo,
)
from .operator_messages import (
    info_message,
    message_for_stop,
    message_from_exception,
    message_from_scan_result,
)
from .reporting import build_install_report, write_install_report
from .session_artifacts import (
    build_session_manifest,
    build_stage_duration_rows,
    format_duration,
    snapshot_settings,
    write_session_manifest,
)
from .snapshots import empty_snapshot, snapshot_from_scan_result
from .state import WorkflowState
from .transport import Transport, TransportError, TransportFactory


class StopRequested(RuntimeError):
    """Raised when the operator stops the current workflow."""


class WorkflowController:
    def __init__(
        self,
        profile: DeviceProfile,
        transport_factory: TransportFactory,
        session: SessionPaths,
        event_handler: Callable[[AppEvent], None],
        timing: WorkflowTiming,
    ):
        self.profile = profile
        self.transport_factory = transport_factory
        self.session = session
        self.event_handler = event_handler
        self.timing = timing

        self.state = WorkflowState.IDLE
        self.scan_results: list[ScanResult] = []
        self.selected_target: ConnectionTarget | None = None
        self.selected_result: ScanResult | None = None
        self.device_snapshot = DeviceSnapshot()
        self.operator_message = info_message(
            "Готов к работе",
            "Выполните сканирование, затем выберите устройство и нужный этап.",
            "Начните со сканирования.",
        )
        self._last_state_message = "Готов к работе"
        self.install_status = InstallStatus()
        self.stage1_complete = False
        self.stage2_complete = False

        self._busy = False
        self._stop_requested = False
        self._active_transport: Transport | None = None
        self._active_thread: Thread | None = None
        self._lock = Lock()
        self.requested_firmware_name = self.profile.default_firmware
        self.session_started_at = self.session.started_at.timestamp()
        self.session_started_label = self.session.started_at.strftime("%Y-%m-%d %H:%M:%S")
        self.last_scan_completed_at = ""
        self._current_job_name: str | None = None
        self._current_job_started_at: float | None = None
        self._last_completed_stage_name = "Ожидание"
        self._last_completed_stage_duration: float | None = None
        self._stage_durations: dict[str, float | None] = {
            "scan": None,
            "stage1": None,
            "stage2": None,
            "stage3": None,
        }

    @property
    def privileged_prompt(self) -> str:
        return getattr(self.profile, "privileged_prompt", self.profile.prompts[0])

    @property
    def user_prompt(self) -> str:
        if hasattr(self.profile, "user_prompt"):
            return self.profile.user_prompt
        return self.profile.prompts[1] if len(self.profile.prompts) > 1 else self.profile.prompts[0]

    @property
    def reduced_prompt(self) -> str:
        if hasattr(self.profile, "reduced_prompt"):
            return self.profile.reduced_prompt
        return self.profile.prompts[2] if len(self.profile.prompts) > 2 else "switch:"

    def initialize(self) -> None:
        self._emit(
            "session_paths",
            log_path=str(self.session.log_path),
            report_path=str(self.session.report_path),
            transcript_path=str(self.session.transcript_path),
            settings_path=str(self.session.settings_path),
            settings_snapshot_path=str(self.session.settings_snapshot_path),
            manifest_path=str(self.session.manifest_path),
            bundle_path=str(self.session.bundle_path),
            session_dir=str(self.session.session_dir),
            session_id=self.session.session_id,
            session_started_at=self.session_started_at,
            session_started_label=self.session_started_label,
            run_mode=self._run_mode(),
        )
        self._emit("device_snapshot", snapshot=self.device_snapshot)
        self._emit("operator_message", message=self.operator_message)
        self._emit("progress", percent=0, stage_name="Ожидание", stage_index=0, total_stages=5)
        self._emit_actions()
        self._set_state(WorkflowState.IDLE, "Готов к работе")
        self._log("info", f"Лог сессии: {self.session.log_path}")
        self._log("info", f"Транскрипт сессии: {self.session.transcript_path}")
        self._write_session_manifest()

    def scan_devices(self, background: bool = True) -> bool:
        return self._start_job("scan", self._scan_devices_job, background=background)

    def run_stage1(self, background: bool = True) -> bool:
        return self._start_job("stage1", self._stage1_job, background=background)

    def run_stage2(self, firmware_name: str | None = None, background: bool = True) -> bool:
        firmware = (
            firmware_name or self.profile.default_firmware
        ).strip() or self.profile.default_firmware
        self.requested_firmware_name = firmware
        return self._start_job("stage2", lambda: self._stage2_job(firmware), background=background)

    def run_stage3(self, background: bool = True) -> bool:
        return self._start_job("stage3", self._stage3_job, background=background)

    def select_target(self, target_id: str) -> bool:
        match = next(
            (result for result in self.scan_results if result.target.id == target_id), None
        )
        if match is None:
            return False
        best = self._choose_best_result(self.scan_results)
        manual_override = best is not None and best.target.id != match.target.id
        self._apply_selected_result(match, manual_override=manual_override, fetch_details=False)
        self._log("info", f"Оператор выбрал цель {target_id}.")
        return True

    def stop(self) -> None:
        self._stop_requested = True
        if self._active_transport is not None:
            try:
                self._active_transport.interrupt()
            except Exception:
                self._log("debug", "Не удалось отправить interrupt active transport.")
        self._set_operator_message(message_for_stop())
        self._log("warn", "Запрошена остановка текущей операции.")

    def dispose(self) -> None:
        self.stop()
        self._disconnect_transport()

    def _emit(self, kind: str, **payload: object) -> None:
        self.event_handler(AppEvent(kind=kind, payload=dict(payload)))

    def _emit_actions(self) -> None:
        selected_available = self.selected_result is not None and self.selected_result.available
        self._emit(
            "actions_changed",
            busy=self._busy,
            scan_enabled=not self._busy,
            stage1_enabled=selected_available and not self._busy,
            stage2_enabled=self.stage1_complete and not self._busy,
            stage3_enabled=selected_available and not self._busy,
            stop_enabled=self._busy,
        )

    def _set_state(self, state: WorkflowState, message: str) -> None:
        self.state = state
        self._last_state_message = message
        self._emit(
            "state_changed",
            state=state.value,
            message=message,
            **self._session_status_payload(),
        )
        self._write_session_manifest()

    def _log(self, level: str, message: str) -> None:
        line = f"[{timestamp()}] {message}"
        append_session_log(self.session.log_path, line)
        self._emit("log", line=line, level=level)

    def _set_operator_message(self, message: OperatorMessage) -> None:
        self.operator_message = message
        self._emit("operator_message", message=message)
        self._write_session_manifest()

    def _emit_scan_results(self) -> None:
        self._emit(
            "scan_results",
            results=self.scan_results,
            selected_target_id=self.selected_target.id if self.selected_target else "",
        )

    def _emit_selected_target(self) -> None:
        self._emit(
            "selected_target_changed",
            target_id=self.selected_target.id if self.selected_target else "",
            manual_override=self.device_snapshot.is_manual_override,
        )
        self._write_session_manifest()

    def _start_job(self, job_name: str, func: Callable[[], None], background: bool) -> bool:
        with self._lock:
            if self._busy:
                self._log("warn", "Дождитесь завершения текущей операции.")
                return False
            self._busy = True
            self._stop_requested = False
            self._begin_stage_tracking(job_name)
            self._emit_actions()

        def runner() -> None:
            try:
                func()
            except StopRequested:
                self._set_state(WorkflowState.FAILED, "Операция остановлена")
                self._set_operator_message(message_for_stop())
                self._log("warn", "Операция остановлена пользователем.")
            except RuntimeError as exc:
                self._set_state(WorkflowState.FAILED, f"Ошибка: {exc}")
                self._set_operator_message(message_from_exception(exc))
                self._log("error", f"{job_name}: {exc}")
            except Exception as exc:
                traceback.print_exc()
                self._set_state(WorkflowState.FAILED, f"Ошибка: {exc}")
                self._set_operator_message(message_from_exception(exc))
                self._log("error", f"{job_name}: {exc}")
            finally:
                self._disconnect_transport()
                with self._lock:
                    self._busy = False
                    self._active_thread = None
                self._finish_stage_tracking(job_name)
                self._emit(
                    "state_changed",
                    state=self.state.value,
                    message=self._last_state_message,
                    **self._session_status_payload(),
                )
                self._write_session_manifest()
                self._emit_actions()

        if background:
            self._active_thread = Thread(target=runner, daemon=True)
            self._active_thread.start()
        else:
            runner()
        return True

    def _scan_devices_job(self) -> None:
        self._set_state(WorkflowState.DISCOVERING, "Сканирование COM-портов...")
        self._log("info", "Запущено сканирование COM-портов.")

        targets = self.transport_factory.list_targets()
        self.scan_results = []
        if not targets:
            self.selected_target = None
            self.selected_result = None
            self.stage1_complete = False
            self.stage2_complete = False
            self.install_status = InstallStatus()
            self.device_snapshot = empty_snapshot(
                status_text="COM-порты не найдены",
                next_step="Подключите USB/COM и повторите сканирование.",
            )
            self._emit("device_snapshot", snapshot=self.device_snapshot)
            self._emit_scan_results()
            self._emit_selected_target()
            self._set_operator_message(
                info_message(
                    "COM-порты не найдены",
                    "Во время сканирования не было найдено ни одного COM-порта.",
                    "Подключите консольный кабель и повторите сканирование.",
                )
            )
            self._set_state(WorkflowState.IDLE, "COM-порты не найдены")
            self._log("warn", "COM-порты не найдены.")
            return

        for target in targets:
            self._ensure_not_stopped()
            result = self.transport_factory.probe(
                target, self.profile.prompts, self.timing.scan_probe_timeout
            )
            self.scan_results.append(result)
            if result.available and result.prompt_type in {"priv", "user"}:
                level = "ok"
            elif result.available:
                level = "warn"
            else:
                level = "debug"
            self._log(level, f"{target.id}: {result.status_message}")

        self._emit_scan_results()

        current_selected_id = self.selected_target.id if self.selected_target else ""
        chosen = next(
            (result for result in self.scan_results if result.target.id == current_selected_id),
            None,
        )
        best = self._choose_best_result(self.scan_results)
        if chosen is None:
            chosen = best
            manual_override = False
        else:
            manual_override = best is not None and chosen.target.id != best.target.id

        if not chosen or not chosen.available:
            self.selected_target = None
            self.selected_result = None
            self.stage1_complete = False
            self.stage2_complete = False
            self.install_status = InstallStatus()
            self.device_snapshot = empty_snapshot(
                status_text="Нет отвечающих устройств",
                next_step=(
                    "Проверьте питание, кабель и скорость порта (baudrate), "
                    "затем повторите сканирование."
                ),
            )
            self._emit("device_snapshot", snapshot=self.device_snapshot)
            self._emit_selected_target()
            if self.scan_results:
                self._set_operator_message(message_from_scan_result(self.scan_results[0]))
            else:
                self._set_operator_message(
                    info_message(
                        "Устройство не найдено",
                        "Отвечающих устройств не обнаружено.",
                        "Повторите сканирование после проверки кабеля и питания.",
                    )
                )
            self._set_state(WorkflowState.IDLE, "Устройство не найдено")
            self._log("warn", "Не найдено отвечающих устройств.")
            return

        self._apply_selected_result(chosen, manual_override=manual_override, fetch_details=True)
        self._set_state(WorkflowState.IDLE, f"Устройство найдено: {chosen.target.id}")
        if manual_override:
            self._log("ok", f"Сохранён ручной выбор порта {chosen.target.id}.")
        else:
            self._log("ok", f"Автоматически выбран порт {chosen.target.id}.")

    def _apply_selected_result(
        self, result: ScanResult, *, manual_override: bool, fetch_details: bool
    ) -> None:
        if self.selected_target is None or self.selected_target.id != result.target.id:
            self.stage1_complete = False
            self.stage2_complete = False
            self.install_status = InstallStatus()
        self.selected_target = result.target
        self.selected_result = result
        snapshot = snapshot_from_scan_result(result, manual_override=manual_override)
        if fetch_details and result.prompt_type in {"priv", "user"}:
            snapshot = self._fetch_device_details(result.target, snapshot)
            snapshot.connection_state = result.connection_state
            snapshot.prompt_type = result.prompt_type or snapshot.prompt_type
            snapshot.status_text = result.status_message
            snapshot.recommended_next_action = (
                result.recommended_next_action or snapshot.recommended_next_action
            )
            snapshot.is_manual_override = manual_override
        self.device_snapshot = snapshot
        self._emit("device_snapshot", snapshot=self.device_snapshot)
        self._emit_selected_target()
        self._emit_scan_results()
        self._set_operator_message(message_from_scan_result(result))
        self._emit_actions()

    def _stage1_job(self) -> None:
        self._ensure_selected_target()
        self._set_state(WorkflowState.CONNECTING, "Stage 1: Подключение к устройству")
        self._set_operator_message(
            info_message(
                "Этап 1", "Подготовка к очистке устройства.", "Дождитесь завершения этапа 1."
            )
        )
        target = self.selected_target
        if target is None:
            raise RuntimeError("Сначала выполните сканирование и выберите устройство")
        transport = self._connect_transport(target, assign_active=True)
        self._ensure_privileged(transport)

        startup_output = transport.send_command(
            "show startup-config", wait=self.timing.command_wait_short
        )
        no_startup_markers = (
            "startup-config is not present",
            "No configuration present",
            "Can't find startup-config",
        )
        need_erase = not any(
            marker.lower() in startup_output.lower() for marker in no_startup_markers
        )

        if need_erase:
            self._set_state(WorkflowState.ERASING, "Stage 1: Стирание startup-config")
            self._log("info", "Выполняется write erase.")
            transport.send_command("write erase", wait=0.5)
            marker, _ = transport.read_until(
                ["Continue?", "[confirm]", "Proceed with reload?", "Delete filename"], 8
            )
            if marker:
                transport.write("")
            time.sleep(self.timing.command_wait_medium)
        else:
            self._log("info", "startup-config отсутствует, write erase пропущен.")

        dir_output = transport.send_command("dir flash:", wait=self.timing.command_wait_medium)
        if "vlan.dat" in dir_output:
            self._log("info", "Обнаружен vlan.dat, выполняю удаление.")
            transport.send_command("delete /force flash:/vlan.dat", wait=0.5)
            time.sleep(self.timing.command_wait_medium)
            self._log("ok", "vlan.dat удалён.")
        else:
            self._log("info", "vlan.dat отсутствует, удаление пропущено.")

        self._set_state(WorkflowState.REBOOTING, "Stage 1: Перезагрузка устройства")
        self._log("info", "Запуск reload.")
        transport.send_command("reload", wait=0.5)
        marker, _ = transport.read_until(
            ["[confirm]", "Proceed with reload?"], self.timing.reload_confirm_timeout
        )
        if marker:
            transport.write("")

        prompt = self._wait_for_prompt_after_reboot(transport, self.timing.stage1_prompt_timeout)
        if prompt != self.privileged_prompt:
            raise RuntimeError(
                "Таймаут после перезагрузки: не удалось дождаться Switch# после этапа 1"
            )

        self.stage1_complete = True
        self.stage2_complete = False
        self.install_status = InstallStatus()
        self.device_snapshot.status_text = "Этап 1 завершён"
        self.device_snapshot.connection_state = "ready"
        self.device_snapshot.prompt_type = "priv"
        self.device_snapshot.recommended_next_action = (
            "Этап 1 завершён. Подготовьте USB-образ и запускайте этап 2."
        )
        self._emit("device_snapshot", snapshot=self.device_snapshot)
        self._set_operator_message(
            info_message(
                "Этап 1 завершён",
                "Конфигурация очищена и устройство вернулось в Switch#.",
                "Подготовьте образ и запускайте этап 2.",
            )
        )
        self._set_state(WorkflowState.DONE, "Этап 1 завершён")
        self._log("ok", "Этап 1 завершён успешно.")

    def _stage2_job(self, firmware_name: str) -> None:
        self._ensure_selected_target()
        if not self.stage1_complete:
            raise RuntimeError("Сначала выполните этап 1")

        self._set_state(WorkflowState.CONNECTING, "Stage 2: Подключение к устройству")
        self._set_operator_message(
            info_message(
                "Этап 2",
                "Подготовка к установке образа.",
                "Не отключайте питание и дождитесь завершения этапа 2.",
            )
        )
        transport = self._open_active_transport()
        self._ensure_privileged(transport)

        flash_output = transport.send_command("show flash:", wait=self.timing.command_wait_medium)
        storage = self.profile.parse_storage(flash_output)
        if storage.total_bytes:
            self.device_snapshot.flash = (
                f"{storage.total_mb:.0f} MB ({storage.free_mb:.0f} MB free)"
            )
            self._emit("device_snapshot", snapshot=self.device_snapshot)

        install_path = self._find_firmware_path(transport, firmware_name)
        if not install_path:
            raise RuntimeError(f"Файл {firmware_name} не найден на USB")

        self._set_state(WorkflowState.INSTALLING, "Stage 2: Установка образа")
        self._log("info", f"Запуск archive download-sw для {install_path}")
        transport.write(f"archive download-sw /overwrite /reload {install_path}")

        download_complete = False
        error_detected = False
        buffer = ""
        recent_lines: list[str] = []
        deadline = time.time() + self.timing.install_timeout
        last_data_time = time.time()
        last_status_log = 0.0
        self.install_status = InstallStatus()
        self._emit("progress", percent=0, stage_name="Подготовка", stage_index=0, total_stages=5)

        while time.time() < deadline:
            self._ensure_not_stopped()
            chunk = transport.read_available()
            if chunk:
                last_data_time = time.time()
                buffer += chunk
                for raw_line in chunk.splitlines():
                    line = raw_line.strip()
                    if not line:
                        continue
                    recent_lines.append(line)
                    if len(recent_lines) > 12:
                        recent_lines.pop(0)
                    self._log("debug", f"INSTALL: {line}")
                    lowered = line.lower()
                    if "examining" in lowered:
                        self._mark_install_stage("examining", 1, "Examining")
                    if "extracting" in lowered:
                        self._mark_install_stage("extracting", 2, "Extracting")
                    if "installing" in lowered:
                        self._mark_install_stage("installing", 3, "Installing")
                    if "deleting" in lowered:
                        self._mark_install_stage("deleting_old", 4, "Deleting old")
                    if "signature" in lowered:
                        self._mark_install_stage("signature_verified", 5, "Signature verified")
                    if "reload" in lowered:
                        self.install_status.reload_requested = True

                lower_buffer = buffer.lower()
                if any(
                    marker in lower_buffer
                    for marker in (
                        "new software image installed",
                        "requested system reload",
                        "reload of the system",
                        "all software images installed",
                    )
                ):
                    download_complete = True
                    break
                if any(
                    err in lower_buffer
                    for err in (" error", "failed", "insufficient", "not enough space")
                ):
                    error_detected = True
                    break
            else:
                now = time.time()
                if (
                    self.install_status.installing
                    and now - last_data_time > self.timing.install_quiet_success
                ):
                    download_complete = True
                    break
                if now - last_status_log > self.timing.heartbeat_interval:
                    self._log("info", "Этап 2 выполняется, ожидаю новые данные от устройства...")
                    last_status_log = now
                time.sleep(0.5)

        if error_detected:
            raise RuntimeError("Таймаут установки: в выводе archive download-sw обнаружена ошибка")
        if not download_complete:
            raise RuntimeError("Таймаут установки: этап 2 не завершился в отведённое время")

        self._set_state(WorkflowState.REBOOTING, "Stage 2: Ожидание возврата устройства")
        prompt = self._wait_for_prompt_after_reboot(transport, self.timing.stage2_prompt_timeout)
        if prompt != self.privileged_prompt:
            raise RuntimeError(
                "Таймаут после перезагрузки: не удалось дождаться Switch# после установки образа"
            )

        self.stage2_complete = True
        self.device_snapshot.status_text = "Этап 2 завершён"
        self.device_snapshot.connection_state = "ready"
        self.device_snapshot.prompt_type = "priv"
        self.device_snapshot.usb_state = "ready"
        self.device_snapshot.recommended_next_action = (
            "Этап 2 завершён. Выполните этап 3 для финальной проверки."
        )
        self._emit("device_snapshot", snapshot=self.device_snapshot)
        self._set_operator_message(
            info_message(
                "Stage 2 завершён",
                f"Образ установлен из {install_path}.",
                "Запускайте этап 3 для финальной проверки и отчёта.",
            )
        )
        self._set_state(WorkflowState.DONE, "Этап 2 завершён")
        self._emit("progress", percent=100, stage_name="Done", stage_index=5, total_stages=5)
        self._log("ok", "Этап 2 завершён успешно.")
        for title, completed in self.install_status.as_rows():
            marker = "✓" if completed else "✗"
            self._log("info", f"{marker} {title}")

    def _stage3_job(self) -> None:
        self._ensure_selected_target()
        self._set_state(WorkflowState.CONNECTING, "Stage 3: Подключение к устройству")
        self._set_operator_message(
            info_message(
                "Этап 3",
                "Подготовка к финальной верификации.",
                "Дождитесь формирования install report.",
            )
        )
        transport = self._open_active_transport()
        self._ensure_privileged(transport)

        self._set_state(WorkflowState.VERIFYING, "Stage 3: Финальная проверка")
        transport.send_command("terminal length 0", wait=0.5)

        version_output = transport.send_command("show version", wait=self.timing.command_wait_long)
        version_info = self.profile.parse_version(version_output)
        boot_output = transport.send_command("show boot", wait=self.timing.command_wait_medium)
        dir_output = transport.send_command("dir flash:", wait=self.timing.command_wait_medium)
        storage = self.profile.parse_storage(dir_output)

        audit_results: list[dict[str, str]] = []
        for audit in self.profile.verify_commands:
            self._ensure_not_stopped()
            output = transport.send_command(audit.command, wait=audit.wait_time)
            audit_results.append({"title": audit.title, "output": output})
            self._log("info", f"Собрана проверка: {audit.command}")

        self._generate_report(
            version_info, storage, version_output, boot_output, dir_output, audit_results
        )
        self.device_snapshot.status_text = "Этап 3 завершён"
        self.device_snapshot.connection_state = "ready"
        self.device_snapshot.prompt_type = "priv"
        self.device_snapshot.recommended_next_action = (
            "Проверка завершена. При необходимости откройте отчёт и транскрипт."
        )
        if version_info.version:
            self.device_snapshot.firmware = version_info.version
        if version_info.model:
            self.device_snapshot.model = version_info.model
        if version_info.uptime:
            self.device_snapshot.uptime = version_info.uptime
        if storage.total_bytes:
            self.device_snapshot.flash = (
                f"{storage.total_mb:.0f} MB ({storage.free_mb:.0f} MB free)"
            )
        self._emit("device_snapshot", snapshot=self.device_snapshot)
        self._emit("report_ready", report_path=str(self.session.report_path))
        self._set_operator_message(
            info_message(
                "Этап 3 завершён",
                "Сформирован финальный install report.",
                "Откройте отчёт, транскрипт и при необходимости папку логов.",
            )
        )
        self._set_state(WorkflowState.DONE, "Этап 3 завершён")
        self._log("ok", f"Отчёт сохранён: {self.session.report_path}")

    def _ensure_selected_target(self) -> None:
        if self.selected_target is None:
            raise RuntimeError("Сначала выполните сканирование и выберите устройство")
        if self.selected_result is not None and not self.selected_result.available:
            raise RuntimeError("Выбранная цель недоступна. Выполните повторный Scan.")

    def _ensure_not_stopped(self) -> None:
        if self._stop_requested:
            raise StopRequested()

    def _choose_best_result(self, results: list[ScanResult]) -> ScanResult | None:
        available = [item for item in results if item.available]
        if not available:
            return None
        return max(available, key=lambda item: item.score)

    def _connect_transport(self, target: ConnectionTarget, assign_active: bool) -> Transport:
        transport = self.transport_factory.create(target)
        if hasattr(transport, "reset_interrupt"):
            transport.reset_interrupt()
        transport.connect()
        if assign_active:
            self._active_transport = transport
        return transport

    def _open_active_transport(self) -> Transport:
        if self._active_transport is not None and self._active_transport.is_connected():
            return self._active_transport
        target = self.selected_target
        if target is None:
            raise RuntimeError("Сначала выполните сканирование и выберите устройство")
        return self._connect_transport(target, assign_active=True)

    def _disconnect_transport(self) -> None:
        transport = self._active_transport
        self._active_transport = None
        self._disconnect_transport_instance(transport)

    def _disconnect_transport_instance(self, transport: Transport | None) -> None:
        if transport is None:
            return
        try:
            transport.disconnect()
        except Exception:
            self._log("debug", "Не удалось корректно закрыть transport.")

    def _fetch_device_details(
        self, target: ConnectionTarget, snapshot: DeviceSnapshot
    ) -> DeviceSnapshot:
        try:
            transport = self._connect_transport(target, assign_active=False)
            self._ensure_privileged(transport)
            transport.send_command("terminal length 0", wait=0.5)
            version_output = transport.send_command(
                "show version", wait=self.timing.command_wait_long
            )
            version_info = self.profile.parse_version(version_output)
            flash_output = transport.send_command(
                "dir flash:", wait=self.timing.command_wait_medium
            )
            storage = self.profile.parse_storage(flash_output)
            snapshot.connection_state = "ready"
            snapshot.prompt_type = "priv"
            if version_info.version:
                snapshot.firmware = version_info.version
            if version_info.model:
                snapshot.model = version_info.model
            if version_info.uptime:
                snapshot.uptime = version_info.uptime
            if storage.total_bytes:
                snapshot.flash = f"{storage.total_mb:.0f} MB ({storage.free_mb:.0f} MB free)"
            usb_found = False
            for usb_path in self.profile.usb_paths:
                output = transport.send_command(
                    f"dir {usb_path}", wait=self.timing.command_wait_medium
                )
                if (
                    "Directory of" in output
                    and "No such" not in output
                    and "Error opening" not in output
                ):
                    usb_found = True
                    break
            snapshot.usb_state = "ready" if usb_found else "missing"
            return snapshot
        except Exception as exc:
            self._log("warn", f"Не удалось получить подробности устройства: {exc}")
            return snapshot
        finally:
            self._disconnect_transport_instance(locals().get("transport"))

    def _read_prompt(
        self,
        transport: Transport,
        timeout: float,
        *,
        allow_user: bool,
        handle_config_dialog: bool,
    ) -> tuple[str | None, str]:
        markers = [self.privileged_prompt]
        if allow_user:
            markers.append(self.user_prompt)
        markers.append(self.reduced_prompt)
        marker, buffer = transport.read_until(markers, timeout)
        if handle_config_dialog and (
            "Would you like to enter" in buffer or "initial configuration dialog" in buffer
        ):
            self._log("info", "Обнаружен initial config dialog, отправляю 'no'.")
            transport.write("no")
            time.sleep(self.timing.command_wait_medium)
            marker, more = transport.read_until(
                [self.privileged_prompt, self.user_prompt], self.timing.prompt_timeout
            )
            buffer += more
        return marker, buffer

    def _ensure_privileged(self, transport: Transport) -> None:
        transport.write("")
        time.sleep(self.timing.command_wait_short)
        marker, buffer = self._read_prompt(
            transport,
            self.timing.prompt_timeout,
            allow_user=True,
            handle_config_dialog=True,
        )
        if marker is None:
            if any(
                token in buffer for token in ("User Access Verification", "Username:", "Password:")
            ):
                raise RuntimeError("Требуется авторизация на устройстве")
            raise RuntimeError("Не удалось получить приглашение устройства")
        if marker == self.reduced_prompt:
            raise RuntimeError("Устройство находится в ROMMON режиме")
        if marker == self.user_prompt:
            self._log("info", "Переход в привилегированный режим (enable).")
            transport.write("enable")
            time.sleep(self.timing.command_wait_short)
            marker, buffer = transport.read_until(
                [self.privileged_prompt], self.timing.enable_timeout
            )
            if marker is None:
                if "Password" in buffer:
                    raise RuntimeError(
                        "Требуется enable password, автоматический переход невозможен"
                    )
                raise RuntimeError("Не удалось войти в привилегированный режим")

    def _wait_for_prompt_after_reboot(self, transport: Transport, timeout: float) -> str | None:
        deadline = time.time() + timeout
        recent_lines: list[str] = []
        while time.time() < deadline:
            self._ensure_not_stopped()
            try:
                if not transport.is_connected():
                    target = self.selected_target
                    if target is None:
                        raise RuntimeError("Сначала выполните сканирование и выберите устройство")
                    transport = self._connect_transport(target, assign_active=True)
                    time.sleep(0.4)
                marker, buffer = self._read_prompt(
                    transport,
                    self.timing.prompt_timeout,
                    allow_user=True,
                    handle_config_dialog=True,
                )
                self._log_reboot_lines(buffer, recent_lines)
                if marker == self.user_prompt:
                    self._log("info", "После перезагрузки получен Switch>, выполняю enable.")
                    transport.write("enable")
                    time.sleep(self.timing.command_wait_short)
                    marker, more = transport.read_until(
                        [self.privileged_prompt], self.timing.enable_timeout
                    )
                    self._log_reboot_lines(more, recent_lines)
                if marker == self.privileged_prompt:
                    self._active_transport = transport
                    return marker
            except TransportError as exc:
                self._log("debug", f"Ожидание prompt после перезагрузки: {exc}")
                self._disconnect_transport_instance(transport)
            time.sleep(self.timing.command_wait_medium)
        return None

    def _log_reboot_lines(self, buffer: str, recent_lines: list[str]) -> None:
        for raw_line in buffer.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            recent_lines.append(line)
            if len(recent_lines) > 12:
                recent_lines.pop(0)
            self._log("debug", f"REBOOT: {line}")

    def _find_firmware_path(self, transport: Transport, firmware_name: str) -> str | None:
        for usb_path in self.profile.usb_paths:
            self._log("info", f"Проверка {usb_path} на наличие {firmware_name}")
            output = transport.send_command(f"dir {usb_path}", wait=self.timing.command_wait_medium)
            if firmware_name in output:
                self._log("ok", f"Файл {firmware_name} найден на {usb_path}")
                self.device_snapshot.usb_state = "ready"
                self._emit("device_snapshot", snapshot=self.device_snapshot)
                return f"{usb_path}/{firmware_name}"
        self.device_snapshot.usb_state = "missing"
        self._emit("device_snapshot", snapshot=self.device_snapshot)
        return None

    def _mark_install_stage(self, attribute: str, index: int, stage_name: str) -> None:
        if getattr(self.install_status, attribute):
            return
        setattr(self.install_status, attribute, True)
        percent = int(index / 5 * 100)
        self._emit(
            "progress", percent=percent, stage_name=stage_name, stage_index=index, total_stages=5
        )
        self._log("info", f"Прогресс этапа 2: {stage_name}")

    def _run_mode(self) -> str:
        base_dir_name = self.session.base_dir.name.lower()
        return "Demo" if base_dir_name == "demo" or "replay" in base_dir_name else "Operator"

    def _friendly_job_name(self, job_name: str | None) -> str:
        mapping = {
            "scan": "Сканирование",
            "stage1": "Этап 1",
            "stage2": "Этап 2",
            "stage3": "Этап 3",
        }
        if not job_name:
            return "Ожидание"
        return mapping.get(job_name, job_name)

    def _begin_stage_tracking(self, job_name: str) -> None:
        self._current_job_name = job_name
        self._current_job_started_at = time.time()
        self._last_completed_stage_name = self._friendly_job_name(job_name)
        self._last_completed_stage_duration = None

    def _finish_stage_tracking(self, job_name: str) -> None:
        if self._current_job_name != job_name or self._current_job_started_at is None:
            return
        duration = time.time() - self._current_job_started_at
        self._stage_durations[job_name] = duration
        self._last_completed_stage_name = self._friendly_job_name(job_name)
        self._last_completed_stage_duration = duration
        if job_name == "scan":
            self.last_scan_completed_at = timestamp()
        self._current_job_name = None
        self._current_job_started_at = None

    def _session_elapsed_seconds(self) -> float:
        return time.time() - self.session_started_at

    def _active_stage_elapsed_seconds(self) -> float | None:
        if self._current_job_started_at is not None:
            return time.time() - self._current_job_started_at
        return self._last_completed_stage_duration

    def _current_stage_label(self) -> str:
        if self._current_job_name is not None:
            return self._friendly_job_name(self._current_job_name)
        return self._last_completed_stage_name

    def _session_status_payload(self) -> dict[str, object]:
        active_stage_elapsed = self._active_stage_elapsed_seconds()
        return {
            "session_id": self.session.session_id,
            "session_started_at": self.session_started_at,
            "session_started_label": self.session_started_label,
            "session_elapsed_seconds": round(self._session_elapsed_seconds(), 2),
            "current_stage": self._current_stage_label(),
            "stage_started_at": self._current_job_started_at,
            "stage_elapsed_seconds": (
                round(active_stage_elapsed, 2) if active_stage_elapsed is not None else None
            ),
            "last_scan_completed_at": self.last_scan_completed_at,
            "requested_firmware_name": self.requested_firmware_name,
            "run_mode": self._run_mode(),
        }

    def _build_session_manifest_content(self) -> dict[str, object]:
        return build_session_manifest(
            session=self.session,
            profile_name=self.profile.display_name,
            run_mode=self._run_mode(),
            started_at=self.session_started_label,
            last_updated_at=timestamp(),
            session_elapsed_seconds=self._session_elapsed_seconds(),
            active_stage_elapsed_seconds=self._active_stage_elapsed_seconds(),
            current_state=self.state.value,
            current_stage=self._current_stage_label(),
            selected_target_id=self.selected_target.id if self.selected_target else "",
            requested_firmware_name=self.requested_firmware_name,
            observed_firmware_version=getattr(self.device_snapshot, "firmware", ""),
            last_scan_completed_at=self.last_scan_completed_at,
            operator_message={
                "severity": getattr(self.operator_message, "severity", ""),
                "title": getattr(self.operator_message, "title", ""),
                "detail": getattr(self.operator_message, "detail", ""),
                "next_step": getattr(self.operator_message, "next_step", ""),
            },
            stage_durations=self._stage_durations,
        )

    def _write_session_manifest(self) -> None:
        snapshot_settings(self.session.settings_path, self.session.settings_snapshot_path)
        write_session_manifest(self.session.manifest_path, self._build_session_manifest_content())

    def _build_report_session_summary(self) -> dict[str, str]:
        operator_text = " | ".join(
            value.strip()
            for value in (
                getattr(self.operator_message, "title", ""),
                getattr(self.operator_message, "detail", ""),
                getattr(self.operator_message, "next_step", ""),
            )
            if value.strip()
        )
        return {
            "Session ID": self.session.session_id,
            "Started": self.session_started_label,
            "Session Duration": format_duration(self._session_elapsed_seconds()),
            "Run Mode": self._run_mode(),
            "Final State": self.state.value,
            "State Message": self._last_state_message,
            "Current Stage": self._current_stage_label(),
            "Selected Target": self.selected_target.id if self.selected_target else "N/A",
            "Requested Firmware": self.requested_firmware_name or "N/A",
            "Observed Firmware": getattr(self.device_snapshot, "firmware", "") or "N/A",
            "Last Scan": self.last_scan_completed_at or "N/A",
            "Operator Message": operator_text or "N/A",
        }

    def _build_report_stage_durations(self) -> list[tuple[str, str]]:
        return build_stage_duration_rows(self._stage_durations)

    def _generate_report(
        self,
        version_info: VersionInfo,
        storage: StorageInfo,
        version_output: str,
        boot_output: str,
        dir_output: str,
        audit_results: list[dict[str, str]],
    ) -> None:
        workflow_mode = "Install+Verify"
        workflow_note = ""
        if not any(completed for _, completed in self.install_status.as_rows()):
            workflow_mode = "Verify-only"
            workflow_note = (
                "INSTALLATION STAGES may remain NOT COMPLETED intentionally for "
                "standalone Stage 3 verification."
            )
        base_dir_name = self.session.base_dir.name.lower()
        run_mode = "Demo" if base_dir_name == "demo" or "replay" in base_dir_name else "Operator"
        content = build_install_report(
            session=self.session,
            profile=self.profile,
            selected_target_id=self.selected_target.id if self.selected_target else "N/A",
            install_status=self.install_status,
            version_info=version_info,
            storage=storage,
            version_output=version_output,
            boot_output=boot_output,
            dir_output=dir_output,
            audit_results=audit_results,
            run_mode=run_mode,
            workflow_mode=workflow_mode,
            workflow_note=workflow_note,
            session_summary=self._build_report_session_summary(),
            stage_durations=self._build_report_stage_durations(),
        )
        write_install_report(self.session.report_path, content)
        self._write_session_manifest()
