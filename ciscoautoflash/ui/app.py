from __future__ import annotations

import argparse
import json
import os
import time
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from queue import Empty, Queue
from tkinter import messagebox
from tkinter.scrolledtext import ScrolledText
from typing import Any

import ttkbootstrap as ttk

from ..config import (
    AppConfig,
    AppSettings,
    load_settings,
    save_settings,
)
from ..core.events import AppEvent
from ..core.logging_utils import append_session_log, timestamp
from ..core.models import ScanResult
from ..core.serial_transport import SerialTransportFactory
from ..core.session_artifacts import export_session_bundle, format_duration, snapshot_settings
from ..core.single_instance import SingleInstanceError, SingleInstanceGuard
from ..core.workflow import WorkflowController
from ..profiles import build_c2960x_profile
from ..replay.adapter import DemoReplayController
from ..replay.loader import ReplayScenario


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"", "0", "false", "no", "off"}:
        return False
    if normalized in {"1", "true", "yes", "on"}:
        return True
    return default


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


class CiscoAutoFlashDesktop:
    def __init__(
        self,
        config: AppConfig | None = None,
        controller: WorkflowController | DemoReplayController | None = None,
        auto_start_scan: bool = True,
        demo_mode: bool = False,
        demo_scenario: str | None = None,
    ):
        self.demo_mode = demo_mode
        self.smoke_mode = self.demo_mode and _env_flag("CISCOAUTOFLASH_SMOKE_MODE", False)
        self.demo_playback_delay_ms = max(1, _env_int("CISCOAUTOFLASH_DEMO_DELAY_MS", 70))
        self.auto_start_scan = _env_flag("CISCOAUTOFLASH_AUTO_START_SCAN", auto_start_scan)
        self.last_smoke_open_path: Path | None = None
        base_config = config or AppConfig()
        if self.demo_mode:
            self.config = replace(base_config, runtime_root=(base_config.runtime_root / "demo"))
        else:
            self.config = base_config
        self.automation_overlay_enabled = self.demo_mode and _env_flag(
            "CISCOAUTOFLASH_AUTOMATION_OVERLAY", False
        )
        self.automation_map_enabled = self.demo_mode and (
            _env_flag("CISCOAUTOFLASH_AUTOMATION_MAP", False) or self.automation_overlay_enabled
        )
        self.automation_map_path = (
            self.config.runtime_root / "smoke_artifacts" / "current" / "automation_map.json"
        )
        self._automation_overlay: tk.Toplevel | None = None
        self._automation_overlay_canvas: tk.Canvas | None = None
        self.session = self.config.create_session_paths()
        self.settings = load_settings(self.session.settings_path)
        self.profile = build_c2960x_profile()
        self.event_queue: Queue[AppEvent] = Queue()
        self.scan_results: dict[str, ScanResult] = {}
        self._suppress_target_selection_event = False
        self.demo_scenarios_by_name: dict[str, ReplayScenario] = {}
        self.demo_display_to_name: dict[str, str] = {}
        self.demo_name_to_display: dict[str, str] = {}
        self.selected_demo_scenario_name = demo_scenario or self.settings.demo_scenario_name

        self._instance_guard: SingleInstanceGuard | None = None
        if controller is None:
            self._instance_guard = SingleInstanceGuard("CiscoAutoFlashDesktop")
            try:
                self._instance_guard.acquire()
            except SingleInstanceError as exc:
                root = tk.Tk()
                root.withdraw()
                messagebox.showerror("CiscoAutoFlash", str(exc))
                root.destroy()
                raise SystemExit(1) from exc

        self.window = ttk.Window(themename=self.config.theme_name)
        self.window.title(f"{self.config.app_name} {self.config.app_version}")
        self.window.geometry(self.settings.window_geometry or "1320x900")
        self.window.minsize(1200, 820)

        if controller is not None:
            self.controller = controller
        elif self.demo_mode:
            self.controller = DemoReplayController(
                session=self.session,
                runtime_root=self.config.runtime_root,
                event_handler=self._enqueue_event,
                schedule=self.window.after,
                scenario_name=self.selected_demo_scenario_name,
                playback_delay_ms=self.demo_playback_delay_ms,
            )
        else:
            self.controller = WorkflowController(
                profile=self.profile,
                transport_factory=SerialTransportFactory(
                    self.config.timing, transcript_path=self.session.transcript_path
                ),
                session=self.session,
                event_handler=self._enqueue_event,
                timing=self.config.timing,
            )

        if self.demo_mode and isinstance(self.controller, DemoReplayController):
            demo_scenarios = self.controller.list_scenarios()
            self.demo_scenarios_by_name = {scenario.name: scenario for scenario in demo_scenarios}
            self.demo_name_to_display = {
                scenario.name: scenario.display_name for scenario in demo_scenarios
            }
            self.demo_display_to_name = {
                scenario.display_name: scenario.name for scenario in demo_scenarios
            }
            self.selected_demo_scenario_name = self.controller.current_scenario.name

        self.log_path = self.session.log_path
        self.report_path = self.session.report_path
        self.transcript_path = self.session.transcript_path
        self.settings_path = self.session.settings_path
        self.manifest_path = self.session.manifest_path
        self.bundle_path = self.session.bundle_path
        self.session_dir = self.session.session_dir
        self.session_started_at_value = getattr(
            self.controller, "session_started_at", self.session.started_at.timestamp()
        )
        self.active_stage_started_at_value: float | None = None

        self.state_var = tk.StringVar(value="Инициализация рабочего места...")
        self.state_badge_var = tk.StringVar(value="ГОТОВНОСТЬ")
        self.transport_mode_var = tk.StringVar(value="Serial/USB")
        self.demo_badge_var = tk.StringVar(value="DEMO" if self.demo_mode else "")
        self.port_var = tk.StringVar(value="—")
        self.device_status_var = tk.StringVar(value="Ожидание сканирования")
        self.model_var = tk.StringVar(value="Не определена")
        self.current_fw_var = tk.StringVar(value="Не определена")
        self.flash_var = tk.StringVar(value="Не определена")
        self.uptime_var = tk.StringVar(value="Не определено")
        self.usb_var = tk.StringVar(value="USB неизвестен")
        self.connection_var = tk.StringVar(value="Ожидание")
        self.prompt_var = tk.StringVar(value="—")
        self.manual_override_var = tk.StringVar(value="Выбор цели: автоматически")
        self.profile_var = tk.StringVar(value=self.profile.display_name)
        self.firmware_input_var = tk.StringVar(
            value=self.settings.firmware_name or self.profile.default_firmware
        )
        self.demo_scenario_var = tk.StringVar(
            value=self.demo_name_to_display.get(self.selected_demo_scenario_name, "")
        )
        self.demo_description_var = tk.StringVar(value="")
        self.demo_actions_var = tk.StringVar(value="")
        self.progress_stage_var = tk.StringVar(value="Ожидание установки")
        self.progress_percent_var = tk.StringVar(value="0%")
        self.progress_meta_var = tk.StringVar(
            value="Маркеры установки появятся по мере работы archive download-sw."
        )
        self.footer_var = tk.StringVar(value="Готов к сканированию COM-портов")
        self.operator_title_var = tk.StringVar(value="Рабочее место готово")
        self.operator_detail_var = tk.StringVar(
            value="Выполните сканирование и выберите устройство для работы."
        )
        self.operator_next_step_var = tk.StringVar(value="Начните со сканирования COM-портов.")
        self.operator_severity_var = tk.StringVar(value="ИНФО")
        self.selected_target_var = tk.StringVar(value="Не выбрана")
        self.scan_status_var = tk.StringVar(value="Сканирование ещё не запускалось")
        self.session_id_var = tk.StringVar(value=self.session.session_id)
        self.session_started_var = tk.StringVar(
            value=self.session.started_at.strftime("%Y-%m-%d %H:%M:%S")
        )
        self.session_duration_var = tk.StringVar(value="00:00:00")
        self.active_stage_duration_var = tk.StringVar(value="—")
        self.session_mode_var = tk.StringVar(value="Demo" if self.demo_mode else "Operator")
        self.current_stage_var = tk.StringVar(value="Ожидание")
        self.last_scan_time_var = tk.StringVar(value="Ещё не выполнялось")
        self.log_path_var = tk.StringVar(value=str(self.log_path))
        self.report_path_var = tk.StringVar(value=str(self.report_path))
        self.transcript_path_var = tk.StringVar(value=str(self.transcript_path))
        self.settings_path_var = tk.StringVar(value=str(self.settings_path))
        self.manifest_path_var = tk.StringVar(value=str(self.manifest_path))
        self.bundle_path_var = tk.StringVar(value=str(self.bundle_path))
        self.log_status_var = tk.StringVar(value="Журнал будет создан по ходу сессии")
        self.report_status_var = tk.StringVar(value="Отчёт появится после этапа проверки")
        self.transcript_status_var = tk.StringVar(
            value="Транскрипт будет писаться в текущей сессии"
        )
        self.settings_status_var = tk.StringVar(value="Настройки будут сохранены при изменениях")
        self.manifest_status_var = tk.StringVar(value="Manifest будет обновляться по ходу сессии")
        self.bundle_status_var = tk.StringVar(value="Bundle будет создан по запросу оператора")

        self._build_ui()
        self._refresh_demo_details()
        self._refresh_preflight_paths()
        self._refresh_artifact_statuses()
        self._apply_state_style("IDLE")
        self._apply_operator_style("info")
        self._refresh_automation_map()
        if hasattr(self.controller, "requested_firmware_name"):
            self.controller.requested_firmware_name = (
                self.firmware_input_var.get().strip() or self.profile.default_firmware
            )
        self.controller.initialize()
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        self.window.after(100, self._drain_events)
        self.window.after(1000, self._tick_session_clock)
        if self.auto_start_scan:
            self.window.after(400, self.controller.scan_devices)

    def _enqueue_event(self, event: AppEvent) -> None:
        self.event_queue.put(event)

    def _build_ui(self) -> None:
        root = self.window
        root.configure(padx=18, pady=18)

        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0, 12))

        title_block = ttk.Frame(header)
        title_block.pack(side="left", fill="x", expand=True)
        ttk.Label(title_block, text="CiscoAutoFlash", font=("Segoe UI", 26, "bold")).pack(
            anchor="w"
        )
        ttk.Label(
            title_block,
            text="Рабочее место прошивки Cisco Catalyst 2960-X | Serial/USB V1 | SSH backend готов",
            font=("Segoe UI", 10),
            bootstyle="secondary",
        ).pack(anchor="w", pady=(4, 0))

        self.state_card = ttk.Labelframe(
            header,
            text="Статус сессии",
            padding=14,
            bootstyle="info",
        )
        self.state_card.pack(side="right")
        self.state_badge = ttk.Label(
            self.state_card,
            textvariable=self.state_badge_var,
            font=("Segoe UI", 12, "bold"),
            bootstyle="info",
        )
        self.state_badge.pack(anchor="e")
        if self.demo_mode:
            self.demo_badge = ttk.Label(
                self.state_card,
                textvariable=self.demo_badge_var,
                font=("Segoe UI", 9, "bold"),
                bootstyle="warning",
            )
            self.demo_badge.pack(anchor="e", pady=(6, 0))
        ttk.Label(
            self.state_card, textvariable=self.transport_mode_var, bootstyle="secondary"
        ).pack(anchor="e", pady=(6, 0))

        self.status_strip_card = ttk.Labelframe(
            root,
            text="Текущее действие",
            padding=14,
            bootstyle="primary",
        )
        self.status_strip_card.pack(fill="x", pady=(0, 12))
        self.status_strip_card.columnconfigure(0, weight=4)
        self.status_strip_card.columnconfigure(1, weight=3)
        self.status_strip_card.columnconfigure(2, weight=1)
        self.status_strip_card.columnconfigure(3, weight=1)
        ttk.Label(
            self.status_strip_card,
            textvariable=self.state_var,
            font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            self.status_strip_card,
            textvariable=self.device_status_var,
            bootstyle="secondary",
            wraplength=420,
            justify="left",
        ).grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Label(self.status_strip_card, text="Профиль", bootstyle="secondary").grid(
            row=0, column=2, sticky="e"
        )
        ttk.Label(
            self.status_strip_card,
            textvariable=self.profile_var,
            font=("Segoe UI", 10, "bold"),
        ).grid(row=1, column=2, sticky="e")
        ttk.Label(self.status_strip_card, text="Режим", bootstyle="secondary").grid(
            row=0, column=3, sticky="e"
        )
        ttk.Label(
            self.status_strip_card,
            textvariable=self.transport_mode_var,
            font=("Segoe UI", 10, "bold"),
        ).grid(row=1, column=3, sticky="e")

        summary_row = ttk.Frame(root)
        summary_row.pack(fill="x", pady=(0, 12))
        for column in range(4):
            summary_row.columnconfigure(column, weight=1)
        self._build_summary_card(
            summary_row, 0, "Выбранный порт", self.port_var, self.manual_override_var
        )
        self._build_summary_card(
            summary_row,
            1,
            "Состояние соединения",
            self.connection_var,
            self.device_status_var,
        )
        self._build_summary_card(summary_row, 2, "Prompt", self.prompt_var, self.usb_var)
        self._build_summary_card(
            summary_row, 3, "Версия / модель", self.current_fw_var, self.model_var
        )

        controls = ttk.Frame(root)
        controls.pack(fill="x", pady=(0, 12))

        firmware_card = ttk.Labelframe(controls, text="Образ прошивки", padding=12)
        firmware_card.pack(side="left", fill="x", expand=True)
        ttk.Label(
            firmware_card,
            text="Имя tar-образа на USB-накопителе",
            bootstyle="secondary",
        ).pack(anchor="w")
        ttk.Entry(firmware_card, textvariable=self.firmware_input_var).pack(fill="x", pady=(6, 0))

        if self.demo_mode:
            demo_card = ttk.Labelframe(controls, text="Demo-сценарий", padding=12)
            demo_card.pack(side="left", fill="x", padx=(12, 0))
            ttk.Label(
                demo_card,
                text="Dev-only проигрывание сценариев без оборудования",
                bootstyle="secondary",
            ).pack(anchor="w")
            self.demo_selector = ttk.Combobox(
                demo_card,
                textvariable=self.demo_scenario_var,
                state="readonly",
                values=list(self.demo_display_to_name),
            )
            self.demo_selector.pack(fill="x", pady=(6, 8))
            self.demo_selector.bind("<<ComboboxSelected>>", self._on_demo_scenario_selected)
            ttk.Label(
                demo_card,
                textvariable=self.demo_description_var,
                bootstyle="secondary",
                justify="left",
                wraplength=320,
            ).pack(anchor="w")
            ttk.Label(
                demo_card,
                textvariable=self.demo_actions_var,
                justify="left",
                wraplength=320,
            ).pack(anchor="w", pady=(8, 0))

        action_card = ttk.Labelframe(controls, text="Основные действия", padding=12)
        action_card.pack(side="left", padx=(12, 0))
        for column in range(5):
            action_card.columnconfigure(column, weight=1)

        self.scan_button = ttk.Button(
            action_card,
            text="Сканировать",
            bootstyle="primary",
            command=self._on_scan,
        )
        self.scan_button.grid(row=0, column=0, padx=4, pady=4, sticky="ew")
        self.stage1_button = ttk.Button(
            action_card,
            text="Этап 1: Сброс",
            bootstyle="warning",
            command=self._on_stage1,
        )
        self.stage1_button.grid(row=0, column=1, padx=4, pady=4, sticky="ew")
        self.stage2_button = ttk.Button(
            action_card,
            text="Этап 2: Установка",
            bootstyle="info",
            command=self._on_stage2,
        )
        self.stage2_button.grid(row=0, column=2, padx=4, pady=4, sticky="ew")
        self.stage3_button = ttk.Button(
            action_card,
            text="Этап 3: Проверка",
            bootstyle="success",
            command=self._on_stage3,
        )
        self.stage3_button.grid(row=0, column=3, padx=4, pady=4, sticky="ew")
        self.stop_button = ttk.Button(
            action_card,
            text="Стоп",
            bootstyle="danger",
            command=self._on_stop,
        )
        self.stop_button.grid(row=0, column=4, padx=4, pady=4, sticky="ew")

        utility_card = ttk.Labelframe(root, text="Файлы и артефакты сессии", padding=12)
        utility_card.pack(fill="x", pady=(0, 12))
        for column in range(6):
            utility_card.columnconfigure(column, weight=1)
        self.log_button = ttk.Button(
            utility_card,
            text="Открыть лог",
            bootstyle="secondary",
            command=self._open_log,
        )
        self.log_button.grid(row=0, column=0, padx=4, pady=4, sticky="ew")
        self.report_button = ttk.Button(
            utility_card,
            text="Открыть отчёт",
            bootstyle="secondary",
            command=self._open_report,
            state="disabled",
        )
        self.report_button.grid(row=0, column=1, padx=4, pady=4, sticky="ew")
        self.transcript_button = ttk.Button(
            utility_card,
            text="Открыть транскрипт",
            bootstyle="secondary",
            command=self._open_transcript,
        )
        self.transcript_button.grid(row=0, column=2, padx=4, pady=4, sticky="ew")
        self.logs_dir_button = ttk.Button(
            utility_card,
            text="Открыть папку логов",
            bootstyle="secondary",
            command=self._open_logs_dir,
        )
        self.logs_dir_button.grid(row=0, column=3, padx=4, pady=4, sticky="ew")
        self.session_folder_button = ttk.Button(
            utility_card,
            text="Открыть папку сессии",
            bootstyle="secondary",
            command=self._open_session_folder,
        )
        self.session_folder_button.grid(row=0, column=4, padx=4, pady=4, sticky="ew")
        self.bundle_export_button = ttk.Button(
            utility_card,
            text="Экспортировать bundle",
            bootstyle="secondary",
            command=self._export_session_bundle,
        )
        self.bundle_export_button.grid(row=0, column=5, padx=4, pady=4, sticky="ew")

        paned = ttk.Panedwindow(root, orient="horizontal", bootstyle="info")
        paned.pack(fill="both", expand=True)

        left_panel = ttk.Frame(paned, padding=2)
        left_panel.columnconfigure(0, weight=1)
        left_panel.rowconfigure(4, weight=1)
        paned.add(left_panel)

        right_panel = ttk.Frame(paned, padding=2)
        right_panel.columnconfigure(0, weight=1)
        right_panel.rowconfigure(0, weight=1)
        paned.add(right_panel)

        preflight_card = ttk.Labelframe(left_panel, text="Предпроверка сессии", padding=12)
        preflight_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        for column in (1, 3):
            preflight_card.columnconfigure(column, weight=1)
        self._build_preflight_value(
            preflight_card, 0, 0, "Выбранная цель", self.selected_target_var
        )
        self._build_preflight_value(preflight_card, 0, 2, "Образ", self.firmware_input_var)
        self._build_preflight_value(preflight_card, 1, 0, "Профиль", self.profile_var)
        self._build_preflight_value(
            preflight_card, 1, 2, "Последнее сканирование", self.scan_status_var
        )
        self._build_preflight_value(preflight_card, 2, 0, "Путь к логу", self.log_path_var)
        self._build_preflight_value(preflight_card, 2, 2, "Путь к отчёту", self.report_path_var)
        self._build_preflight_value(
            preflight_card, 3, 0, "Путь к транскрипту", self.transcript_path_var
        )
        self._build_preflight_value(preflight_card, 3, 2, "Файл настроек", self.settings_path_var)

        session_card = ttk.Labelframe(left_panel, text="Сводка сессии", padding=12)
        session_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for column in (1, 3):
            session_card.columnconfigure(column, weight=1)
        self._build_preflight_value(session_card, 0, 0, "ID сессии", self.session_id_var)
        self._build_preflight_value(session_card, 0, 2, "Старт", self.session_started_var)
        self._build_preflight_value(session_card, 1, 0, "Длительность", self.session_duration_var)
        self._build_preflight_value(
            session_card, 1, 2, "Длительность этапа", self.active_stage_duration_var
        )
        self._build_preflight_value(session_card, 2, 0, "Режим", self.session_mode_var)
        self._build_preflight_value(session_card, 2, 2, "Текущий этап", self.current_stage_var)
        self._build_preflight_value(
            session_card, 3, 0, "Выбранная цель", self.selected_target_var
        )
        self._build_preflight_value(session_card, 3, 2, "Firmware", self.firmware_input_var)
        self._build_preflight_value(
            session_card, 4, 0, "Последний scan", self.last_scan_time_var
        )
        self._build_preflight_value(session_card, 4, 2, "Статус", self.state_badge_var)

        self.operator_card = ttk.Labelframe(
            left_panel,
            text="Операторская подсказка",
            padding=14,
            bootstyle="info",
        )
        self.operator_card.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        operator_header = ttk.Frame(self.operator_card)
        operator_header.pack(fill="x")
        ttk.Label(
            operator_header,
            textvariable=self.operator_title_var,
            font=("Segoe UI", 12, "bold"),
        ).pack(side="left", anchor="w")
        self.operator_badge = ttk.Label(
            operator_header,
            textvariable=self.operator_severity_var,
            bootstyle="info",
            font=("Segoe UI", 9, "bold"),
        )
        self.operator_badge.pack(side="right", anchor="e")
        ttk.Label(
            self.operator_card,
            textvariable=self.operator_detail_var,
            justify="left",
            wraplength=420,
            bootstyle="secondary",
        ).pack(anchor="w", pady=(8, 8))
        ttk.Label(
            self.operator_card,
            text="Что делать дальше",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            self.operator_card,
            textvariable=self.operator_next_step_var,
            justify="left",
            wraplength=420,
        ).pack(anchor="w", pady=(4, 10))
        ttk.Separator(self.operator_card).pack(fill="x", pady=10)
        ttk.Label(
            self.operator_card, textvariable=self.manual_override_var, bootstyle="secondary"
        ).pack(anchor="w")
        ttk.Label(self.operator_card, textvariable=self.uptime_var, bootstyle="secondary").pack(
            anchor="w", pady=(2, 0)
        )

        progress_card = ttk.Labelframe(left_panel, text="Прогресс установки", padding=14)
        progress_card.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(
            progress_card,
            textvariable=self.progress_stage_var,
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        self.progress = ttk.Floodgauge(
            progress_card,
            value=0,
            maximum=100,
            text=self.progress_percent_var.get(),
            bootstyle="info",
            thickness=28,
        )
        self.progress.pack(fill="x", pady=(10, 8))
        ttk.Label(progress_card, textvariable=self.progress_meta_var, bootstyle="secondary").pack(
            anchor="w"
        )
        ttk.Label(
            progress_card,
            text=(
                "Ожидаемые маркеры: проверка образа -> распаковка -> установка -> "
                "очистка -> проверка подписи"
            ),
            bootstyle="secondary",
            wraplength=420,
            justify="left",
        ).pack(anchor="w", pady=(6, 0))

        targets_card = ttk.Labelframe(left_panel, text="Найденные устройства", padding=10)
        targets_card.grid(row=4, column=0, sticky="nsew")
        targets_card.rowconfigure(1, weight=1)
        targets_card.columnconfigure(0, weight=1)
        ttk.Label(targets_card, textvariable=self.scan_status_var, bootstyle="secondary").grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        self.targets_tree = ttk.Treeview(
            targets_card,
            columns=("status", "state", "prompt", "version"),
            show="tree headings",
            height=10,
            selectmode="browse",
            bootstyle="info",
        )
        self.targets_tree.heading("#0", text="Порт")
        self.targets_tree.heading("status", text="Статус")
        self.targets_tree.heading("state", text="Соединение")
        self.targets_tree.heading("prompt", text="Prompt")
        self.targets_tree.heading("version", text="Версия")
        self.targets_tree.column("#0", width=110, stretch=False)
        self.targets_tree.column("status", width=220)
        self.targets_tree.column("state", width=110, stretch=False)
        self.targets_tree.column("prompt", width=120, stretch=False)
        self.targets_tree.column("version", width=120, stretch=False)
        self.targets_tree.grid(row=1, column=0, sticky="nsew")
        self.targets_tree.bind("<<TreeviewSelect>>", self._on_target_selected)
        tree_scroll = ttk.Scrollbar(
            targets_card, orient="vertical", command=self.targets_tree.yview
        )
        tree_scroll.grid(row=1, column=1, sticky="ns")
        self.targets_tree.configure(yscrollcommand=tree_scroll.set)

        self.diagnostics_notebook = ttk.Notebook(right_panel, bootstyle="info")
        self.diagnostics_notebook.grid(row=0, column=0, sticky="nsew")

        log_tab = ttk.Frame(self.diagnostics_notebook, padding=10)
        self.diagnostics_notebook.add(log_tab, text="Журнал")
        legend = ttk.Frame(log_tab)
        legend.pack(fill="x", pady=(0, 8))
        for label, style in (
            ("info", "secondary"),
            ("ok", "success"),
            ("warn", "warning"),
            ("error", "danger"),
            ("debug", "info"),
        ):
            ttk.Label(legend, text=label.upper(), bootstyle=style).pack(side="left", padx=(0, 6))
        ttk.Label(
            legend,
            text="Журнал текущей операции, reboot/install и трасса этапов.",
            bootstyle="secondary",
        ).pack(side="right")
        self.log_box = ScrolledText(
            log_tab,
            font=("Consolas", 10),
            wrap="word",
            relief="flat",
            borderwidth=0,
        )
        self.log_box.pack(fill="both", expand=True)
        self.log_box.configure(
            background="#0f172a",
            foreground="#dbeafe",
            insertbackground="#dbeafe",
        )
        self.log_box.tag_config("info", foreground="#dbeafe")
        self.log_box.tag_config("ok", foreground="#86efac")
        self.log_box.tag_config("warn", foreground="#facc15")
        self.log_box.tag_config("error", foreground="#fca5a5")
        self.log_box.tag_config("debug", foreground="#93c5fd")

        artifacts_tab = ttk.Frame(self.diagnostics_notebook, padding=12)
        self.diagnostics_notebook.add(artifacts_tab, text="Артефакты сессии")
        artifacts_tab.columnconfigure(1, weight=1)
        artifacts_tab.columnconfigure(2, weight=1)
        ttk.Label(
            artifacts_tab,
            text="Здесь собраны все файлы текущей сессии и краткая подсказка, что в них искать.",
            bootstyle="secondary",
            wraplength=760,
            justify="left",
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))
        self._build_artifact_row(
            artifacts_tab,
            1,
            "Лог",
            self.log_path_var,
            self.log_status_var,
            "Ищите общий таймлайн этапов, статусы сканирования и короткие сводки ошибок.",
            self._open_log,
            button_text="Открыть",
        )
        self._build_artifact_row(
            artifacts_tab,
            2,
            "Отчёт",
            self.report_path_var,
            self.report_status_var,
            "Ищите итоговую версию IOS, boot variable, flash space и финальную проверку.",
            self._open_report,
            button_text="Открыть",
            button_attr="artifact_report_button",
            enabled=False,
        )
        self._build_artifact_row(
            artifacts_tab,
            3,
            "Транскрипт",
            self.transcript_path_var,
            self.transcript_status_var,
            "Ищите сырой READ/WRITE диалог с устройством, prompt и вывод команд.",
            self._open_transcript,
            button_text="Открыть",
        )
        self._build_artifact_row(
            artifacts_tab,
            4,
            "Настройки",
            self.settings_path_var,
            self.settings_status_var,
            "Ищите последний firmware name, выбранный порт и геометрию окна.",
            lambda: self._open_path(self.settings_path),
            button_text="Открыть",
        )
        self._build_artifact_row(
            artifacts_tab,
            5,
            "Manifest",
            self.manifest_path_var,
            self.manifest_status_var,
            "Ищите сводку сессии, длительности этапов, финальный state и operator message.",
            self._open_manifest,
            button_text="Открыть",
        )
        self._build_artifact_row(
            artifacts_tab,
            6,
            "Bundle",
            self.bundle_path_var,
            self.bundle_status_var,
            "ZIP-пакет для баг-репорта: log, report, transcript, settings snapshot и manifest.",
            self._open_bundle,
            button_text="Открыть",
            button_attr="artifact_bundle_button",
            enabled=False,
        )
        ttk.Button(
            artifacts_tab,
            text="Открыть папку логов",
            bootstyle="secondary",
            command=self._open_logs_dir,
        ).grid(row=7, column=3, sticky="e", pady=(6, 0))

        runbook_tab = ttk.Frame(self.diagnostics_notebook, padding=10)
        self.diagnostics_notebook.add(runbook_tab, text="Памятка")
        self.diagnostics_notebook.bind("<<NotebookTabChanged>>", self._on_diagnostics_tab_changed)
        ttk.Label(
            runbook_tab,
            text=(
                "Краткая памятка загружается из docs/pre_hardware и служит опорой "
                "перед реальным железом."
            ),
            bootstyle="secondary",
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        self.runbook_box = ScrolledText(
            runbook_tab,
            font=("Segoe UI", 10),
            wrap="word",
            relief="flat",
            borderwidth=0,
        )
        self.runbook_box.pack(fill="both", expand=True)
        self._set_text_widget(self.runbook_box, self._load_runbook_text(), readonly=True)

        footer = ttk.Label(root, textvariable=self.footer_var, bootstyle="secondary")
        footer.pack(fill="x", pady=(12, 0))

    def _build_summary_card(
        self,
        parent: ttk.Frame,
        column: int,
        title: str,
        primary_var: tk.StringVar,
        secondary_var: tk.StringVar,
    ) -> None:
        card = ttk.Labelframe(parent, text=title, padding=12)
        card.grid(row=0, column=column, padx=(0 if column == 0 else 8, 0), sticky="nsew")
        ttk.Label(card, textvariable=primary_var, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(
            card,
            textvariable=secondary_var,
            bootstyle="secondary",
            wraplength=240,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

    def _build_preflight_value(
        self,
        parent: ttk.Labelframe,
        row: int,
        column: int,
        title: str,
        value_var: tk.StringVar,
    ) -> None:
        ttk.Label(parent, text=title, bootstyle="secondary").grid(
            row=row,
            column=column,
            sticky="nw",
            padx=(0 if column == 0 else 16, 8),
            pady=4,
        )
        ttk.Label(parent, textvariable=value_var, justify="left", wraplength=360).grid(
            row=row,
            column=column + 1,
            sticky="nw",
            pady=4,
        )

    def _build_artifact_row(
        self,
        parent: ttk.Frame,
        row: int,
        title: str,
        path_var: tk.StringVar,
        status_var: tk.StringVar,
        description: str,
        command,
        *,
        button_text: str,
        button_attr: str | None = None,
        enabled: bool = True,
    ) -> None:
        ttk.Label(parent, text=title, font=("Segoe UI", 10, "bold")).grid(
            row=row, column=0, sticky="nw", padx=(0, 10), pady=(0, 10)
        )
        entry = ttk.Entry(parent, textvariable=path_var)
        entry.grid(row=row, column=1, sticky="ew", pady=(0, 10))
        entry.configure(state="readonly")
        meta = ttk.Frame(parent)
        meta.grid(row=row, column=2, sticky="new", padx=(12, 10), pady=(0, 10))
        ttk.Label(meta, textvariable=status_var, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        ttk.Label(
            meta,
            text=description,
            bootstyle="secondary",
            wraplength=320,
            justify="left",
        ).pack(anchor="w", pady=(2, 0))
        button = ttk.Button(
            parent,
            text=button_text,
            bootstyle="secondary",
            command=command,
            state="normal" if enabled else "disabled",
        )
        button.grid(row=row, column=3, sticky="e", pady=(0, 10))
        if button_attr:
            setattr(self, button_attr, button)

    def _widget_bounds(self, widget: Any) -> dict[str, int] | None:
        if widget is None:
            return None
        try:
            left = int(widget.winfo_rootx())
            top = int(widget.winfo_rooty())
            width = int(widget.winfo_width())
            height = int(widget.winfo_height())
        except Exception:
            return None
        if width <= 0 or height <= 0:
            return None
        return {
            "left": left,
            "top": top,
            "width": width,
            "height": height,
            "right": left + width,
            "bottom": top + height,
        }

    @staticmethod
    def _click_point_from_bounds(bounds: dict[str, int]) -> dict[str, int]:
        return {
            "x": int(bounds["left"] + bounds["width"] / 2),
            "y": int(bounds["top"] + bounds["height"] / 2),
        }

    def _control_payload(self, widget: Any, *, name: str) -> dict[str, object] | None:
        bounds = self._widget_bounds(widget)
        if bounds is None:
            return None
        try:
            state = str(widget.cget("state"))
        except Exception:
            state = ""
        try:
            text = str(widget.cget("text"))
        except Exception:
            text = name
        return {
            "name": name,
            "text": text,
            "state": state,
            "bounds": bounds,
            "click_point": self._click_point_from_bounds(bounds),
        }

    def _build_notebook_tabs_payload(self) -> dict[str, dict[str, object]]:
        notebook = getattr(self, "diagnostics_notebook", None)
        bounds = self._widget_bounds(notebook)
        if notebook is None or bounds is None:
            return {}
        try:
            tab_count = int(notebook.index("end"))
            selected_tab = str(notebook.tab(notebook.select(), "text"))
        except Exception:
            return {}
        probe_y = max(1, min(10, bounds["height"] - 1))
        runs: dict[int, list[int]] = {}
        last_index: int | None = None
        run_start = 0
        for x_pos in range(max(1, bounds["width"])):
            try:
                index = int(notebook.index(f"@{x_pos},{probe_y}"))
            except Exception:
                index = -1
            if index < 0 or index >= tab_count:
                index = -1
            if index != last_index:
                if last_index is not None and last_index >= 0:
                    runs[last_index] = [run_start, x_pos - 1]
                run_start = x_pos
                last_index = index
        if last_index is not None and last_index >= 0:
            runs[last_index] = [run_start, max(0, bounds["width"] - 1)]
        payload: dict[str, dict[str, object]] = {}
        tab_height = min(28, bounds["height"])
        for index, (start_x, end_x) in runs.items():
            try:
                tab_text = str(notebook.tab(index, "text"))
            except Exception:
                continue
            tab_bounds = {
                "left": bounds["left"] + start_x,
                "top": bounds["top"],
                "width": max(1, end_x - start_x + 1),
                "height": tab_height,
                "right": bounds["left"] + end_x + 1,
                "bottom": bounds["top"] + tab_height,
            }
            payload[tab_text] = {
                "index": index,
                "selected": tab_text == selected_tab,
                "bounds": tab_bounds,
                "click_point": {
                    "x": int(tab_bounds["left"] + tab_bounds["width"] / 2),
                    "y": int(tab_bounds["top"] + min(12, max(6, tab_height // 2))),
                },
            }
        return payload

    def _build_automation_map(self) -> dict[str, object]:
        update_idletasks = getattr(self.window, "update_idletasks", None)
        if callable(update_idletasks):
            update_idletasks()
        window_bounds = self._widget_bounds(self.window)
        if window_bounds is None:
            raise RuntimeError("Window bounds are not available for automation map.")
        window_title = ""
        title = getattr(self.window, "title", None)
        if callable(title):
            window_title = str(title())
        else:
            window_text = getattr(self.window, "window_text", None)
            if callable(window_text):
                window_title = str(window_text())
        controls: dict[str, dict[str, object]] = {}
        control_map = (
            ("scan", getattr(self, "scan_button", None)),
            ("stage1", getattr(self, "stage1_button", None)),
            ("stage2", getattr(self, "stage2_button", None)),
            ("stage3", getattr(self, "stage3_button", None)),
            ("stop", getattr(self, "stop_button", None)),
            ("open_log", getattr(self, "log_button", None)),
            ("open_report", getattr(self, "report_button", None)),
            ("open_transcript", getattr(self, "transcript_button", None)),
            ("open_logs_dir", getattr(self, "logs_dir_button", None)),
            ("open_session_dir", getattr(self, "session_folder_button", None)),
            ("export_bundle", getattr(self, "bundle_export_button", None)),
        )
        for name, widget in control_map:
            payload = self._control_payload(widget, name=name)
            if payload is not None:
                controls[name] = payload

        selector_bounds = self._widget_bounds(getattr(self, "demo_selector", None))
        selector_payload: dict[str, object] = {
            "current_display": self.demo_scenario_var.get(),
            "current_name": self.selected_demo_scenario_name,
            "items": list(self.demo_display_to_name),
        }
        if selector_bounds is not None:
            selector_payload["bounds"] = selector_bounds
            selector_payload["click_point"] = self._click_point_from_bounds(selector_bounds)
            selector_payload["arrow_click_point"] = {
                "x": max(selector_bounds["left"] + 6, selector_bounds["right"] - 12),
                "y": int(selector_bounds["top"] + selector_bounds["height"] / 2),
            }

        notebook = getattr(self, "diagnostics_notebook", None)
        notebook_bounds = self._widget_bounds(notebook)
        tabs_payload = self._build_notebook_tabs_payload()
        state_payload = {
            "state_text": self.state_var.get(),
            "state_badge": self.state_badge_var.get(),
            "current_stage": self.current_stage_var.get(),
            "selected_target": self.selected_target_var.get(),
            "connection": self.connection_var.get(),
            "prompt": self.prompt_var.get(),
            "footer": self.footer_var.get(),
            "selected_tab": next(
                (name for name, item in tabs_payload.items() if bool(item.get("selected"))),
                "",
            ),
            "artifact_states": {
                name: str(payload.get("state", ""))
                for name, payload in controls.items()
                if name.startswith("open_") or name == "export_bundle"
            },
        }
        session_payload = {
            "session_id": self.session.session_id,
            "session_dir": str(self.session_dir),
            "log_path": str(self.log_path),
            "report_path": str(self.report_path),
            "transcript_path": str(self.transcript_path),
            "settings_path": str(self.settings_path),
            "manifest_path": str(self.manifest_path),
            "bundle_path": str(self.bundle_path),
        }
        return {
            "generated_at": timestamp(),
            "window": {
                "title": window_title,
                "bounds": window_bounds,
                "click_point": self._click_point_from_bounds(window_bounds),
            },
            "controls": controls,
            "tabs": {
                "container": notebook_bounds,
                "items": tabs_payload,
            },
            "selector": selector_payload,
            "state": state_payload,
            "session": session_payload,
        }

    def _refresh_automation_overlay(self, payload: dict[str, object] | None = None) -> None:
        if not self.automation_overlay_enabled:
            return
        if payload is None:
            payload = self._build_automation_map()
        window_payload = payload.get("window", {})
        window_bounds = window_payload.get("bounds") if isinstance(window_payload, dict) else None
        if not isinstance(window_bounds, dict):
            return
        overlay = self._automation_overlay
        canvas = self._automation_overlay_canvas
        if overlay is None or canvas is None or not overlay.winfo_exists():
            overlay = tk.Toplevel(self.window)
            overlay.overrideredirect(True)
            overlay.attributes("-topmost", True)
            try:
                overlay.attributes("-alpha", 0.22)
            except Exception:
                pass
            canvas = tk.Canvas(overlay, highlightthickness=0, bg="black")
            canvas.pack(fill="both", expand=True)
            self._automation_overlay = overlay
            self._automation_overlay_canvas = canvas
        overlay.geometry(
            f"{window_bounds['width']}x{window_bounds['height']}+{window_bounds['left']}+{window_bounds['top']}"
        )
        canvas.configure(width=window_bounds["width"], height=window_bounds["height"])
        canvas.delete("all")

        def draw_target(label: str, bounds: dict[str, int], color: str) -> None:
            left = bounds["left"] - window_bounds["left"]
            top = bounds["top"] - window_bounds["top"]
            right = bounds["right"] - window_bounds["left"]
            bottom = bounds["bottom"] - window_bounds["top"]
            canvas.create_rectangle(left, top, right, bottom, outline=color, width=2)
            center_x = int((left + right) / 2)
            center_y = int((top + bottom) / 2)
            canvas.create_oval(
                center_x - 3,
                center_y - 3,
                center_x + 3,
                center_y + 3,
                fill=color,
                outline=color,
            )
            canvas.create_text(left + 4, max(8, top + 8), text=label, anchor="w", fill=color)

        controls = payload.get("controls", {})
        if isinstance(controls, dict):
            for name, item in controls.items():
                if isinstance(item, dict):
                    bounds = item.get("bounds")
                    if isinstance(bounds, dict):
                        draw_target(str(name), bounds, "#7dd3fc")
        tabs = payload.get("tabs", {})
        if isinstance(tabs, dict):
            tab_items = tabs.get("items", {})
            if isinstance(tab_items, dict):
                for name, item in tab_items.items():
                    if isinstance(item, dict):
                        bounds = item.get("bounds")
                        if isinstance(bounds, dict):
                            draw_target(f"tab:{name}", bounds, "#86efac")
        selector = payload.get("selector", {})
        if isinstance(selector, dict):
            bounds = selector.get("bounds")
            if isinstance(bounds, dict):
                draw_target("selector", bounds, "#fca5a5")

    def _refresh_automation_map(self) -> None:
        if not self.automation_map_enabled and not self.automation_overlay_enabled:
            return
        try:
            payload = self._build_automation_map()
        except Exception as exc:
            if self.smoke_mode and self.demo_mode:
                self._log_demo_ui_action("Automation map refresh failed", repr(exc), level="debug")
            return
        if self.automation_map_enabled:
            self.automation_map_path.parent.mkdir(parents=True, exist_ok=True)
            self.automation_map_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        self._refresh_automation_overlay(payload)

    def _refresh_preflight_paths(self) -> None:
        path_map = (
            ("log_path_var", self.log_path),
            ("report_path_var", self.report_path),
            ("transcript_path_var", self.transcript_path),
            ("settings_path_var", self.settings_path),
            ("manifest_path_var", self.manifest_path),
            ("bundle_path_var", self.bundle_path),
        )
        for attr, path in path_map:
            var = getattr(self, attr, None)
            if var is not None:
                var.set(str(path))
        self._refresh_artifact_statuses()

    def _refresh_artifact_statuses(self) -> None:
        self.log_status_var.set(
            "Журнал готов" if self.log_path.exists() else "Журнал будет создан по ходу сессии"
        )
        self.report_status_var.set(
            "Отчёт готов" if self.report_path.exists() else "Отчёт появится после этапа проверки"
        )
        self.transcript_status_var.set(
            "Транскрипт готов"
            if self.transcript_path.exists()
            else "Транскрипт будет писаться в текущей сессии"
        )
        self.settings_status_var.set(
            "Настройки сохранены"
            if self.settings_path.exists()
            else "Настройки будут сохранены при изменениях"
        )
        self.manifest_status_var.set(
            "Manifest готов"
            if self.manifest_path.exists()
            else "Manifest будет обновляться по ходу сессии"
        )
        self.bundle_status_var.set(
            "Bundle готов"
            if self.bundle_path.exists()
            else "Bundle будет создан по запросу оператора"
        )
        artifact_bundle_button = getattr(self, "artifact_bundle_button", None)
        if artifact_bundle_button is not None:
            artifact_bundle_button.configure(
                state="normal" if self.bundle_path.exists() else "disabled"
            )
        self._refresh_automation_map()

    def _load_runbook_text(self) -> str:
        docs_dir = self.config.project_root / "docs" / "pre_hardware"
        sections = [
            ("Гейт перед железом", docs_dir / "pre_hardware_readiness_gate.md"),
            ("Аппаратный чек-лист", docs_dir / "hardware_smoke_checklist.md"),
            ("Ожидаемые результаты", docs_dir / "expected_outcomes.md"),
            ("Матрица сценариев", docs_dir / "scenario_matrix.md"),
            ("Сверка с legacy", docs_dir / "legacy_parity_checklist.md"),
        ]
        parts = [
            "Встроенная памятка перед железом",
            "",
            (
                "Эта вкладка читает документы из docs/pre_hardware и нужна как встроенная "
                "памятка перед реальным Cisco 2960-X."
            ),
            "",
        ]
        for title, section_path in sections:
            parts.append(f"{'=' * 78}")
            parts.append(title)
            parts.append(f"Файл: {section_path}")
            if section_path.exists():
                try:
                    parts.append(section_path.read_text(encoding="utf-8").strip())
                except Exception as exc:
                    parts.append(f"Не удалось прочитать файл: {exc}")
            else:
                parts.append("Файл не найден.")
            parts.append("")
        return "\n".join(parts).strip() + "\n"

    def _set_text_widget(self, widget: ScrolledText, text: str, *, readonly: bool) -> None:
        if readonly:
            widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        if readonly:
            widget.configure(state="disabled")

    def _tick_session_clock(self) -> None:
        session_started_at = getattr(self, "session_started_at_value", None)
        if session_started_at is not None:
            elapsed = max(0.0, time.time() - session_started_at)
            self.session_duration_var.set(format_duration(elapsed))
        else:
            self.session_duration_var.set("00:00:00")
        active_stage_started_at = getattr(self, "active_stage_started_at_value", None)
        if active_stage_started_at is not None:
            elapsed = max(0.0, time.time() - active_stage_started_at)
            self.active_stage_duration_var.set(format_duration(elapsed))
        self.window.after(1000, self._tick_session_clock)

    def _update_selected_target(self, target_id: str) -> None:
        value = target_id or "Не выбрана"
        self.selected_target_var.set(value)

    def _set_tree_selection(self, target_id: str, *, ensure_visible: bool = True) -> None:
        if not target_id or not hasattr(self, "targets_tree"):
            return
        self._suppress_target_selection_event = True
        try:
            self.targets_tree.selection_set(target_id)
            self.targets_tree.focus(target_id)
            if ensure_visible:
                self.targets_tree.see(target_id)
        finally:
            self._suppress_target_selection_event = False

    def _update_scan_status(self, results: list[ScanResult], selected_target_id: str) -> None:
        if not results:
            self.scan_status_var.set("COM-цели не найдены")
        elif selected_target_id:
            self.scan_status_var.set(
                f"Найдено COM-целей: {len(results)}. Выбрана цель {selected_target_id}."
            )
        else:
            self.scan_status_var.set(
                f"Найдено COM-целей: {len(results)}. Отвечающее устройство не выбрано."
            )

    def _friendly_connection_state(self, value: str) -> str:
        mapping = {
            "idle": "Ожидание",
            "ready": "Готово",
            "unknown": "Не определено",
            "port_busy": "Порт занят",
            "login_required": "Нужен вход",
            "config_dialog": "Config dialog",
            "rommon": "ROMMON",
            "no_prompt": "Нет prompt",
            "press_return": "Нажмите Enter",
            "user": "Switch>",
            "priv": "Switch#",
        }
        return mapping.get(value, value or "Не определено")

    def _friendly_prompt(self, value: str) -> str:
        mapping = {
            "priv": "Switch#",
            "user": "Switch>",
            "rommon": "ROMMON",
            "config_dialog": "Config dialog",
            "press_return": "Нажмите Enter",
            "login": "Login",
            # Cisco prompt label; not a credential.
            "password": "Password",  # nosec
        }
        return mapping.get(value, value or "—")

    def _friendly_manual_override(self, manual_override: bool) -> str:
        return "Выбор цели: вручную" if manual_override else "Выбор цели: автоматически"

    def _friendly_install_stage(self, stage_name: str) -> str:
        mapping = {
            "Examining": "Проверка образа",
            "Extracting": "Распаковка",
            "Installing": "Установка образа",
            "Deleting old": "Очистка старых файлов",
            "Signature verified": "Проверка подписи",
            "Ожидание": "Ожидание установки",
        }
        return mapping.get(stage_name, stage_name or "Ожидание установки")

    def _severity_label(self, severity: str) -> str:
        mapping = {
            "info": "ИНФО",
            "warn": "ВНИМАНИЕ",
            "warning": "ВНИМАНИЕ",
            "error": "ОШИБКА",
            "success": "ГОТОВО",
        }
        return mapping.get(severity, severity.upper() if severity else "ИНФО")

    def _severity_bootstyle(self, severity: str) -> str:
        mapping = {
            "info": "info",
            "warn": "warning",
            "warning": "warning",
            "error": "danger",
            "success": "success",
        }
        return mapping.get(severity, "info")

    def _apply_operator_style(self, severity: str) -> None:
        style = self._severity_bootstyle(severity)
        self.operator_severity_var.set(self._severity_label(severity))
        if hasattr(self, "operator_card"):
            self.operator_card.configure(bootstyle=style)
        if hasattr(self, "operator_badge"):
            self.operator_badge.configure(bootstyle=style)

    def _state_badge_text(self, state_name: str) -> str:
        mapping = {
            "IDLE": "ГОТОВНОСТЬ",
            "DISCOVERING": "СКАНИРОВАНИЕ",
            "CONNECTING": "ПОДКЛЮЧЕНИЕ",
            "PRECHECK": "ПРЕДПРОВЕРКА",
            "ERASING": "СБРОС",
            "INSTALLING": "УСТАНОВКА",
            "REBOOTING": "ПЕРЕЗАГРУЗКА",
            "VERIFYING": "ПРОВЕРКА",
            "DONE": "ГОТОВО",
            "FAILED": "ОШИБКА",
        }
        return mapping.get(state_name, state_name or "СТАТУС")

    def _state_bootstyle(self, state_name: str) -> str:
        mapping = {
            "IDLE": "secondary",
            "DISCOVERING": "info",
            "CONNECTING": "primary",
            "PRECHECK": "primary",
            "ERASING": "warning",
            "INSTALLING": "info",
            "REBOOTING": "warning",
            "VERIFYING": "success",
            "DONE": "success",
            "FAILED": "danger",
        }
        return mapping.get(state_name, "secondary")

    def _apply_state_style(self, state_name: str) -> None:
        style = self._state_bootstyle(state_name)
        self.state_badge_var.set(self._state_badge_text(state_name))
        if hasattr(self, "state_card"):
            self.state_card.configure(bootstyle=style)
        if hasattr(self, "state_badge"):
            self.state_badge.configure(bootstyle=style)
        if hasattr(self, "status_strip_card"):
            self.status_strip_card.configure(bootstyle=style)

    def _on_scan(self) -> None:
        self._persist_settings()
        self._log_demo_ui_action("Запущен Scan")
        self.controller.scan_devices()

    def _on_stage1(self) -> None:
        if self.demo_mode:
            self._persist_settings()
            self._log_demo_ui_action("Запущен Stage 1")
            self.controller.run_stage1()
            return
        confirmed = messagebox.askyesno(
            "Этап 1: сброс",
            "Этап 1 выполнит write erase, удалит vlan.dat и перезагрузит устройство. Продолжить?",
        )
        if confirmed:
            self._persist_settings()
            self.controller.run_stage1()

    def _on_stage2(self) -> None:
        if not self.firmware_input_var.get().strip():
            messagebox.showwarning("Этап 2: установка", "Укажите имя файла прошивки.")
            return
        if self.demo_mode:
            self._persist_settings()
            self._log_demo_ui_action(
                "Запущен Stage 2",
                f"Файл: {self.firmware_input_var.get().strip()}",
            )
            self.controller.run_stage2(self.firmware_input_var.get().strip())
            return
        confirmed = messagebox.askyesno(
            "Этап 2: установка",
            "USB-накопитель вставлен в свитч и на нём лежит нужный tar-образ?",
        )
        if confirmed:
            self._persist_settings()
            self.controller.run_stage2(self.firmware_input_var.get().strip())

    def _on_stage3(self) -> None:
        self._persist_settings()
        self._log_demo_ui_action("Запущен Stage 3")
        self.controller.run_stage3()

    def _on_stop(self) -> None:
        self._log_demo_ui_action("Нажат Stop")
        self.controller.stop()

    def _on_target_selected(self, _event: object) -> None:
        if self._suppress_target_selection_event:
            return
        selection = self.targets_tree.selection()
        if not selection:
            return
        target_id = str(selection[0])
        if target_id == self.selected_target_var.get():
            return
        if self.controller.select_target(target_id):
            self._persist_settings(preferred_target_id=target_id)
            self._log_demo_ui_action("Выбрана цель", target_id)

    def _on_demo_scenario_selected(self, _event: object) -> None:
        if not self.demo_mode or not isinstance(self.controller, DemoReplayController):
            return
        scenario_display = self.demo_scenario_var.get()
        scenario_name = self.demo_display_to_name.get(scenario_display, "")
        if not scenario_name:
            return
        if self.controller.set_scenario(scenario_name):
            self.selected_demo_scenario_name = scenario_name
            self._refresh_demo_details()
            self._persist_settings()
            self._log_demo_ui_action("Выбран сценарий", scenario_display)

    def _on_diagnostics_tab_changed(self, event: object) -> None:
        if not self.demo_mode:
            return
        notebook = getattr(event, "widget", getattr(self, "diagnostics_notebook", None))
        if notebook is None:
            return
        try:
            tab_id = notebook.select()
            tab_text = str(notebook.tab(tab_id, "text"))
        except Exception:
            return
        if tab_text:
            self._log_demo_ui_action("Открыта вкладка", tab_text, level="debug")
            self._refresh_automation_map()

    def _log_demo_ui_action(self, action: str, detail: str = "", level: str = "info") -> None:
        if not self.demo_mode:
            return
        message = f"[DEMO][UI] {action}"
        if detail:
            message = f"{message}: {detail}"
        line = f"[{timestamp()}] {message}"
        append_session_log(self.log_path, line)
        self._enqueue_event(AppEvent("log", {"line": line, "level": level}))

    def _open_log(self) -> None:
        self._log_demo_ui_action("Открыт журнал", str(self.log_path))
        self._open_path(self.log_path)

    def _open_report(self) -> None:
        self._log_demo_ui_action("Открыт отчёт", str(self.report_path))
        self._open_path(self.report_path)

    def _open_transcript(self) -> None:
        self._log_demo_ui_action("Открыт транскрипт", str(self.transcript_path))
        self._open_path(self.transcript_path)

    def _open_logs_dir(self) -> None:
        self._log_demo_ui_action("Открыта папка логов", str(self.session.logs_dir))
        self._open_path(self.session.logs_dir)

    def _open_manifest(self) -> None:
        self._log_demo_ui_action("Открыт manifest", str(self.manifest_path))
        self._open_path(self.manifest_path)

    def _open_bundle(self) -> None:
        self._log_demo_ui_action("Открыт session bundle", str(self.bundle_path))
        self._open_path(self.bundle_path)

    def _open_session_folder(self) -> None:
        self._log_demo_ui_action("Открыта папка сессии", str(self.session_dir))
        self._open_path(self.session_dir)

    def _export_session_bundle(self) -> None:
        self._persist_settings()
        bundle_path = export_session_bundle(self.session)
        self.bundle_path = bundle_path
        self.bundle_path_var.set(str(bundle_path))
        self._refresh_artifact_statuses()
        self.footer_var.set(f"Session bundle сохранён: {bundle_path.name}")
        self._log_demo_ui_action("Экспортирован session bundle", str(bundle_path))

    def _open_path(self, path: Path) -> None:
        if not Path(path).exists():
            messagebox.showinfo("Артефакт пока не создан", f"Путь ещё не существует:\n{path}")
            return
        if self.smoke_mode:
            self.last_smoke_open_path = Path(path)
            self.footer_var.set(f"Smoke check: путь подтверждён -> {Path(path).name}")
            self._log_demo_ui_action("Smoke-mode open suppressed", str(path), level="debug")
            return
        try:
            # Intentional local file open in desktop UI.
            os.startfile(str(path))  # nosec
        except Exception:
            messagebox.showinfo("Путь к артефакту", str(path))

    def _drain_events(self) -> None:
        handled_any = False
        while True:
            try:
                event = self.event_queue.get_nowait()
            except Empty:
                break
            self._handle_event(event)
            handled_any = True
        if handled_any:
            self._refresh_automation_map()
        self.window.after(100, self._drain_events)

    def _handle_event(self, event: AppEvent) -> None:
        if event.kind == "session_paths":
            self.log_path = Path(str(event.payload["log_path"]))
            self.report_path = Path(str(event.payload["report_path"]))
            self.transcript_path = Path(
                str(event.payload.get("transcript_path", self.transcript_path))
            )
            self.settings_path = Path(str(event.payload.get("settings_path", self.settings_path)))
            self.session.settings_path = self.settings_path
            settings_snapshot_path = event.payload.get(
                "settings_snapshot_path",
                self.session.settings_snapshot_path,
            )
            self.session.settings_snapshot_path = Path(str(settings_snapshot_path))
            self.manifest_path = Path(str(event.payload.get("manifest_path", self.manifest_path)))
            self.bundle_path = Path(str(event.payload.get("bundle_path", self.bundle_path)))
            self.session.manifest_path = self.manifest_path
            self.session.bundle_path = self.bundle_path
            self.session_dir = Path(str(event.payload.get("session_dir", self.session_dir)))
            self.session.session_dir = self.session_dir
            self.session.log_path = self.log_path
            self.session.report_path = self.report_path
            self.session.transcript_path = self.transcript_path
            self.session_id_var.set(str(event.payload.get("session_id", self.session.session_id)))
            self.session_started_var.set(
                str(event.payload.get("session_started_label", self.session_started_var.get()))
            )
            self.session_started_at_value = float(
                event.payload.get("session_started_at", self.session_started_at_value or 0.0)
            )
            run_mode = event.payload.get("run_mode", self.session_mode_var.get())
            self.session_mode_var.set(str(run_mode))
            self._refresh_preflight_paths()
        elif event.kind == "log":
            self._append_log(str(event.payload["line"]), str(event.payload.get("level", "info")))
        elif event.kind == "state_changed":
            state_name = str(event.payload.get("state", ""))
            message = str(event.payload.get("message", state_name))
            self.state_var.set(message)
            self.footer_var.set(message)
            self._apply_state_style(state_name)
            self.current_stage_var.set(
                str(event.payload.get("current_stage", self.current_stage_var.get()))
            )
            self.last_scan_time_var.set(
                str(event.payload.get("last_scan_completed_at", self.last_scan_time_var.get()))
                or "Ещё не выполнялось"
            )
            session_elapsed = event.payload.get("session_elapsed_seconds")
            if session_elapsed is not None:
                self.session_duration_var.set(format_duration(float(session_elapsed)))
            stage_started_at = event.payload.get("stage_started_at")
            self.active_stage_started_at_value = (
                float(stage_started_at) if stage_started_at is not None else None
            )
            stage_elapsed = event.payload.get("stage_elapsed_seconds")
            if self.active_stage_started_at_value is None:
                self.active_stage_duration_var.set(
                    format_duration(float(stage_elapsed)) if stage_elapsed is not None else "—"
                )
            requested_firmware = str(
                event.payload.get("requested_firmware_name", self.firmware_input_var.get())
            )
            if requested_firmware and not self.firmware_input_var.get().strip():
                self.firmware_input_var.set(requested_firmware)
            if state_name == "DISCOVERING":
                self.scan_status_var.set("Идёт сканирование COM-портов...")
        elif event.kind == "actions_changed":
            self._set_button_state(self.scan_button, bool(event.payload.get("scan_enabled", False)))
            self._set_button_state(
                self.stage1_button, bool(event.payload.get("stage1_enabled", False))
            )
            self._set_button_state(
                self.stage2_button, bool(event.payload.get("stage2_enabled", False))
            )
            self._set_button_state(
                self.stage3_button, bool(event.payload.get("stage3_enabled", False))
            )
            self._set_button_state(self.stop_button, bool(event.payload.get("stop_enabled", False)))
        elif event.kind == "device_snapshot":
            snapshot = event.payload["snapshot"]
            target_id = getattr(snapshot, "port", "") or ""
            self.port_var.set(target_id or "—")
            self._update_selected_target(target_id)
            self.device_status_var.set(getattr(snapshot, "status_text", "Не определено"))
            self.model_var.set(getattr(snapshot, "model", "Не определена"))
            self.current_fw_var.set(getattr(snapshot, "firmware", "Не определена"))
            self.flash_var.set(getattr(snapshot, "flash", "Не определена"))
            self.uptime_var.set(getattr(snapshot, "uptime", "Не определено"))
            self.connection_var.set(
                self._friendly_connection_state(
                    getattr(snapshot, "connection_state", "unknown") or "unknown"
                )
            )
            self.prompt_var.set(self._friendly_prompt(getattr(snapshot, "prompt_type", "") or ""))
            self.operator_next_step_var.set(getattr(snapshot, "recommended_next_action", ""))
            self.manual_override_var.set(
                self._friendly_manual_override(bool(getattr(snapshot, "is_manual_override", False)))
            )
            usb_state = getattr(snapshot, "usb_state", "unknown")
            if usb_state == "ready":
                self.usb_var.set("USB обнаружен")
            elif usb_state == "missing":
                self.usb_var.set("USB не найден")
            else:
                self.usb_var.set("USB неизвестен")
        elif event.kind == "operator_message":
            message = event.payload["message"]
            severity = str(getattr(message, "severity", "info") or "info")
            self.operator_title_var.set(getattr(message, "title", ""))
            self.operator_detail_var.set(getattr(message, "detail", ""))
            self.operator_next_step_var.set(getattr(message, "next_step", ""))
            self._apply_operator_style(severity)
        elif event.kind == "progress":
            percent = int(event.payload.get("percent", 0))
            stage_name = self._friendly_install_stage(
                str(event.payload.get("stage_name", "Ожидание"))
            )
            stage_index = int(event.payload.get("stage_index", 0))
            total_stages = int(event.payload.get("total_stages", 0))
            self.progress.configure(value=percent, text=f"{percent}%")
            self.progress_stage_var.set(stage_name)
            self.progress_percent_var.set(f"{percent}%")
            if stage_index and total_stages:
                self.progress_meta_var.set(
                    f"Шаг {stage_index} из {total_stages}. Следите за журналом и транскриптом."
                )
            else:
                self.progress_meta_var.set(
                    "Прогресс установки обновляется по маркерам archive download-sw."
                )
        elif event.kind == "scan_results":
            results = list(event.payload.get("results", []))
            selected_target_id = str(event.payload.get("selected_target_id", ""))
            self._update_scan_status(results, selected_target_id)
            if hasattr(self, "targets_tree"):
                self._render_scan_results(results, selected_target_id)
        elif event.kind == "selected_target_changed":
            target_id = str(event.payload.get("target_id", ""))
            manual_override = bool(event.payload.get("manual_override", False))
            self._update_selected_target(target_id)
            self.manual_override_var.set(self._friendly_manual_override(manual_override))
            if target_id and hasattr(self, "targets_tree"):
                self._set_tree_selection(target_id)
                self._persist_settings(preferred_target_id=target_id)
        elif event.kind == "report_ready":
            self.report_path = Path(str(event.payload["report_path"]))
            self._refresh_preflight_paths()
            if hasattr(self, "report_button"):
                self.report_button.configure(state="normal")
            artifact_button = getattr(self, "artifact_report_button", None)
            if artifact_button is not None:
                artifact_button.configure(state="normal")

    def _render_scan_results(self, results: list[ScanResult], selected_target_id: str) -> None:
        self.scan_results = {result.target.id: result for result in results}
        existing = set(self.targets_tree.get_children(""))
        incoming = {result.target.id for result in results}
        for item_id in existing - incoming:
            self.targets_tree.delete(item_id)
        for result in results:
            values = (
                result.status_message,
                self._friendly_connection_state(result.connection_state),
                self._friendly_prompt(result.prompt_type or ""),
                result.version,
            )
            if self.targets_tree.exists(result.target.id):
                self.targets_tree.item(result.target.id, text=result.target.id, values=values)
            else:
                self.targets_tree.insert(
                    "", "end", iid=result.target.id, text=result.target.id, values=values
                )
        preferred = selected_target_id or self.settings.preferred_target_id
        if preferred and self.targets_tree.exists(preferred):
            self._set_tree_selection(preferred)
        elif results:
            first = results[0].target.id
            self._set_tree_selection(first, ensure_visible=False)

    def _set_button_state(self, button: ttk.Button, enabled: bool) -> None:
        button.configure(state="normal" if enabled else "disabled")

    def _append_log(self, line: str, level: str) -> None:
        tag = level if level in {"info", "ok", "warn", "error", "debug"} else "info"
        self.log_box.insert("end", line + "\n", tag)
        self.log_box.see("end")

    def _persist_settings(self, preferred_target_id: str | None = None) -> None:
        if not hasattr(self, "settings_path"):
            return
        existing = getattr(self, "settings", AppSettings())
        window_geometry = existing.window_geometry
        if hasattr(self.window, "geometry"):
            try:
                window_geometry = self.window.geometry()
            except Exception:
                window_geometry = existing.window_geometry
        current = AppSettings(
            firmware_name=self.firmware_input_var.get().strip() or existing.firmware_name,
            preferred_target_id=preferred_target_id
            if preferred_target_id is not None
            else existing.preferred_target_id,
            selected_transport="serial",
            demo_scenario_name=self.selected_demo_scenario_name or existing.demo_scenario_name,
            window_geometry=window_geometry,
        )
        self.settings = current
        save_settings(self.settings_path, current)
        snapshot_settings(self.settings_path, self.session.settings_snapshot_path)
        if hasattr(self.controller, "requested_firmware_name"):
            self.controller.requested_firmware_name = (
                self.firmware_input_var.get().strip() or self.profile.default_firmware
            )
        self._refresh_artifact_statuses()

    def _on_close(self) -> None:
        self._persist_settings()
        self.controller.dispose()
        guard = getattr(self, "_instance_guard", None)
        if guard is not None:
            guard.release()
        self.window.destroy()

    def run(self) -> None:
        self.window.mainloop()

    def _friendly_demo_actions(self, actions: tuple[str, ...]) -> str:
        labels = {
            "scan": "Scan",
            "stage1": "Stage 1",
            "stage2": "Stage 2",
            "stage3": "Stage 3",
        }
        return "Доступно: " + ", ".join(labels.get(action, action) for action in actions)

    def _refresh_demo_details(self) -> None:
        if not self.demo_mode:
            return
        scenario = self.demo_scenarios_by_name.get(self.selected_demo_scenario_name)
        if scenario is None and self.demo_scenarios_by_name:
            scenario = next(iter(self.demo_scenarios_by_name.values()))
            self.selected_demo_scenario_name = scenario.name
        if scenario is None:
            self.demo_scenario_var.set("")
            self.demo_description_var.set("Сценарии demo mode не найдены.")
            self.demo_actions_var.set("Доступно: —")
            self._refresh_automation_map()
            return
        self.demo_scenario_var.set(self.demo_name_to_display.get(scenario.name, scenario.name))
        self.demo_description_var.set(
            scenario.description or "Сценарий готов для click-smoke без оборудования."
        )
        self.demo_actions_var.set(self._friendly_demo_actions(scenario.supported_actions))
        self._refresh_automation_map()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CiscoAutoFlash desktop app")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the UI in dev-only replay mode without real hardware.",
    )
    parser.add_argument(
        "--demo-scenario",
        help="Optional replay scenario name to preselect in demo mode.",
    )
    args = parser.parse_args(argv)

    app = CiscoAutoFlashDesktop(
        demo_mode=args.demo,
        demo_scenario=args.demo_scenario,
    )
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
