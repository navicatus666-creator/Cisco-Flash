from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ..config import SessionPaths
from ..core.events import AppEvent
from ..core.logging_utils import append_session_log, timestamp
from ..core.models import OperatorMessage
from ..core.operator_messages import info_message
from ..core.snapshots import empty_snapshot
from .loader import ReplayScenario, load_scenario, load_scenarios
from .runner import ReplayRunner

ScheduleCallback = Callable[[int, Callable[[], None]], object]
EmitCallback = Callable[[AppEvent], None]


class DemoReplayController:
    def __init__(
        self,
        *,
        session: SessionPaths,
        runtime_root: Path,
        event_handler: EmitCallback,
        schedule: ScheduleCallback,
        scenario_name: str | None = None,
        playback_delay_ms: int = 70,
    ) -> None:
        self.session = session
        self.runtime_root = runtime_root
        self.event_handler = event_handler
        self.schedule = schedule
        self.playback_delay_ms = playback_delay_ms
        self.session_started_at = self.session.started_at.timestamp()
        self.session_started_label = self.session.started_at.strftime("%Y-%m-%d %H:%M:%S")
        self._scenario_map = {scenario.name: scenario for scenario in load_scenarios()}
        self._busy = False
        self._playback_token = 0
        self._selected_target_id = ""
        self._selected_scenario_name = self._resolve_scenario_name(scenario_name)

    @property
    def current_scenario(self) -> ReplayScenario:
        return self._scenario_map[self._selected_scenario_name]

    def list_scenarios(self) -> list[ReplayScenario]:
        return list(self._scenario_map.values())

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
            event_timeline_path=str(self.session.event_timeline_path),
            dashboard_snapshot_path=(
                str(self.session.dashboard_snapshot_path)
                if self.session.dashboard_snapshot_path is not None
                else ""
            ),
            session_dir=str(self.session.session_dir),
            session_id=self.session.session_id,
            session_started_at=self.session_started_at,
            session_started_label=self.session_started_label,
            run_mode="Demo",
        )
        self._emit(
            "device_snapshot",
            snapshot=empty_snapshot(
                status_text="Демо-режим готов к проигрыванию сценариев.",
                next_step="Выберите сценарий и нажмите Scan или нужный этап.",
            ),
        )
        self._emit("operator_message", message=self._scenario_message())
        self._emit("progress", percent=0, stage_name="Ожидание", stage_index=0, total_stages=5)
        self._emit(
            "state_changed",
            state="IDLE",
            message="Демо-режим готов. Выберите сценарий и запустите действие.",
            current_stage="Ожидание",
            last_scan_completed_at="",
            requested_firmware_name="",
        )
        self._emit_actions()
        self._emit(
            "log",
            line=f"[DEMO] Загружен сценарий {self.current_scenario.display_name}.",
            level="info",
        )

    def set_scenario(self, scenario_name: str) -> bool:
        if scenario_name not in self._scenario_map:
            return False
        if self._busy:
            return False
        self._selected_scenario_name = scenario_name
        self._selected_target_id = ""
        self._emit(
            "device_snapshot",
            snapshot=empty_snapshot(
                status_text="Сценарий переключен. Устройство ещё не проигрывалось.",
                next_step="Сценарий переключён. Запустите Scan, чтобы обновить статус и карточки.",
            ),
        )
        self._emit("operator_message", message=self._scenario_message())
        self._emit(
            "state_changed",
            state="IDLE",
            message=f"Сценарий переключён: {self.current_scenario.display_name}. Запустите Scan.",
        )
        self._emit_actions()
        self._emit(
            "log",
            line=f"[DEMO] Выбран сценарий {self.current_scenario.display_name}.",
            level="info",
        )
        return True

    def scan_devices(self) -> bool:
        return self._start_action("scan")

    def run_stage1(self) -> bool:
        return self._start_action("stage1")

    def run_stage2(self, firmware_name: str | None = None) -> bool:
        return self._start_action("stage2", firmware_name=firmware_name)

    def run_stage3(self) -> bool:
        return self._start_action("stage3")

    def stop(self) -> None:
        self._playback_token += 1
        if not self._busy:
            self._emit(
                "operator_message",
                message=info_message(
                    "Демо-режим остановлен",
                    "Активного проигрывания нет.",
                    "Выберите сценарий и запустите следующее действие.",
                ),
            )
            return
        self._busy = False
        self._emit(
            "state_changed",
            state="IDLE",
            message="Демо-проигрывание остановлено оператором.",
        )
        self._emit(
            "operator_message",
            message=OperatorMessage(
                code="demo_stopped",
                title="Демо-проигрывание остановлено",
                detail="Проигрывание остановлено до завершения текущего сценария.",
                next_step=(
                    "Запустите Scan заново или переключите сценарий перед следующим действием."
                ),
                severity="warning",
            ),
        )
        self._emit("log", line="[DEMO] Проигрывание остановлено.", level="warn")
        self._emit_actions()
        self._emit_idle_ready("stopped")

    def select_target(self, target_id: str) -> bool:
        if target_id != self.current_scenario.target.id:
            return False
        self._selected_target_id = target_id
        self._emit("selected_target_changed", target_id=target_id, manual_override=False)
        self._emit(
            "log",
            line=f"[DEMO] Выбрана цель {target_id} для сценария.",
            level="info",
        )
        return True

    def dispose(self) -> None:
        self.stop()

    def _resolve_scenario_name(self, scenario_name: str | None) -> str:
        if scenario_name and scenario_name in self._scenario_map:
            return scenario_name
        if "scan_ready" in self._scenario_map:
            return "scan_ready"
        return next(iter(self._scenario_map))

    def _scenario_message(self) -> OperatorMessage:
        scenario = self.current_scenario
        supported = ", ".join(
            self._friendly_action_name(name) for name in scenario.supported_actions
        )
        detail = scenario.description or "Сценарий готов для визуальной проверки интерфейса."
        return info_message(
            f"Demo: {scenario.display_name}",
            detail,
            f"Доступные действия: {supported}.",
        )

    def _friendly_action_name(self, action: str) -> str:
        mapping = {
            "scan": "Scan",
            "stage1": "Stage 1",
            "stage2": "Stage 2",
            "stage3": "Stage 3",
        }
        return mapping.get(action, action)

    def _emit(self, kind: str, **payload: object) -> None:
        self.event_handler(AppEvent(kind=kind, payload=dict(payload)))

    def _emit_actions(self) -> None:
        supported = set(self.current_scenario.supported_actions)
        self._emit(
            "actions_changed",
            scan_enabled=not self._busy and "scan" in supported,
            stage1_enabled=not self._busy and "stage1" in supported,
            stage2_enabled=not self._busy and "stage2" in supported,
            stage3_enabled=not self._busy and "stage3" in supported,
            stop_enabled=self._busy,
        )

    def _emit_idle_ready(self, reason: str) -> None:
        marker = f"[DEMO] Controller idle: {self.current_scenario.name} ({reason})"
        append_session_log(self.session.log_path, f"[{timestamp()}] {marker}")
        self._emit(
            "demo_idle_ready",
            scenario_name=self.current_scenario.name,
            scenario_display=self.current_scenario.display_name,
            reason=reason,
            busy=False,
            marker=marker,
        )
        self._emit("log", line=marker, level="debug")

    def _start_action(self, action: str, firmware_name: str | None = None) -> bool:
        if self._busy:
            return False
        if action not in self.current_scenario.supported_actions:
            self._emit(
                "operator_message",
                message=OperatorMessage(
                    code="demo_action_unsupported",
                    title="Действие недоступно для сценария",
                    detail=(
                        f"Сценарий {self.current_scenario.display_name} не поддерживает "
                        f"{self._friendly_action_name(action)}."
                    ),
                    next_step="Переключите сценарий или нажмите доступный этап.",
                    severity="warning",
                ),
            )
            self._emit(
                "log",
                line=(
                    f"[DEMO] Сценарий {self.current_scenario.name} не поддерживает "
                    f"{self._friendly_action_name(action)}."
                ),
                level="warn",
            )
            return False

        self._busy = True
        self._playback_token += 1
        token = self._playback_token
        self._emit_actions()

        scenario = load_scenario(self.current_scenario.name)
        result = ReplayRunner(scenario, runtime_root=self.runtime_root).run(
            action=action,
            firmware_name=firmware_name,
        )
        filtered_events = [event for event in result.events if event.kind != "actions_changed"]
        total_delay = 0
        for index, event in enumerate(filtered_events):
            delay = index * self.playback_delay_ms
            total_delay = delay
            self.schedule(delay, self._make_event_callback(token, event))
        self.schedule(total_delay + self.playback_delay_ms, self._make_finish_callback(token))
        return True

    def _make_event_callback(self, token: int, event: AppEvent) -> Callable[[], None]:
        def callback() -> None:
            if token != self._playback_token:
                return
            if event.kind == "selected_target_changed":
                self._selected_target_id = (
                    str(event.payload.get("target_id", "")) or self._selected_target_id
                )
            self.event_handler(event)

        return callback

    def _make_finish_callback(self, token: int) -> Callable[[], None]:
        def callback() -> None:
            if token != self._playback_token:
                return
            self._busy = False
            self._emit_actions()
            self._emit_idle_ready("completed")

        return callback
