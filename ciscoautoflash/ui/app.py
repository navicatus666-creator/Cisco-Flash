from __future__ import annotations

import argparse
import json
import os
import re
import threading
import time
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from queue import Empty, Queue
from tkinter import messagebox
from tkinter.scrolledtext import ScrolledText
from typing import Any, cast

import ttkbootstrap as ttk

try:
    from PIL import ImageGrab as _ImageGrab
except ImportError:  # pragma: no cover - optional runtime dependency
    _ImageGrab = cast(Any, None)
else:
    pass

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
from ..core.session_artifacts import (
    export_session_bundle,
    format_duration,
    snapshot_settings,
    update_manifest_artifacts,
)
from ..core.single_instance import SingleInstanceError, SingleInstanceGuard
from ..core.workflow import WorkflowController
from ..devtools.hardware_day import (
    build_connection_snapshot,
    describe_connection_snapshot,
    format_latest_preflight_status,
    load_operator_preflight_summary,
)
from ..profiles import build_c2960x_profile
from ..replay.adapter import DemoReplayController
from ..replay.loader import ReplayScenario

ImageGrab: Any | None = _ImageGrab


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


_LAYOUT_MAX_WIDTH = 1920
_LAYOUT_MAX_HEIGHT = 1080
_LAYOUT_DEFAULT_WIDTH = 1600
_LAYOUT_DEFAULT_HEIGHT = 960
_LAYOUT_MIN_WIDTH = 1440
_LAYOUT_MIN_HEIGHT = 860
_BRAND_COLORS = {
    "primary": "#0b5cab",
    "primary_active": "#084b8c",
    "primary_soft": "#d9e7f6",
    "accent": "#2aa2d8",
    "accent_soft": "#e1f3fb",
    "slate": "#34506a",
    "canvas": "#edf3f8",
    "surface": "#ffffff",
    "surface_alt": "#f7fbfe",
    "surface_shell": "#f0f5fb",
    "surface_muted": "#e2edf8",
    "border": "#c5d5e6",
    "border_strong": "#8fb1d4",
    "text": "#102a43",
    "muted": "#5b7188",
    "log_shell": "#eaf1f9",
    "log_bg": "#10253a",
    "log_fg": "#e5f4ff",
    "ok": "#2f9e6f",
    "warn": "#e0a100",
    "danger": "#d1495b",
}
_TITLE_FONT = ("Segoe UI", 22, "bold")
_TITLE_LABEL_FONT = ("Segoe UI", 10, "bold")
_VALUE_FONT = ("Segoe UI", 11, "bold")
_BADGE_FONT = ("Segoe UI", 9, "bold")
_STATUS_FONT = ("Segoe UI", 15, "bold")
_BUTTON_FONT = ("Segoe UI", 9, "bold")


def _parse_geometry_size(geometry: str | None) -> tuple[int, int] | None:
    if not geometry:
        return None
    match = re.match(r"^\s*(\d+)x(\d+)", geometry)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)))


def _resolve_window_layout_contract(
    saved_geometry: str | None,
    screen_width: int,
    screen_height: int,
) -> tuple[str, tuple[int, int], tuple[int, int]]:
    max_width = max(1, min(_LAYOUT_MAX_WIDTH, screen_width))
    max_height = max(1, min(_LAYOUT_MAX_HEIGHT, screen_height))
    min_width = min(max_width, _LAYOUT_MIN_WIDTH)
    min_height = min(max_height, _LAYOUT_MIN_HEIGHT)
    default_width = max(min_width, min(max_width, _LAYOUT_DEFAULT_WIDTH))
    default_height = max(min_height, min(max_height, _LAYOUT_DEFAULT_HEIGHT))

    parsed = _parse_geometry_size(saved_geometry)
    if parsed is None:
        width = default_width
        height = default_height
    else:
        width = max(min_width, min(parsed[0], max_width))
        height = max(min_height, min(parsed[1], max_height))

    return (f"{width}x{height}", (min_width, min_height), (max_width, max_height))


def _resolve_metrics_workspace_contract() -> dict[str, object]:
    return {
        "column_weights": (3, 2),
        "row_weights": (0, 1),
        "status_grid": {"row": 0, "column": 0, "columnspan": 1},
        "artifacts_grid": {"row": 0, "column": 1, "columnspan": 1},
        "diagnostics_grid": {"row": 1, "column": 0, "columnspan": 2},
    }


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
        self.demo_playback_delay_ms = max(1, _env_int("CISCOAUTOFLASH_DEMO_DELAY_MS", 70))
        self.auto_start_scan = _env_flag("CISCOAUTOFLASH_AUTO_START_SCAN", auto_start_scan)
        self.ui_smoke_mode = _env_flag("CISCOAUTOFLASH_UI_SMOKE", False)
        self.ui_smoke_close_ms = max(250, _env_int("CISCOAUTOFLASH_UI_SMOKE_CLOSE_MS", 1500))
        self._event_timeline: list[dict[str, Any]] = []
        self.operator_message_code = ""
        self.current_state_name = "IDLE"
        self._progress_percent_value = 0
        self._terminal_snapshot_state: str | None = None
        self._ui_smoke_after_id: str | None = None
        base_config = config or AppConfig()
        if self.demo_mode:
            self.config = replace(base_config, runtime_root=(base_config.runtime_root / "demo"))
        else:
            self.config = base_config
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
        self._demo_action_state = {
            "scan_enabled": False,
            "stage1_enabled": False,
            "stage2_enabled": False,
            "stage3_enabled": False,
            "stop_enabled": False,
        }
        self.demo_busy = False
        self.last_demo_idle_marker = ""

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
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        geometry, min_size, max_size = _resolve_window_layout_contract(
            self.settings.window_geometry,
            screen_width,
            screen_height,
        )
        self.window.geometry(geometry)
        self.window.minsize(*min_size)
        self.window.maxsize(*max_size)
        self.style = ttk.Style()
        self.palette = dict(_BRAND_COLORS)
        self._configure_brand_styles()

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
        self.event_timeline_path = self.session.event_timeline_path
        self.dashboard_snapshot_path = self.session.dashboard_snapshot_path
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
        self.device_status_summary_var = tk.StringVar(value="Порт ещё не сканировался")
        self.model_var = tk.StringVar(value="Определится после scan")
        self.current_fw_var = tk.StringVar(value="Определится после scan")
        self.flash_var = tk.StringVar(value="Определится после scan")
        self.uptime_var = tk.StringVar(value="Определится после scan")
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
            value="Маркеры archive download-sw появятся по ходу установки."
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
        self.hardware_gate_var = tk.StringVar(value="Локальный preflight ещё не запускался.")
        self.hardware_day_status_var = tk.StringVar(
            value="Сначала прогоните local preflight, затем подключайте console path."
        )
        self.hardware_console_var = tk.StringVar(
            value="COM-порты ещё не проверялись из hardware-day summary."
        )
        self.hardware_ethernet_var = tk.StringVar(
            value="Ethernet-статус будет показан после локальной проверки."
        )
        self.hardware_ssh_var = tk.StringVar(
            value="Host не задан; optional hidden SSH pass пока не оценивался."
        )
        self.hardware_live_run_var = tk.StringVar(
            value="console -> scan -> stage1 -> stage2 -> stage3 -> bundle"
        )
        self.hardware_return_var = tk.StringVar(
            value="session bundle -> session folder -> triage_session_return.py"
        )
        self._hardware_day_refresh_queue: Queue[dict[str, Any]] = Queue()
        self._hardware_day_refresh_request_token = 0
        self._hardware_day_refresh_applied_token = 0
        self._hardware_day_refresh_inflight = False
        self._hardware_day_refresh_pending = False
        self._hardware_day_refresh_after_id: str | None = None
        self._hardware_day_periodic_after_id: str | None = None
        self._hardware_day_refresh_closed = False

        self._build_ui()
        self._refresh_demo_details()
        self._refresh_preflight_paths()
        self._refresh_artifact_statuses()
        self._schedule_hardware_day_refresh(delay_ms=0)
        self._schedule_hardware_day_periodic_refresh()
        self._apply_state_style("IDLE")
        self._apply_operator_style("info")
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
        self._schedule_ui_smoke_close()

    def _enqueue_event(self, event: AppEvent) -> None:
        self.event_queue.put(event)

    def _configure_brand_styles(self) -> None:
        palette = self.palette
        style = self.style
        self.window.configure(background=palette["canvas"])

        style.configure("UiA.TFrame", background=palette["canvas"])
        style.configure("UiB.TFrame", background=palette["surface"])
        style.configure("UiC.TFrame", background=palette["surface_shell"])
        style.configure(
            "UiD.TLabelframe",
            background=palette["surface_alt"],
            bordercolor=palette["border"],
            relief="flat",
            borderwidth=1,
            lightcolor=palette["border"],
            darkcolor=palette["border"],
        )
        style.configure(
            "UiD.TLabelframe.Label",
            background=palette["surface_alt"],
            foreground=palette["slate"],
            font=_TITLE_LABEL_FONT,
        )
        style.configure(
            "UiE.TLabelframe",
            background=palette["surface"],
            bordercolor=palette["border_strong"],
            relief="flat",
            borderwidth=1,
            lightcolor=palette["border_strong"],
            darkcolor=palette["border_strong"],
        )
        style.configure(
            "UiE.TLabelframe.Label",
            background=palette["surface"],
            foreground=palette["primary"],
            font=_TITLE_LABEL_FONT,
        )
        for style_name, border in (
            ("UiF.TLabelframe", palette["slate"]),
            ("UiG.TLabelframe", palette["accent"]),
            ("UiH.TLabelframe", palette["primary"]),
            ("UiI.TLabelframe", palette["warn"]),
            ("UiJ.TLabelframe", palette["ok"]),
            ("UiK.TLabelframe", palette["danger"]),
        ):
            style.configure(
                style_name,
                background=palette["surface"],
                bordercolor=border,
                relief="solid",
                borderwidth=1,
                lightcolor=border,
                darkcolor=border,
            )
            style.configure(
                f"{style_name}.Label",
                background=palette["surface"],
                foreground=border,
                font=_TITLE_LABEL_FONT,
            )

        style.configure(
            "UiL.TLabel",
            background=palette["canvas"],
            foreground=palette["primary"],
            font=_TITLE_FONT,
        )
        style.configure(
            "UiM.TLabel",
            background=palette["canvas"],
            foreground=palette["muted"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "UiN.TLabel",
            background=palette["surface"],
            foreground=palette["text"],
            font=_VALUE_FONT,
        )
        style.configure(
            "UiO.TLabel",
            background=palette["surface"],
            foreground=palette["muted"],
            font=("Segoe UI", 9),
        )
        style.configure(
            "UiP.TLabel",
            background=palette["surface"],
            foreground=palette["text"],
            font=_STATUS_FONT,
        )
        style.configure(
            "UiQ.TLabel",
            background=palette["primary_soft"],
            foreground=palette["primary"],
            font=_BADGE_FONT,
            padding=(10, 4),
        )
        style.configure("UiAA.TFrame", background=palette["surface_shell"])
        style.configure(
            "UiAB.TLabel",
            background=palette["surface_shell"],
            foreground=palette["slate"],
            font=("Segoe UI Semibold", 8),
        )
        style.configure(
            "UiAC.TLabel",
            background=palette["surface_shell"],
            foreground=palette["text"],
            font=("Segoe UI Semibold", 11),
        )
        style.configure(
            "UiAD.TLabel",
            background=palette["surface_shell"],
            foreground=palette["muted"],
            font=("Segoe UI", 8),
        )
        style.configure(
            "UiR.Treeview",
            background=palette["surface"],
            fieldbackground=palette["surface"],
            foreground=palette["text"],
            bordercolor=palette["border"],
            lightcolor=palette["border"],
            darkcolor=palette["border"],
            rowheight=30,
            relief="flat",
            font=("Segoe UI", 9),
        )
        style.map(
            "UiR.Treeview",
            background=[("selected", palette["primary"])],
            foreground=[("selected", palette["surface"])],
        )
        style.configure(
            "UiR.Treeview.Heading",
            background=palette["primary"],
            foreground=palette["surface"],
            bordercolor=palette["primary"],
            relief="flat",
            padding=(10, 8),
            font=_TITLE_LABEL_FONT,
        )
        style.map(
            "UiR.Treeview.Heading",
            background=[("active", palette["primary_active"])],
            foreground=[("active", palette["surface"])],
        )
        style.configure(
            "UiS.TNotebook",
            background=palette["surface_shell"],
            bordercolor=palette["border"],
            tabmargins=(0, 0, 0, 0),
        )
        style.configure(
            "UiS.TNotebook.Tab",
            background=palette["surface_shell"],
            foreground=palette["muted"],
            bordercolor=palette["border"],
            padding=(12, 7),
            font=_BADGE_FONT,
        )
        style.map(
            "UiS.TNotebook.Tab",
            background=[
                ("selected", palette["primary"]),
                ("active", palette["surface_alt"]),
            ],
            foreground=[
                ("selected", palette["surface"]),
                ("active", palette["primary"]),
            ],
        )
        for style_name, background, foreground in (
            ("UiT.TButton", palette["primary"], palette["surface"]),
            ("UiU.TButton", palette["accent"], palette["text"]),
            ("UiV.TButton", palette["ok"], palette["surface"]),
            ("UiW.TButton", palette["warn"], palette["text"]),
            ("UiX.TButton", palette["danger"], palette["surface"]),
            ("UiY.TButton", palette["surface_shell"], palette["primary"]),
        ):
            style.configure(
                style_name,
                background=background,
                foreground=foreground,
                bordercolor=background,
                darkcolor=background,
                lightcolor=background,
                focusthickness=0,
                focuscolor=background,
                relief="flat",
                padding=(10, 8),
                font=_BUTTON_FONT,
            )
            style.map(
                style_name,
                background=[("active", background), ("pressed", background)],
                foreground=[("active", foreground), ("pressed", foreground)],
            )

    def _state_card_style(self, state_name: str) -> str:
        mapping = {
            "IDLE": "UiF.TLabelframe",
            "DISCOVERING": "UiG.TLabelframe",
            "CONNECTING": "UiH.TLabelframe",
            "PRECHECK": "UiH.TLabelframe",
            "ERASING": "UiI.TLabelframe",
            "INSTALLING": "UiG.TLabelframe",
            "REBOOTING": "UiI.TLabelframe",
            "VERIFYING": "UiJ.TLabelframe",
            "DONE": "UiJ.TLabelframe",
            "FAILED": "UiK.TLabelframe",
        }
        return mapping.get(state_name, "UiF.TLabelframe")

    def _build_ui(self) -> None:
        root = self.window
        root.configure(padx=14, pady=14, background=self.palette["canvas"])

        self.status_strip_card = ttk.Labelframe(
            root,
            text=" ",
            padding=4,
            style="UiF.TLabelframe",
        )
        self.status_strip_card.pack(fill="x", pady=(0, 8))
        self.status_strip_card.columnconfigure(0, weight=2)
        self.status_strip_card.columnconfigure(1, weight=5)
        self.status_strip_card.columnconfigure(2, weight=3)

        status_title = ttk.Frame(self.status_strip_card, style="UiB.TFrame")
        status_title.grid(row=0, column=0, sticky="w")
        ttk.Label(status_title, text="CiscoAutoFlash", style="UiL.TLabel").pack(anchor="w")
        ttk.Label(
            status_title,
            text="Операторская консоль",
            style="UiM.TLabel",
        ).pack(anchor="w", pady=(1, 0))

        status_primary = ttk.Frame(self.status_strip_card, style="UiB.TFrame")
        status_primary.grid(row=0, column=1, sticky="nsew", padx=(12, 12))
        status_primary.columnconfigure(0, weight=1)
        self.state_message_label = ttk.Label(
            status_primary,
            textvariable=self.state_var,
            style="UiP.TLabel",
            justify="left",
            anchor="w",
        )
        self.state_message_label.grid(row=0, column=0, sticky="ew")
        self._bind_responsive_wrap(self.state_message_label, status_primary, min_wrap=260)
        self.device_status_label = ttk.Label(
            status_primary,
            textvariable=self.device_status_summary_var,
            style="UiO.TLabel",
            justify="left",
            anchor="w",
        )
        self.device_status_label.grid(row=1, column=0, sticky="ew", pady=(1, 0))
        self._bind_responsive_wrap(self.device_status_label, status_primary, min_wrap=180)

        status_meta = ttk.Frame(self.status_strip_card, style="UiB.TFrame")
        status_meta.grid(row=0, column=2, sticky="e")
        self.state_badge = ttk.Label(
            status_meta,
            textvariable=self.state_badge_var,
            style="UiQ.TLabel",
        )
        self.state_badge.pack(anchor="e")
        if self.demo_mode:
            self.demo_badge = ttk.Label(
                status_meta,
                textvariable=self.demo_badge_var,
                style="UiQ.TLabel",
            )
            self.demo_badge.pack(anchor="e", pady=(6, 0))
        ttk.Label(status_meta, text="Режим", style="UiO.TLabel").pack(anchor="e", pady=(6, 0))
        ttk.Label(
            status_meta,
            textvariable=self.transport_mode_var,
            style="UiN.TLabel",
        ).pack(anchor="e")

        self.workspace_notebook = ttk.Notebook(root, style="UiS.TNotebook")
        self.workspace_notebook.pack(fill="both", expand=True)

        flash_workspace_tab = ttk.Frame(self.workspace_notebook, padding=4, style="UiA.TFrame")
        metrics_workspace_tab = ttk.Frame(
            self.workspace_notebook, padding=4, style="UiA.TFrame"
        )
        self.workspace_notebook.add(flash_workspace_tab, text="Прошивка")
        self.workspace_notebook.add(metrics_workspace_tab, text="Состояние и артефакты")

        body = ttk.Frame(flash_workspace_tab, style="UiA.TFrame")
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=2, minsize=280)
        body.columnconfigure(1, weight=10, minsize=1040)
        body.rowconfigure(0, weight=1)

        left_panel = ttk.Frame(body, padding=2, style="UiA.TFrame")
        left_panel.grid(row=0, column=0, sticky="new", padx=(0, 8))
        left_panel.columnconfigure(0, weight=1)

        center_panel = ttk.Frame(body, padding=2, style="UiA.TFrame")
        center_panel.grid(row=0, column=1, sticky="nsew")
        center_panel.columnconfigure(0, weight=1)
        center_panel.rowconfigure(0, weight=1)

        targets_card = ttk.Labelframe(
            left_panel,
            text="Найденные устройства",
            padding=10,
            style="UiE.TLabelframe",
        )
        targets_card.grid(row=0, column=0, sticky="new")
        targets_card.columnconfigure(0, weight=1)
        scan_status_label = ttk.Label(
            targets_card,
            textvariable=self.scan_status_var,
            style="UiO.TLabel",
            justify="left",
            anchor="w",
        )
        scan_status_label.grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        self._bind_responsive_wrap(scan_status_label, targets_card, min_wrap=220)
        self.targets_tree = ttk.Treeview(
            targets_card,
            columns=("status", "state"),
            show="tree headings",
            height=7,
            selectmode="browse",
            style="UiR.Treeview",
        )
        self.targets_tree.heading("#0", text="Порт")
        self.targets_tree.heading("status", text="Статус")
        self.targets_tree.heading("state", text="Соединение")
        self.targets_tree.column("#0", width=94, stretch=False)
        self.targets_tree.column("status", width=180, stretch=True)
        self.targets_tree.column("state", width=96, stretch=False)
        self.targets_tree.grid(row=1, column=0, sticky="nsew")
        self.targets_tree.bind("<<TreeviewSelect>>", self._on_target_selected)
        tree_scroll = ttk.Scrollbar(
            targets_card, orient="vertical", command=self.targets_tree.yview
        )
        tree_scroll.grid(row=1, column=1, sticky="ns")
        self.targets_tree.configure(yscrollcommand=tree_scroll.set)
        ttk.Separator(targets_card).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 8))
        ttk.Label(
            targets_card,
            text="Текущая цель",
            style="UiAB.TLabel",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 6))
        selected_target_summary = ttk.Frame(targets_card, style="UiC.TFrame")
        selected_target_summary.grid(row=4, column=0, columnspan=2, sticky="ew")
        selected_target_summary.columnconfigure(1, weight=1)
        self._build_preflight_value(
            selected_target_summary, 0, 0, "Порт", self.selected_target_var, min_wrap=140
        )
        self._build_preflight_value(
            selected_target_summary, 1, 0, "Соединение", self.connection_var, min_wrap=140
        )

        workflow_card = ttk.Labelframe(
            center_panel,
            text="Пульт оператора",
            padding=10,
            style="UiD.TLabelframe",
        )
        workflow_card.grid(row=0, column=0, sticky="nsew")
        workflow_card.columnconfigure(0, weight=1)
        workflow_card.rowconfigure(2, weight=1)

        summary_grid = ttk.Frame(workflow_card, style="UiAA.TFrame")
        summary_grid.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for column in range(3):
            summary_grid.columnconfigure(column, weight=1, uniform="summary")
        self._build_summary_card(
            summary_grid,
            0,
            0,
            "Порт и выбор",
            self.selected_target_var,
            self.manual_override_var,
        )
        self._build_summary_card(
            summary_grid,
            0,
            1,
            "Связь и статус",
            self.connection_var,
            self.device_status_summary_var,
        )
        self._build_summary_card(
            summary_grid,
            0,
            2,
            "Устройство и IOS",
            self.model_var,
            self.current_fw_var,
        )

        controls = ttk.Frame(workflow_card, style="UiA.TFrame")
        controls.grid(row=1, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(4, weight=1)

        action_strip = ttk.Frame(controls, padding=(10, 8), style="UiAA.TFrame")
        action_strip.grid(row=0, column=0, sticky="ew")
        action_strip.columnconfigure(1, weight=1)
        action_strip.columnconfigure(3, minsize=16)
        action_strip.columnconfigure(8, weight=1)
        ttk.Label(action_strip, text="Сканирование и этапы", style="UiAB.TLabel").grid(
            row=0, column=0, columnspan=9, sticky="w", pady=(0, 6)
        )
        ttk.Label(action_strip, text="Firmware", style="UiAB.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 8)
        )
        firmware_entry = ttk.Entry(action_strip, textvariable=self.firmware_input_var)
        firmware_entry.grid(row=1, column=1, sticky="ew", padx=(0, 10))

        self.scan_button = ttk.Button(
            action_strip,
            text="Сканировать",
            style="UiT.TButton",
            command=self._on_scan,
        )
        self.scan_button.grid(row=1, column=2, sticky="ew")
        ttk.Label(action_strip, text="Этапы", style="UiAB.TLabel").grid(
            row=1, column=4, sticky="w", padx=(10, 8)
        )
        self.stage1_button = ttk.Button(
            action_strip,
            text="Этап 1",
            style="UiW.TButton",
            command=self._on_stage1,
        )
        self.stage1_button.grid(row=1, column=5, padx=(0, 4), sticky="ew")
        self.stage2_button = ttk.Button(
            action_strip,
            text="Этап 2",
            style="UiU.TButton",
            command=self._on_stage2,
        )
        self.stage2_button.grid(row=1, column=6, padx=4, sticky="ew")
        self.stage3_button = ttk.Button(
            action_strip,
            text="Этап 3",
            style="UiV.TButton",
            command=self._on_stage3,
        )
        self.stage3_button.grid(row=1, column=7, padx=(4, 4), sticky="ew")
        self.stop_button = ttk.Button(
            action_strip,
            text="Стоп",
            style="UiX.TButton",
            command=self._on_stop,
        )
        self.stop_button.grid(row=1, column=8, sticky="ew")
        stage_hint_label = ttk.Label(
            action_strip,
            text="Порядок: scan -> 1 -> 2 -> 3.",
            style="UiAD.TLabel",
            justify="left",
            anchor="w",
        )
        stage_hint_label.grid(row=2, column=0, columnspan=9, sticky="ew", pady=(6, 0))
        self._bind_responsive_wrap(stage_hint_label, action_strip, min_wrap=320)

        live_grid = ttk.Frame(workflow_card, style="UiA.TFrame")
        live_grid.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        live_grid.columnconfigure(0, weight=6)
        live_grid.columnconfigure(1, weight=4)
        live_grid.rowconfigure(0, weight=1)
        live_grid.rowconfigure(1, weight=1)

        self.operator_card = ttk.Labelframe(
            live_grid,
            text="Главное сейчас",
            padding=10,
            style="UiD.TLabelframe",
        )
        self.operator_card.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0, 8))
        self.operator_card.columnconfigure(0, weight=1)
        operator_header = ttk.Frame(self.operator_card, style="UiC.TFrame")
        operator_header.pack(fill="x")
        ttk.Label(
            operator_header,
            textvariable=self.operator_title_var,
            style="UiN.TLabel",
        ).pack(side="left", anchor="w")
        self.operator_badge = ttk.Label(
            operator_header,
            textvariable=self.operator_severity_var,
            style="UiQ.TLabel",
        )
        self.operator_badge.pack(side="right", anchor="e")
        self.operator_detail_label = ttk.Label(
            self.operator_card,
            textvariable=self.operator_detail_var,
            justify="left",
            style="UiO.TLabel",
            anchor="w",
        )
        self.operator_detail_label.pack(fill="x", anchor="w", pady=(4, 2))
        self._bind_responsive_wrap(self.operator_detail_label, self.operator_card, min_wrap=280)
        ttk.Separator(self.operator_card).pack(fill="x", pady=(8, 8))
        ttk.Label(
            self.operator_card,
            text="Следующий шаг",
            style="UiAB.TLabel",
        ).pack(anchor="w")
        self.operator_next_step_label = ttk.Label(
            self.operator_card,
            textvariable=self.operator_next_step_var,
            justify="left",
            anchor="w",
            style="UiO.TLabel",
        )
        self.operator_next_step_label.pack(fill="x", anchor="w", pady=(4, 0))
        self._bind_responsive_wrap(self.operator_next_step_label, self.operator_card, min_wrap=280)

        bottom_context_card = ttk.Labelframe(
            live_grid,
            text="Ход операции и цель",
            padding=10,
            style="UiD.TLabelframe",
        )
        bottom_context_card.grid(row=1, column=0, columnspan=2, sticky="nsew")
        bottom_context_card.columnconfigure(0, weight=3, uniform="mission")
        bottom_context_card.columnconfigure(1, weight=2, uniform="mission")

        operation_context_card = ttk.Frame(bottom_context_card, style="UiC.TFrame")
        operation_context_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        ttk.Label(
            operation_context_card,
            text="Ход прошивки",
            style="UiAB.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        for column in range(2):
            operation_context_card.columnconfigure(column, weight=1, uniform="context")
        self._build_shell_fact_card(
            operation_context_card, 1, 0, "Этап", self.current_stage_var, min_wrap=180
        )
        self._build_shell_fact_card(
            operation_context_card,
            1,
            1,
            "Последний scan",
            self.last_scan_time_var,
            min_wrap=180,
        )
        self._build_shell_fact_card(
            operation_context_card,
            2,
            0,
            "Выбор цели",
            self.manual_override_var,
            min_wrap=180,
        )
        self._build_shell_fact_card(
            operation_context_card,
            2,
            1,
            "Соединение",
            self.connection_var,
            min_wrap=180,
        )
        progress_section = ttk.Frame(operation_context_card, style="UiC.TFrame")
        progress_section.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        progress_section.columnconfigure(0, weight=1)
        ttk.Label(
            progress_section,
            textvariable=self.progress_stage_var,
            style="UiN.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Floodgauge(
            progress_section,
            value=0,
            maximum=100,
            text=self.progress_percent_var.get(),
            bootstyle="primary",
            thickness=18,
        )
        self.progress.grid(row=1, column=0, sticky="ew", pady=(6, 6))
        self.progress_meta_label = ttk.Label(
            progress_section,
            textvariable=self.progress_meta_var,
            style="UiO.TLabel",
            justify="left",
            anchor="w",
        )
        self.progress_meta_label.grid(row=2, column=0, sticky="ew", pady=(0, 0))
        self._bind_responsive_wrap(self.progress_meta_label, progress_section, min_wrap=420)

        status_side_card = ttk.Frame(bottom_context_card, style="UiC.TFrame")
        status_side_card.grid(row=0, column=1, sticky="nsew")
        ttk.Label(
            status_side_card,
            text="Данные цели",
            style="UiAB.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        progress_facts = ttk.Frame(status_side_card, style="UiC.TFrame")
        progress_facts.grid(row=1, column=0, sticky="ew")
        for column in range(2):
            progress_facts.columnconfigure(column, weight=1, uniform="facts")
        self._build_shell_fact_card(
            progress_facts, 0, 0, "IOS", self.current_fw_var, min_wrap=180
        )
        self._build_shell_fact_card(
            progress_facts, 0, 1, "Модель", self.model_var, min_wrap=180
        )
        self._build_shell_fact_card(
            progress_facts, 1, 0, "Flash", self.flash_var, min_wrap=180
        )
        self._build_shell_fact_card(
            progress_facts, 1, 1, "Uptime", self.uptime_var, min_wrap=180
        )
        self._build_shell_fact_card(
            progress_facts, 2, 0, "USB", self.usb_var, min_wrap=180
        )
        self._build_shell_fact_card(
            progress_facts, 2, 1, "Статус", self.device_status_summary_var, min_wrap=180
        )

        if self.demo_mode:
            demo_card = ttk.Labelframe(
                controls, text="Demo-сценарий", padding=10, style="UiD.TLabelframe"
            )
            demo_card.grid(row=1, column=0, sticky="ew", pady=(8, 0))
            ttk.Label(
                demo_card,
                text="Dev-only проигрывание сценариев без оборудования",
                style="UiO.TLabel",
            ).pack(anchor="w")
            self.demo_selector = ttk.Combobox(
                demo_card,
                textvariable=self.demo_scenario_var,
                state="readonly",
                values=list(self.demo_display_to_name),
            )
            self.demo_selector.pack(fill="x", pady=(6, 8))
            self.demo_selector.bind("<<ComboboxSelected>>", self._on_demo_scenario_selected)
            self.demo_scenario_buttons: dict[str, ttk.Button] = {}
            buttons_frame = ttk.Frame(demo_card)
            buttons_frame.pack(fill="x", pady=(0, 8))
            buttons_frame.columnconfigure(0, weight=1)
            buttons_frame.columnconfigure(1, weight=1)
            for index, scenario in enumerate(self.demo_scenarios_by_name.values()):
                button = ttk.Button(
                    buttons_frame,
                    text=scenario.display_name,
                    style="UiY.TButton",
                    command=lambda scenario_name=scenario.name: self._on_demo_scenario_button(
                        scenario_name
                    ),
                )
                button.grid(
                    row=index // 2,
                    column=index % 2,
                    padx=4,
                    pady=4,
                    sticky="ew",
                )
                self.demo_scenario_buttons[scenario.name] = button
            ttk.Label(
                demo_card,
                textvariable=self.demo_description_var,
                style="UiO.TLabel",
                justify="left",
                wraplength=320,
            ).pack(anchor="w")
            ttk.Label(
                demo_card,
                textvariable=self.demo_actions_var,
                justify="left",
                wraplength=320,
            ).pack(anchor="w", pady=(8, 0))

        metrics_body = ttk.Frame(metrics_workspace_tab, style="UiA.TFrame")
        metrics_body.pack(fill="both", expand=True)
        metrics_contract = _resolve_metrics_workspace_contract()
        column_weights = cast(tuple[int, int], metrics_contract["column_weights"])
        row_weights = cast(tuple[int, int], metrics_contract["row_weights"])
        metrics_body.columnconfigure(0, weight=column_weights[0], minsize=720)
        metrics_body.columnconfigure(1, weight=column_weights[1], minsize=480)
        metrics_body.rowconfigure(0, weight=row_weights[0])
        metrics_body.rowconfigure(1, weight=row_weights[1])

        status_stack = ttk.Frame(metrics_body, style="UiA.TFrame")
        status_grid = cast(dict[str, int], metrics_contract["status_grid"])
        status_stack.grid(
            row=status_grid["row"],
            column=status_grid["column"],
            columnspan=status_grid["columnspan"],
            sticky="nsew",
            padx=(0, 10),
            pady=(0, 10),
        )
        status_stack.columnconfigure(0, weight=1)
        status_stack.rowconfigure(0, weight=1)
        status_stack.rowconfigure(1, weight=1)

        utility_card = ttk.Labelframe(
            metrics_body,
            text="Артефакты сессии",
            padding=8,
            style="UiD.TLabelframe",
        )
        artifacts_grid = cast(dict[str, int], metrics_contract["artifacts_grid"])
        utility_card.grid(
            row=artifacts_grid["row"],
            column=artifacts_grid["column"],
            columnspan=artifacts_grid["columnspan"],
            sticky="nsew",
            pady=(0, 10),
        )
        utility_card.columnconfigure(1, weight=1)
        utility_card.columnconfigure(2, weight=1)
        self.artifacts_intro_label = ttk.Label(
            utility_card,
            text=(
                "Все файлы текущей сессии и быстрые действия "
                "для возврата артефактов собраны здесь."
            ),
            style="UiO.TLabel",
            justify="left",
            anchor="w",
        )
        self.artifacts_intro_label.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 10))
        self._bind_responsive_wrap(self.artifacts_intro_label, utility_card, min_wrap=360)

        utility_actions = ttk.Frame(utility_card, style="UiB.TFrame")
        utility_actions.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 10))
        for column in range(3):
            utility_actions.columnconfigure(column, weight=1)
        self.logs_dir_button = ttk.Button(
            utility_actions,
            text="Открыть папку логов",
            style="UiY.TButton",
            command=self._open_logs_dir,
        )
        self.logs_dir_button.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self.session_folder_button = ttk.Button(
            utility_actions,
            text="Открыть папку сессии",
            style="UiY.TButton",
            command=self._open_session_folder,
        )
        self.session_folder_button.grid(row=0, column=1, padx=4, sticky="ew")
        self.bundle_export_button = ttk.Button(
            utility_actions,
            text="Экспортировать bundle",
            style="UiY.TButton",
            command=self._export_session_bundle,
        )
        self.bundle_export_button.grid(row=0, column=2, padx=(4, 0), sticky="ew")

        overview_card = ttk.Labelframe(
            status_stack,
            text="Контекст и готовность",
            padding=8,
            style="UiD.TLabelframe",
        )
        overview_card.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        for column in (1, 3):
            overview_card.columnconfigure(column, weight=1)
        self._build_preflight_value(overview_card, 0, 0, "Выбранная цель", self.selected_target_var)
        self._build_preflight_value(overview_card, 0, 2, "Firmware", self.firmware_input_var)
        self._build_preflight_value(overview_card, 1, 0, "ID сессии", self.session_id_var)
        self._build_preflight_value(overview_card, 1, 2, "Статус", self.state_badge_var)
        self._build_preflight_value(overview_card, 2, 0, "Локальный gate", self.hardware_gate_var)
        self._build_preflight_value(
            overview_card, 2, 2, "Готовность к железу", self.hardware_day_status_var
        )
        self._build_preflight_value(overview_card, 3, 0, "Console / USB", self.hardware_console_var)
        self._build_preflight_value(overview_card, 3, 2, "Ethernet", self.hardware_ethernet_var)
        self._build_preflight_value(overview_card, 4, 0, "Optional SSH", self.hardware_ssh_var)
        self._build_preflight_value(
            overview_card, 4, 2, "Возврат артефактов", self.hardware_return_var
        )

        execution_card = ttk.Labelframe(
            status_stack,
            text="Подсказка оператора",
            padding=8,
            style="UiD.TLabelframe",
        )
        execution_card.grid(row=1, column=0, sticky="nsew")
        execution_card.columnconfigure(0, weight=1)
        metrics_operator_card = ttk.Frame(execution_card, style="UiC.TFrame")
        metrics_operator_card.grid(row=0, column=0, sticky="nsew")
        metrics_operator_card.columnconfigure(0, weight=1)
        metrics_operator_header = ttk.Frame(metrics_operator_card, style="UiC.TFrame")
        metrics_operator_header.pack(fill="x")
        ttk.Label(
            metrics_operator_header,
            textvariable=self.operator_title_var,
            style="UiN.TLabel",
        ).pack(side="left", anchor="w")
        ttk.Label(
            metrics_operator_header,
            textvariable=self.operator_severity_var,
            style="UiQ.TLabel",
        ).pack(side="right", anchor="e")
        metrics_detail_label = ttk.Label(
            metrics_operator_card,
            textvariable=self.operator_detail_var,
            justify="left",
            anchor="w",
            style="UiO.TLabel",
        )
        metrics_detail_label.pack(fill="x", anchor="w", pady=(4, 2))
        self._bind_responsive_wrap(metrics_detail_label, metrics_operator_card, min_wrap=260)
        metrics_next_step_label = ttk.Label(
            metrics_operator_card,
            textvariable=self.operator_next_step_var,
            justify="left",
            anchor="w",
            style="UiO.TLabel",
        )
        metrics_next_step_label.pack(fill="x", anchor="w", pady=(0, 8))
        self._bind_responsive_wrap(metrics_next_step_label, metrics_operator_card, min_wrap=260)
        metrics_meta = ttk.Frame(metrics_operator_card, style="UiC.TFrame")
        metrics_meta.pack(fill="x")
        metrics_meta.columnconfigure(0, weight=1)
        metrics_meta.columnconfigure(1, weight=1)
        ttk.Label(
            metrics_meta,
            textvariable=self.current_stage_var,
            style="UiO.TLabel",
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            metrics_meta,
            textvariable=self.last_scan_time_var,
            style="UiO.TLabel",
            anchor="w",
        ).grid(row=0, column=1, sticky="w", padx=(12, 0))
        diagnostics_card = ttk.Labelframe(
            metrics_body,
            text="Журнал и памятка",
            padding=8,
            style="UiD.TLabelframe",
        )
        diagnostics_grid = cast(dict[str, int], metrics_contract["diagnostics_grid"])
        diagnostics_card.grid(
            row=diagnostics_grid["row"],
            column=diagnostics_grid["column"],
            columnspan=diagnostics_grid["columnspan"],
            sticky="nsew",
        )
        diagnostics_card.columnconfigure(0, weight=1)
        diagnostics_card.rowconfigure(0, weight=1)

        self.diagnostics_notebook = ttk.Notebook(diagnostics_card, style="UiS.TNotebook")
        self.diagnostics_notebook.grid(row=0, column=0, sticky="nsew")

        log_tab = ttk.Frame(self.diagnostics_notebook, padding=8, style="UiB.TFrame")
        self.diagnostics_notebook.add(log_tab, text="Журнал")
        legend = ttk.Frame(log_tab, style="UiB.TFrame")
        legend.pack(fill="x", pady=(0, 8))
        for label, style in (
            ("info", "secondary"),
            ("ok", "success"),
            ("warn", "warning"),
            ("error", "danger"),
            ("debug", "info"),
        ):
            ttk.Label(legend, text=label.upper(), bootstyle=style).pack(side="left", padx=(0, 6))
        ttk.Label(legend, text="Текущая операция", style="UiO.TLabel").pack(side="right")
        self.log_box = ScrolledText(
            log_tab,
            font=("Consolas", 10),
            wrap="word",
            relief="flat",
            borderwidth=0,
        )
        self.log_box.pack(fill="both", expand=True)
        self.log_box.configure(
            background=self.palette["log_bg"],
            foreground=self.palette["log_fg"],
            insertbackground=self.palette["log_fg"],
        )
        self.log_box.tag_config("info", foreground=self.palette["log_fg"])
        self.log_box.tag_config("ok", foreground="#8dd9b5")
        self.log_box.tag_config("warn", foreground="#ffd166")
        self.log_box.tag_config("error", foreground="#ff96a3")
        self.log_box.tag_config("debug", foreground="#6fd3ff")

        runbook_tab = ttk.Frame(
            self.diagnostics_notebook,
            padding=10,
            style="UiB.TFrame",
        )
        self.diagnostics_notebook.add(runbook_tab, text="Памятка")
        self.diagnostics_notebook.bind("<<NotebookTabChanged>>", self._on_diagnostics_tab_changed)
        self.runbook_intro_label = ttk.Label(
            runbook_tab,
            text=(
                "Краткая памятка загружается из docs/pre_hardware и служит опорой "
                "перед реальным железом."
            ),
            style="UiO.TLabel",
            justify="left",
            anchor="w",
        )
        self.runbook_intro_label.pack(fill="x", anchor="w", pady=(0, 8))
        self._bind_responsive_wrap(self.runbook_intro_label, runbook_tab, min_wrap=420)
        self.runbook_box = ScrolledText(
            runbook_tab,
            font=("Segoe UI", 10),
            wrap="word",
            relief="flat",
            borderwidth=0,
        )
        self.runbook_box.pack(fill="both", expand=True)
        self.runbook_box.configure(
            background=self.palette["surface"],
            foreground=self.palette["text"],
            insertbackground=self.palette["text"],
        )

        self.log_button = self._build_artifact_row(
            utility_card,
            2,
            "Лог",
            self.log_path_var,
            self.log_status_var,
            "Общий таймлайн этапов, статусы сканирования и короткие сводки ошибок.",
            self._open_log,
            button_text="Открыть",
        )
        self.report_button = self._build_artifact_row(
            utility_card,
            3,
            "Отчёт",
            self.report_path_var,
            self.report_status_var,
            "Итоговая версия IOS, boot variable, flash space и финальная проверка.",
            self._open_report,
            button_text="Открыть",
            enabled=False,
        )
        self.artifact_report_button = self.report_button
        self.transcript_button = self._build_artifact_row(
            utility_card,
            4,
            "Транскрипт",
            self.transcript_path_var,
            self.transcript_status_var,
            "Сырой READ/WRITE диалог с устройством, prompt и вывод команд.",
            self._open_transcript,
            button_text="Открыть",
        )
        self._build_artifact_row(
            utility_card,
            5,
            "Настройки",
            self.settings_path_var,
            self.settings_status_var,
            "Последний firmware name, выбранный порт и геометрия окна.",
            lambda: self._open_path(self.settings_path),
            button_text="Открыть",
        )
        self._build_artifact_row(
            utility_card,
            6,
            "Manifest",
            self.manifest_path_var,
            self.manifest_status_var,
            "Сводка сессии, длительности этапов, финальный state и operator message.",
            self._open_manifest,
            button_text="Открыть",
        )
        self.artifact_bundle_button = self._build_artifact_row(
            utility_card,
            7,
            "Bundle",
            self.bundle_path_var,
            self.bundle_status_var,
            "ZIP-пакет для баг-репорта: log, report, transcript, settings snapshot и manifest.",
            self._open_bundle,
            button_text="Открыть",
            enabled=False,
        )
        self._set_text_widget(self.runbook_box, self._load_runbook_text(), readonly=True)

    def _build_summary_card(
        self,
        parent: ttk.Frame,
        row: int,
        column: int,
        title: str,
        primary_var: tk.StringVar,
        secondary_var: tk.StringVar,
    ) -> None:
        card = ttk.Frame(parent, padding=(8, 6), style="UiAA.TFrame")
        card.grid(
            row=row,
            column=column,
            padx=(0 if column == 0 else 8, 0),
            pady=(0 if row == 0 else 8, 0),
            sticky="nsew",
        )
        ttk.Label(card, text=title, style="UiAB.TLabel").pack(anchor="w")
        ttk.Label(card, textvariable=primary_var, style="UiAC.TLabel").pack(anchor="w", pady=(2, 0))
        secondary_label = ttk.Label(
            card,
            textvariable=secondary_var,
            style="UiAD.TLabel",
            justify="left",
            anchor="w",
        )
        secondary_label.pack(fill="x", anchor="w", pady=(2, 0))
        self._bind_responsive_wrap(secondary_label, card, min_wrap=160)

    def _build_shell_fact_card(
        self,
        parent: ttk.Frame,
        row: int,
        column: int,
        title: str,
        value_var: tk.StringVar,
        *,
        min_wrap: int = 180,
    ) -> None:
        card = ttk.Frame(parent, padding=(8, 6), style="UiAA.TFrame")
        card.grid(
            row=row,
            column=column,
            padx=(0 if column == 0 else 8, 0),
            pady=(0 if row <= 1 else 8, 0),
            sticky="nsew",
        )
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text=title, style="UiAB.TLabel").grid(row=0, column=0, sticky="w")
        value_label = ttk.Label(
            card,
            textvariable=value_var,
            justify="left",
            anchor="w",
            style="UiAC.TLabel",
        )
        value_label.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self._bind_responsive_wrap(value_label, card, min_wrap=min_wrap)

    def _build_preflight_value(
        self,
        parent: Any,
        row: int,
        column: int,
        title: str,
        value_var: tk.StringVar,
        *,
        min_wrap: int = 220,
    ) -> None:
        ttk.Label(parent, text=title, style="UiO.TLabel").grid(
            row=row,
            column=column,
            sticky="nw",
            padx=(0 if column == 0 else 16, 8),
            pady=4,
        )
        value_cell = ttk.Frame(parent)
        value_cell.grid(row=row, column=column + 1, sticky="ew", pady=4)
        value_cell.columnconfigure(0, weight=1)
        value_label = ttk.Label(
            value_cell,
            textvariable=value_var,
            justify="left",
            anchor="w",
            style="UiN.TLabel",
        )
        value_label.grid(row=0, column=0, sticky="ew")
        self._bind_responsive_wrap(value_label, value_cell, min_wrap=min_wrap)

    def _build_artifact_row(
        self,
        parent: Any,
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
    ) -> ttk.Button:
        ttk.Label(parent, text=title, font=("Segoe UI", 10, "bold")).grid(
            row=row, column=0, sticky="nw", padx=(0, 10), pady=(0, 10)
        )
        entry = ttk.Entry(parent, textvariable=path_var)
        entry.grid(row=row, column=1, sticky="ew", pady=(0, 10))
        entry.configure(state="readonly")
        meta = ttk.Frame(parent)
        meta.grid(row=row, column=2, sticky="new", padx=(12, 10), pady=(0, 10))
        meta.columnconfigure(0, weight=1)
        ttk.Label(meta, textvariable=status_var, font=("Segoe UI", 9, "bold")).pack(anchor="w")
        description_label = ttk.Label(
            meta,
            text=description,
            style="UiO.TLabel",
            justify="left",
            anchor="w",
        )
        description_label.pack(fill="x", anchor="w", pady=(2, 0))
        self._bind_responsive_wrap(description_label, meta, min_wrap=200)
        button = ttk.Button(
            parent,
            text=button_text,
            style="UiY.TButton",
            command=command,
            state="normal" if enabled else "disabled",
        )
        button.grid(row=row, column=3, sticky="e", pady=(0, 10))
        if button_attr:
            setattr(self, button_attr, button)
        return button

    def _bind_responsive_wrap(
        self,
        label: Any,
        container: Any,
        *,
        min_wrap: int,
        horizontal_padding: int = 28,
    ) -> None:
        def update_wrap(_event: object | None = None) -> None:
            try:
                width = int(container.winfo_width())
            except Exception:
                return
            if width <= horizontal_padding:
                return
            label.configure(wraplength=max(min_wrap, width - horizontal_padding))

        try:
            container.bind("<Configure>", update_wrap, add="+")
        except Exception:
            update_wrap()
            return
        update_wrap()

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

    def _build_tabs_payload(self, notebook: object | None) -> dict[str, dict[str, object]]:
        bounds = self._widget_bounds(notebook)
        if notebook is None or bounds is None:
            return {}
        notebook_obj = cast(Any, notebook)
        try:
            tab_count = int(notebook_obj.index("end"))
            selected_tab = str(notebook_obj.tab(notebook_obj.select(), "text"))
        except Exception:
            return {}
        probe_y = max(1, min(10, bounds["height"] - 1))
        runs: dict[int, list[int]] = {}
        last_index: int | None = None
        run_start = 0
        for x_pos in range(max(1, bounds["width"])):
            try:
                index = int(notebook_obj.index(f"@{x_pos},{probe_y}"))
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
                tab_text = str(notebook_obj.tab(index, "text"))
            except tk.TclError:
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

    def _build_notebook_tabs_payload(self) -> dict[str, dict[str, object]]:
        return self._build_tabs_payload(getattr(self, "diagnostics_notebook", None))

    def _build_workspace_tabs_payload(self) -> dict[str, dict[str, object]]:
        return self._build_tabs_payload(getattr(self, "workspace_notebook", None))

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

    def _refresh_hardware_day_summary(self) -> None:
        latest_preflight = load_operator_preflight_summary(
            runtime_root=self.config.runtime_root,
            project_root=self.config.project_root,
        )
        snapshot = build_connection_snapshot()
        described = describe_connection_snapshot(snapshot)
        self._apply_hardware_day_summary(latest_preflight, snapshot, described)

    def _sync_runtime_artifact_paths(self) -> None:
        update_manifest_artifacts(
            self.manifest_path,
            event_timeline_path=self.event_timeline_path,
            dashboard_snapshot_path=self.dashboard_snapshot_path,
        )

    def _event_paths_for_event(self, event: AppEvent) -> dict[str, str]:
        path_keys = (
            "session_dir",
            "log_path",
            "report_path",
            "transcript_path",
            "settings_path",
            "settings_snapshot_path",
            "manifest_path",
            "bundle_path",
            "event_timeline_path",
            "dashboard_snapshot_path",
        )
        if event.kind == "session_paths":
            return {
                key: str(event.payload.get(key, ""))
                for key in path_keys
                if str(event.payload.get(key, "")).strip()
            }
        if event.kind == "report_ready":
            return {"report_path": str(self.report_path)}
        return {}

    def _write_event_timeline(self) -> None:
        self.event_timeline_path.parent.mkdir(parents=True, exist_ok=True)
        self.event_timeline_path.write_text(
            json.dumps(self._event_timeline, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.session.event_timeline_path = self.event_timeline_path
        self._sync_runtime_artifact_paths()

    def _record_event_timeline_entry(self, event: AppEvent) -> None:
        selected_target = self.selected_target_var.get().strip()
        if selected_target == "Не выбрана":
            selected_target = ""
        entry = {
            "timestamp": timestamp(),
            "kind": event.kind,
            "state": self.current_state_name,
            "current_stage": self.current_stage_var.get().strip(),
            "selected_target_id": selected_target,
            "operator_message_code": self.operator_message_code,
            "progress_percent": self._progress_percent_value,
            "paths": self._event_paths_for_event(event),
        }
        self._event_timeline.append(entry)
        self._write_event_timeline()

    def _capture_terminal_snapshot(self, state_name: str) -> None:
        if state_name not in {"FAILED", "STOPPED"}:
            return
        if self._terminal_snapshot_state is not None or ImageGrab is None:
            return
        bounds = self._widget_bounds(self.window)
        if bounds is None:
            return
        try:
            update_idletasks = getattr(self.window, "update_idletasks", None)
            if callable(update_idletasks):
                update_idletasks()
            snapshot_path = self.session_dir / f"dashboard_snapshot_{state_name.lower()}.png"
            image = ImageGrab.grab(
                bbox=(
                    bounds["left"],
                    bounds["top"],
                    bounds["right"],
                    bounds["bottom"],
                )
            )
            image.save(snapshot_path)
        except Exception:
            return
        self.dashboard_snapshot_path = snapshot_path
        self.session.dashboard_snapshot_path = snapshot_path
        self._terminal_snapshot_state = state_name
        self._sync_runtime_artifact_paths()
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
            "error": "Ошибка",
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

    def _compact_target_status(self, status_message: str, connection_state: str) -> str:
        text = str(status_message or "").strip()
        lowered = text.lower()
        if connection_state == "ready":
            return "Готово"
        if "timeout" in lowered or "таймаут" in lowered:
            return "Таймаут"
        if "port_busy" in lowered or "порт занят" in lowered:
            return "Порт занят"
        if "rommon" in lowered:
            return "ROMMON"
        if "login" in lowered or "нужен вход" in lowered:
            return "Нужен вход"
        if "config" in lowered:
            return "Config dialog"
        if "return" in lowered or "enter" in lowered:
            return "Нажмите Enter"
        if text:
            compact = text.split(":", 1)[0].strip()
            return compact[:28] if compact else "Статус"
        return "Статус"

    def _compact_summary_status(self, status_message: str) -> str:
        text = str(status_message or "").strip()
        lowered = text.lower()
        if not text:
            return "Ожидание сканирования"
        if "timeout" in lowered or "таймаут" in lowered:
            return "Порт не ответил вовремя"
        if "could not open port" in lowered or "open port" in lowered:
            return "Ошибка открытия COM-порта"
        if "write timeout" in lowered:
            return "Таймаут записи"
        if "порт занят" in lowered or "port_busy" in lowered:
            return "Порт занят другим процессом"
        if "готов" in lowered or "switch#" in lowered:
            return "Устройство отвечает"
        compact = text.split(":", 1)[-1].strip() if ":" in text else text
        return compact[:44] if compact else "Статус обновлён"

    def _scan_placeholder_value(self, value: object) -> str:
        text = str(value or "").strip()
        if not text or text.lower() in {
            "unknown",
            "none",
            "n/a",
            "не определено",
            "не определена",
            "неизвестно",
            "—",
        }:
            return "Определится после scan"
        return text

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
        if hasattr(self, "operator_badge"):
            badge_map = {
                "info": self.palette["accent"],
                "warning": self.palette["warn"],
                "danger": self.palette["danger"],
                "success": self.palette["ok"],
            }
            fg_map = {
                "info": self.palette["text"],
                "warning": self.palette["text"],
                "danger": self.palette["surface"],
                "success": self.palette["surface"],
            }
            self.operator_badge.configure(
                background=badge_map.get(style, self.palette["surface_muted"]),
                foreground=fg_map.get(style, self.palette["primary"]),
            )

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
            self.state_card.configure(style=self._state_card_style(state_name))
        if hasattr(self, "state_badge"):
            badge_map = {
                "secondary": (self.palette["surface_muted"], self.palette["primary"]),
                "info": (self.palette["accent"], self.palette["text"]),
                "primary": (self.palette["primary"], self.palette["surface"]),
                "warning": (self.palette["warn"], self.palette["text"]),
                "success": (self.palette["ok"], self.palette["surface"]),
                "danger": (self.palette["danger"], self.palette["surface"]),
            }
            background, foreground = badge_map.get(
                style, (self.palette["surface_muted"], self.palette["primary"])
            )
            self.state_badge.configure(background=background, foreground=foreground)
        if hasattr(self, "status_strip_card"):
            self.status_strip_card.configure(style=self._state_card_style(state_name))

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
        self._apply_demo_scenario(scenario_name)

    def _on_demo_scenario_button(self, scenario_name: str) -> None:
        if not self.demo_mode or not isinstance(self.controller, DemoReplayController):
            return
        self._apply_demo_scenario(scenario_name)

    def _apply_demo_scenario(self, scenario_name: str) -> None:
        scenario_display = self.demo_name_to_display.get(scenario_name, "")
        if not scenario_display:
            return
        controller = self.controller
        if not isinstance(controller, DemoReplayController):
            return
        if controller.set_scenario(scenario_name):
            self.selected_demo_scenario_name = scenario_name
            self.demo_scenario_var.set(scenario_display)
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
        try:
            # Intentional local file open in desktop UI.
            os.startfile(str(path))  # nosec
        except Exception:
            messagebox.showinfo("Путь к артефакту", str(path))

    def _drain_events(self) -> None:
        self._drain_hardware_day_refresh_results()
        while True:
            try:
                event = self.event_queue.get_nowait()
            except Empty:
                break
            self._handle_event(event)
            self._record_event_timeline_entry(event)
        self.window.after(100, self._drain_events)

    def _cancel_window_after(self, attr_name: str) -> None:
        handle = getattr(self, attr_name, None)
        if handle is None:
            return
        after_cancel = getattr(self.window, "after_cancel", None)
        if callable(after_cancel):
            try:
                after_cancel(handle)
            except Exception:
                handle = None
        setattr(self, attr_name, None)

    def _schedule_ui_smoke_close(self) -> None:
        if not self.ui_smoke_mode:
            return
        self._cancel_window_after("_ui_smoke_after_id")
        self._ui_smoke_after_id = self.window.after(
            self.ui_smoke_close_ms,
            self._on_ui_smoke_timeout,
        )

    def _on_ui_smoke_timeout(self) -> None:
        self._ui_smoke_after_id = None
        self._on_close()

    def _schedule_hardware_day_periodic_refresh(self) -> None:
        if self._hardware_day_refresh_closed:
            return
        self._cancel_window_after("_hardware_day_periodic_after_id")
        self._hardware_day_periodic_after_id = self.window.after(
            15000, self._on_hardware_day_periodic_refresh
        )

    def _on_hardware_day_periodic_refresh(self) -> None:
        self._hardware_day_periodic_after_id = None
        self._schedule_hardware_day_refresh(delay_ms=0)
        self._schedule_hardware_day_periodic_refresh()

    def _schedule_hardware_day_refresh(self, delay_ms: int = 500) -> None:
        if self._hardware_day_refresh_closed:
            return
        self._hardware_day_refresh_request_token += 1
        request_token = self._hardware_day_refresh_request_token
        self._cancel_window_after("_hardware_day_refresh_after_id")

        def _start(request_token: int = request_token) -> None:
            self._hardware_day_refresh_after_id = None
            self._start_hardware_day_refresh(request_token)

        self._hardware_day_refresh_after_id = self.window.after(delay_ms, _start)

    def _start_hardware_day_refresh(self, request_token: int) -> None:
        if self._hardware_day_refresh_closed:
            return
        if request_token < self._hardware_day_refresh_request_token:
            return
        if self._hardware_day_refresh_inflight:
            self._hardware_day_refresh_pending = True
            return
        self._hardware_day_refresh_inflight = True
        self._hardware_day_refresh_pending = False
        worker = threading.Thread(
            target=self._hardware_day_refresh_worker,
            args=(request_token,),
            daemon=True,
        )
        worker.start()

    def _hardware_day_refresh_worker(self, request_token: int) -> None:
        result: dict[str, Any] = {"request_token": request_token}
        try:
            latest_preflight = load_operator_preflight_summary(
                runtime_root=self.config.runtime_root,
                project_root=self.config.project_root,
            )
            snapshot = build_connection_snapshot()
            described = describe_connection_snapshot(snapshot)
            result.update(
                {
                    "latest_preflight": latest_preflight,
                    "snapshot": snapshot,
                    "described": described,
                }
            )
        except Exception as exc:
            result["error"] = str(exc)
        self._hardware_day_refresh_queue.put(result)

    def _apply_hardware_day_summary(
        self,
        latest_preflight: dict[str, Any] | None,
        snapshot: dict[str, Any],
        described: dict[str, str],
    ) -> None:
        self.hardware_gate_var.set(format_latest_preflight_status(latest_preflight))
        self.hardware_console_var.set(described["console"])
        self.hardware_ethernet_var.set(described["ethernet"])
        self.hardware_ssh_var.set(described["ssh"])
        self.hardware_live_run_var.set(described["live_run_path"])
        self.hardware_return_var.set(described["return_path"])
        if latest_preflight and str(latest_preflight.get("status", "")) == "READY":
            if bool(snapshot.get("console", {}).get("ready", False)):
                self.hardware_day_status_var.set(
                    "Serial-first live run можно начинать: выбери один "
                    "console path и держи второй резервным."
                )
            else:
                self.hardware_day_status_var.set(
                    "Код готов, но console path не найден. Подключите "
                    "основной console before live run."
                )
        else:
            self.hardware_day_status_var.set(
                "Сначала нужен зелёный local preflight, потом уже живой serial-first run."
            )

    def _drain_hardware_day_refresh_results(self) -> None:
        while True:
            try:
                result = self._hardware_day_refresh_queue.get_nowait()
            except Empty:
                break
            request_token = int(result.get("request_token", 0))
            self._hardware_day_refresh_inflight = False
            if self._hardware_day_refresh_closed:
                continue
            if request_token < self._hardware_day_refresh_request_token:
                self._hardware_day_refresh_pending = False
                self._start_hardware_day_refresh(self._hardware_day_refresh_request_token)
                continue
            error = str(result.get("error", "") or "")
            if error:
                self.hardware_day_status_var.set(f"Snapshot недоступен: {error}")
            else:
                latest_preflight = result.get("latest_preflight")
                snapshot = result.get("snapshot")
                described = result.get("described")
                if isinstance(snapshot, dict) and isinstance(described, dict):
                    self._apply_hardware_day_summary(
                        latest_preflight
                        if isinstance(latest_preflight, dict) or latest_preflight is None
                        else None,
                        snapshot,
                        described,
                    )
                    self._hardware_day_refresh_applied_token = request_token
            if (
                self._hardware_day_refresh_pending
                or request_token < self._hardware_day_refresh_request_token
            ):
                self._hardware_day_refresh_pending = False
                self._start_hardware_day_refresh(self._hardware_day_refresh_request_token)

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
            self.event_timeline_path = Path(
                str(event.payload.get("event_timeline_path", self.event_timeline_path))
            )
            raw_snapshot_path = str(
                event.payload.get(
                    "dashboard_snapshot_path",
                    self.dashboard_snapshot_path or "",
                )
            ).strip()
            self.dashboard_snapshot_path = Path(raw_snapshot_path) if raw_snapshot_path else None
            self.session.manifest_path = self.manifest_path
            self.session.bundle_path = self.bundle_path
            self.session.event_timeline_path = self.event_timeline_path
            self.session.dashboard_snapshot_path = self.dashboard_snapshot_path
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
            self.current_state_name = state_name
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
            self._capture_terminal_snapshot(state_name)
        elif event.kind == "actions_changed":
            self._demo_action_state = {
                "scan_enabled": bool(event.payload.get("scan_enabled", False)),
                "stage1_enabled": bool(event.payload.get("stage1_enabled", False)),
                "stage2_enabled": bool(event.payload.get("stage2_enabled", False)),
                "stage3_enabled": bool(event.payload.get("stage3_enabled", False)),
                "stop_enabled": bool(event.payload.get("stop_enabled", False)),
            }
            self.demo_busy = bool(self._demo_action_state["stop_enabled"])
            if self.demo_busy:
                self.last_demo_idle_marker = ""
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
        elif event.kind == "demo_idle_ready":
            marker = str(event.payload.get("marker", "")).strip()
            if marker:
                self.last_demo_idle_marker = marker
            self.demo_busy = bool(event.payload.get("busy", False))
        elif event.kind == "device_snapshot":
            snapshot = event.payload["snapshot"]
            target_id = getattr(snapshot, "port", "") or ""
            self.port_var.set(target_id or "—")
            self._update_selected_target(target_id)
            status_text = str(getattr(snapshot, "status_text", "Не определено") or "Не определено")
            self.device_status_var.set(status_text)
            self.device_status_summary_var.set(self._compact_summary_status(status_text))
            self.model_var.set(self._scan_placeholder_value(getattr(snapshot, "model", "")))
            self.current_fw_var.set(
                self._scan_placeholder_value(getattr(snapshot, "firmware", ""))
            )
            self.flash_var.set(self._scan_placeholder_value(getattr(snapshot, "flash", "")))
            self.uptime_var.set(self._scan_placeholder_value(getattr(snapshot, "uptime", "")))
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
            self.operator_message_code = str(getattr(message, "code", "") or "")
            self.operator_title_var.set(getattr(message, "title", ""))
            detail = str(getattr(message, "detail", "") or "")
            self.operator_detail_var.set(detail)
            if detail:
                self.device_status_summary_var.set(self._compact_summary_status(detail))
            self.operator_next_step_var.set(getattr(message, "next_step", ""))
            self._apply_operator_style(severity)
        elif event.kind == "progress":
            percent = int(event.payload.get("percent", 0))
            self._progress_percent_value = percent
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
            selected_result = next(
                (result for result in results if result.target.id == selected_target_id),
                results[0] if results else None,
            )
            if selected_result is not None:
                self.device_status_summary_var.set(
                    self._compact_summary_status(selected_result.status_message)
                )
            if hasattr(self, "targets_tree"):
                self._render_scan_results(results, selected_target_id)
            self._schedule_hardware_day_refresh()
        elif event.kind == "selected_target_changed":
            target_id = str(event.payload.get("target_id", ""))
            manual_override = bool(event.payload.get("manual_override", False))
            self._update_selected_target(target_id)
            self.manual_override_var.set(self._friendly_manual_override(manual_override))
            if target_id and hasattr(self, "targets_tree"):
                self._set_tree_selection(target_id)
                self._persist_settings(preferred_target_id=target_id)
            self._schedule_hardware_day_refresh()
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
                self._compact_target_status(result.status_message, result.connection_state),
                self._friendly_connection_state(result.connection_state),
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
        self._hardware_day_refresh_closed = True
        self._cancel_window_after("_ui_smoke_after_id")
        self._cancel_window_after("_hardware_day_refresh_after_id")
        self._cancel_window_after("_hardware_day_periodic_after_id")
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
            return
        self.demo_scenario_var.set(self.demo_name_to_display.get(scenario.name, scenario.name))
        self.demo_description_var.set(
            scenario.description or "Сценарий готов для ручной проверки без оборудования."
        )
        self.demo_actions_var.set(self._friendly_demo_actions(scenario.supported_actions))
        for scenario_name, button in getattr(self, "demo_scenario_buttons", {}).items():
            button.configure(
                bootstyle="primary" if scenario_name == scenario.name else "secondary"
            )


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
