from __future__ import annotations

import json
import shutil
import sys
import types
import unittest
import uuid
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

if "ttkbootstrap" not in sys.modules:
    ttkbootstrap_stub = types.SimpleNamespace(
        Window=object,
        Frame=object,
        Labelframe=object,
        Label=object,
        Button=object,
        Entry=object,
        Combobox=object,
        Progressbar=object,
        Floodgauge=object,
        Notebook=object,
        Panedwindow=object,
        Treeview=object,
        Scrollbar=object,
        Separator=object,
    )
    sys.modules["ttkbootstrap"] = ttkbootstrap_stub

from ciscoautoflash.config import AppSettings
from ciscoautoflash.core.events import AppEvent
from ciscoautoflash.core.models import ConnectionTarget, DeviceSnapshot, ScanResult
from ciscoautoflash.replay.adapter import DemoReplayController
from ciscoautoflash.ui.app import (
    _BRAND_COLORS,
    CiscoAutoFlashDesktop,
    _parse_geometry_size,
    _resolve_window_layout_contract,
)


class DummyVar:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def set(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value


class DummyButton:
    def __init__(self) -> None:
        self.state = "normal"

    def configure(self, **kwargs) -> None:
        if "state" in kwargs:
            self.state = kwargs["state"]


class DummyGeometryWidget(DummyButton):
    def __init__(
        self,
        *,
        x: int = 0,
        y: int = 0,
        width: int = 120,
        height: int = 24,
        state: str = "normal",
        text: str = "",
    ) -> None:
        super().__init__()
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.state = state
        self.text = text

    def winfo_rootx(self) -> int:
        return self.x

    def winfo_rooty(self) -> int:
        return self.y

    def winfo_width(self) -> int:
        return self.width

    def winfo_height(self) -> int:
        return self.height

    def cget(self, option: str) -> str:
        if option == "state":
            return self.state
        if option == "text":
            return self.text
        raise KeyError(option)

    def get(self) -> str:
        return self.text


class DummyResponsiveContainer:
    def __init__(self, width: int = 480) -> None:
        self.width = width
        self.bindings: dict[str, object] = {}

    def winfo_width(self) -> int:
        return self.width

    def bind(self, event: str, callback, add: str | None = None) -> None:
        self.bindings[event] = callback


class DummyResponsiveLabel:
    def __init__(self) -> None:
        self.configured: dict[str, object] = {}

    def configure(self, **kwargs) -> None:
        self.configured.update(kwargs)


class DummyProgress:
    def __init__(self) -> None:
        self.value = 0

    def configure(self, **kwargs) -> None:
        if "value" in kwargs:
            self.value = kwargs["value"]


class DummyLogBox:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def insert(self, _index: str, value: str, _tag: str) -> None:
        self.lines.append(value)

    def see(self, _index: str) -> None:
        return None


class DummyTree:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, object]] = {}
        self.selection_items: tuple[str, ...] = ()
        self.focused: str = ""
        self.seen: list[str] = []

    def get_children(self, _item: str = "") -> list[str]:
        return list(self.nodes)

    def delete(self, item_id: str) -> None:
        self.nodes.pop(item_id, None)

    def exists(self, item_id: str) -> bool:
        return item_id in self.nodes

    def item(self, item_id: str, **kwargs) -> None:
        record = self.nodes.setdefault(item_id, {})
        record.update(kwargs)

    def insert(self, _parent: str, _index: str, iid: str, text: str, values) -> None:
        self.nodes[iid] = {"text": text, "values": values}

    def selection(self) -> tuple[str, ...]:
        return self.selection_items

    def selection_set(self, item_id: str) -> None:
        self.selection_items = (item_id,)

    def focus(self, item_id: str) -> None:
        self.focused = item_id

    def see(self, item_id: str) -> None:
        self.seen.append(item_id)


class DummyWindow:
    def __init__(self) -> None:
        self.after_calls: list[tuple[int, object]] = []
        self.cancelled_after_ids: list[object] = []
        self.destroyed = False
        self.geometry_text = "1320x900"
        self.x = 0
        self.y = 0
        self.width = 1320
        self.height = 900
        self._after_id = 0

    def after(self, delay: int, callback):
        self._after_id += 1
        handle = f"after-{self._after_id}"
        self.after_calls.append((delay, callback, handle))
        return handle

    def after_cancel(self, handle) -> None:
        self.cancelled_after_ids.append(handle)

    def destroy(self) -> None:
        self.destroyed = True

    def geometry(self) -> str:
        return self.geometry_text

    def winfo_rootx(self) -> int:
        return self.x

    def winfo_rooty(self) -> int:
        return self.y

    def winfo_width(self) -> int:
        return self.width

    def winfo_height(self) -> int:
        return self.height


class DummyNotebook:
    def __init__(
        self,
        labels: dict[str, str] | None = None,
        *,
        current: str | None = None,
        tab_boxes: dict[str, tuple[int, int, int, int]] | None = None,
    ) -> None:
        self.labels = labels or {
            "log": "Журнал",
            "runbook": "Памятка",
        }
        self.current = current or next(iter(self.labels))
        self.x = 640
        self.y = 480
        self.width = 480
        self.height = 240
        if tab_boxes is None:
            keys = list(self.labels)
            tab_boxes = {
                key: (index * 120, 0, 120, 24) for index, key in enumerate(keys)
            }
        self.tab_boxes = tab_boxes

    def select(self) -> str:
        return self.current

    def tab(self, tab_id: str | int, option: str) -> str:
        if option != "text":
            raise KeyError(option)
        if isinstance(tab_id, int):
            tab_id = list(self.labels)[tab_id]
        return self.labels[tab_id]

    def tabs(self) -> tuple[str, ...]:
        return tuple(self.labels)

    def bbox(self, tab_id: str):
        return self.tab_boxes[tab_id]

    def index(self, spec: str) -> int:
        if spec == "end":
            return len(self.labels)
        if spec.startswith("@"):
            x_text, _y_text = spec[1:].split(",", 1)
            x_pos = int(x_text)
            for idx, tab_id in enumerate(self.labels):
                start_x, _start_y, width, _height = self.tab_boxes[tab_id]
                if start_x <= x_pos < start_x + width:
                    return idx
            raise ValueError(spec)
        return list(self.labels).index(spec)

    def winfo_rootx(self) -> int:
        return self.x

    def winfo_rooty(self) -> int:
        return self.y

    def winfo_width(self) -> int:
        return self.width

    def winfo_height(self) -> int:
        return self.height


class CiscoAutoFlashDesktopSmokeTests(unittest.TestCase):
    def make_app_shell(self) -> CiscoAutoFlashDesktop:
        app = object.__new__(CiscoAutoFlashDesktop)
        runtime_root = Path("C:/PROJECT/tests/_runtime") / uuid.uuid4().hex
        runtime_root.mkdir(parents=True, exist_ok=True)
        self.addCleanup(shutil.rmtree, runtime_root, ignore_errors=True)
        app.window = DummyWindow()
        app.diagnostics_notebook = DummyNotebook()
        app.event_queue = Queue()
        app.scan_button = DummyGeometryWidget(x=900, y=200, text="Сканировать")
        app.stage1_button = DummyGeometryWidget(x=1020, y=200, text="Этап 1: Сброс")
        app.stage2_button = DummyGeometryWidget(x=1140, y=200, text="Этап 2: Установка")
        app.stage3_button = DummyGeometryWidget(x=1260, y=200, text="Этап 3: Проверка")
        app.stop_button = DummyGeometryWidget(x=1380, y=200, width=70, text="Стоп")
        app.log_button = DummyGeometryWidget(x=40, y=320, width=180, text="Открыть лог")
        app.report_button = DummyGeometryWidget(
            x=230, y=320, width=180, state="disabled", text="Открыть отчёт"
        )
        app.transcript_button = DummyGeometryWidget(
            x=420, y=320, width=180, text="Открыть транскрипт"
        )
        app.logs_dir_button = DummyGeometryWidget(
            x=610, y=320, width=180, text="Открыть папку логов"
        )
        app.session_folder_button = DummyGeometryWidget(
            x=800, y=320, width=220, text="Открыть папку сессии"
        )
        app.bundle_export_button = DummyGeometryWidget(
            x=1030, y=320, width=220, text="Экспортировать bundle"
        )
        app.artifact_bundle_button = app.bundle_export_button
        app.demo_selector = DummyGeometryWidget(
            x=760,
            y=160,
            width=260,
            height=28,
            state="readonly",
            text="Сканирование: Switch# готов",
        )
        app.demo_scenario_buttons = {
            "scan_ready": DummyGeometryWidget(
                x=760, y=200, width=180, height=28, text="Сканирование: Switch# готов"
            ),
            "stage1_reboot_config_dialog": DummyGeometryWidget(
                x=950, y=200, width=220, height=28, text="Этап 1: reboot + config dialog"
            ),
            "stage2_install_success": DummyGeometryWidget(
                x=760, y=236, width=180, height=28, text="Этап 2: успешная установка"
            ),
            "stage2_install_timeout": DummyGeometryWidget(
                x=950, y=236, width=220, height=28, text="Этап 2: timeout установки"
            ),
            "stage3_verify": DummyGeometryWidget(
                x=760, y=272, width=180, height=28, text="Этап 3: verify"
            ),
        }
        app.progress = DummyProgress()
        app.log_box = DummyLogBox()
        app.targets_tree = DummyTree()
        app.state_var = DummyVar()
        app.state_badge_var = DummyVar()
        app.transport_mode_var = DummyVar("Serial/USB")
        app.demo_badge_var = DummyVar("")
        app.footer_var = DummyVar()
        app.port_var = DummyVar()
        app.device_status_var = DummyVar()
        app.device_status_summary_var = DummyVar()
        app.model_var = DummyVar()
        app.current_fw_var = DummyVar()
        app.flash_var = DummyVar()
        app.uptime_var = DummyVar()
        app.usb_var = DummyVar()
        app.connection_var = DummyVar()
        app.prompt_var = DummyVar()
        app.manual_override_var = DummyVar()
        app.profile_var = DummyVar("Cisco Catalyst 2960-X")
        app.operator_title_var = DummyVar()
        app.operator_detail_var = DummyVar()
        app.operator_next_step_var = DummyVar()
        app.operator_severity_var = DummyVar()
        app.progress_stage_var = DummyVar()
        app.progress_percent_var = DummyVar()
        app.progress_meta_var = DummyVar()
        app.session_id_var = DummyVar("test")
        app.session_started_var = DummyVar()
        app.session_duration_var = DummyVar()
        app.active_stage_duration_var = DummyVar()
        app.session_mode_var = DummyVar("Operator")
        app.current_stage_var = DummyVar()
        app.last_scan_time_var = DummyVar()
        app.selected_target_var = DummyVar()
        app.scan_status_var = DummyVar()
        app.log_path_var = DummyVar()
        app.report_path_var = DummyVar()
        app.transcript_path_var = DummyVar()
        app.settings_path_var = DummyVar()
        app.manifest_path_var = DummyVar()
        app.bundle_path_var = DummyVar()
        app.log_status_var = DummyVar()
        app.report_status_var = DummyVar()
        app.transcript_status_var = DummyVar()
        app.settings_status_var = DummyVar()
        app.manifest_status_var = DummyVar()
        app.bundle_status_var = DummyVar()
        app.hardware_gate_var = DummyVar()
        app.hardware_day_status_var = DummyVar()
        app.hardware_console_var = DummyVar()
        app.hardware_ethernet_var = DummyVar()
        app.hardware_ssh_var = DummyVar()
        app.hardware_live_run_var = DummyVar()
        app.hardware_return_var = DummyVar()
        app.firmware_input_var = DummyVar("c2960x-universalk9.tar")
        app.demo_scenario_var = DummyVar("")
        app.demo_description_var = DummyVar("")
        app.demo_actions_var = DummyVar("")
        logs_root = runtime_root / "logs"
        app.log_path = logs_root / "current.log"
        app.report_path = logs_root / "report.txt"
        app.transcript_path = logs_root / "transcript.txt"
        app.settings_path = logs_root / "settings" / "settings.json"
        app.manifest_path = logs_root / "sessions" / "current" / "session_manifest.json"
        app.bundle_path = logs_root / "sessions" / "current" / "session_bundle.zip"
        app.event_timeline_path = logs_root / "sessions" / "current" / "event_timeline.json"
        app.dashboard_snapshot_path = None
        app.session_started_at_value = 0.0
        app.active_stage_started_at_value = None
        sessions_dir = logs_root / "sessions"
        session_dir = sessions_dir / "current"
        for directory in (sessions_dir, session_dir):
            directory.mkdir(parents=True, exist_ok=True)
        app.session = SimpleNamespace(
            logs_dir=logs_root,
            sessions_dir=sessions_dir,
            session_dir=session_dir,
            session_id="test",
            started_at=0.0,
            manifest_path=app.manifest_path,
            bundle_path=app.bundle_path,
            event_timeline_path=app.event_timeline_path,
            dashboard_snapshot_path=app.dashboard_snapshot_path,
            settings_path=app.settings_path,
            settings_snapshot_path=app.settings_path,
            log_path=app.log_path,
            report_path=app.report_path,
            transcript_path=app.transcript_path,
        )
        app.session_dir = session_dir
        app.settings = AppSettings(preferred_target_id="")
        app.scan_results = {}
        app.demo_mode = False
        app.last_demo_idle_marker = ""
        app.demo_busy = False
        app._event_timeline = []
        app.operator_message_code = ""
        app.current_state_name = "IDLE"
        app._progress_percent_value = 0
        app._terminal_snapshot_state = None
        app._demo_action_state = {
            "scan_enabled": False,
            "stage1_enabled": False,
            "stage2_enabled": False,
            "stage3_enabled": False,
            "stop_enabled": False,
        }
        app._suppress_target_selection_event = False
        app.selected_demo_scenario_name = ""
        app.demo_display_to_name = {}
        app.demo_name_to_display = {}
        app.controller = Mock()
        app.config = SimpleNamespace(
            project_root=Path("C:/PROJECT"),
            runtime_root=runtime_root,
        )
        app._persist_settings = Mock()
        app._hardware_day_refresh_queue = Queue()
        app._hardware_day_refresh_request_token = 0
        app._hardware_day_refresh_applied_token = 0
        app._hardware_day_refresh_inflight = False
        app._hardware_day_refresh_pending = False
        app._hardware_day_refresh_after_id = None
        app._hardware_day_periodic_after_id = None
        app._hardware_day_refresh_closed = False
        return app

    def test_bind_responsive_wrap_sets_initial_wraplength_and_registers_configure(self) -> None:
        app = self.make_app_shell()
        container = DummyResponsiveContainer(width=520)
        label = DummyResponsiveLabel()

        app._bind_responsive_wrap(label, container, min_wrap=220, horizontal_padding=40)

        self.assertEqual(label.configured["wraplength"], 480)
        self.assertIn("<Configure>", container.bindings)

    def test_bind_responsive_wrap_respects_minimum_wraplength(self) -> None:
        app = self.make_app_shell()
        container = DummyResponsiveContainer(width=120)
        label = DummyResponsiveLabel()

        app._bind_responsive_wrap(label, container, min_wrap=220, horizontal_padding=40)

        self.assertEqual(label.configured["wraplength"], 220)

    def test_parse_geometry_size_reads_dimensions_from_geometry_string(self) -> None:
        self.assertEqual(_parse_geometry_size("1600x960+12+34"), (1600, 960))
        self.assertEqual(_parse_geometry_size("1920x1080-8+0"), (1920, 1080))
        self.assertIsNone(_parse_geometry_size("zoomed"))

    def test_resolve_window_layout_contract_clamps_saved_geometry_to_viewport(self) -> None:
        geometry, min_size, max_size = _resolve_window_layout_contract(
            "2200x1400+0+0",
            screen_width=2560,
            screen_height=1440,
        )

        self.assertEqual(geometry, "1920x1080")
        self.assertEqual(min_size, (1440, 860))
        self.assertEqual(max_size, (1920, 1080))

    def test_resolve_window_layout_contract_uses_default_when_saved_geometry_missing(self) -> None:
        geometry, min_size, max_size = _resolve_window_layout_contract(
            None,
            screen_width=1920,
            screen_height=1080,
        )

        self.assertEqual(geometry, "1600x960")
        self.assertEqual(min_size, (1440, 860))
        self.assertEqual(max_size, (1920, 1080))

    def test_resolve_window_layout_contract_downshifts_for_smaller_screen(self) -> None:
        geometry, min_size, max_size = _resolve_window_layout_contract(
            "1280x720",
            screen_width=1366,
            screen_height=768,
        )

        self.assertEqual(geometry, "1366x768")
        self.assertEqual(min_size, (1366, 768))
        self.assertEqual(max_size, (1366, 768))

    def test_brand_palette_keeps_light_shell_and_dark_log_contrast(self) -> None:
        self.assertEqual(_BRAND_COLORS["primary"], "#0b5cab")
        self.assertEqual(_BRAND_COLORS["log_bg"], "#10253a")
        self.assertNotEqual(_BRAND_COLORS["canvas"], _BRAND_COLORS["log_bg"])
        self.assertNotEqual(_BRAND_COLORS["surface"], _BRAND_COLORS["primary"])

    def test_handle_event_updates_device_snapshot_vars(self) -> None:
        app = self.make_app_shell()
        snapshot = DeviceSnapshot(
            port="COM7",
            status_text="Коммутатор готов",
            connection_state="ready",
            prompt_type="priv",
            model="WS-C2960X-48FPS-L",
            firmware="15.2(7)E13",
            flash="123 MB",
            uptime="2 weeks",
            usb_state="ready",
            recommended_next_action="Запустите этап 1 или этап 3.",
            is_manual_override=True,
        )

        app._handle_event(AppEvent("device_snapshot", {"snapshot": snapshot}))

        self.assertEqual(app.port_var.get(), "COM7")
        self.assertEqual(app.selected_target_var.get(), "COM7")
        self.assertEqual(app.device_status_var.get(), "Коммутатор готов")
        self.assertEqual(app.model_var.get(), "WS-C2960X-48FPS-L")
        self.assertEqual(app.current_fw_var.get(), "15.2(7)E13")
        self.assertEqual(app.flash_var.get(), "123 MB")
        self.assertEqual(app.uptime_var.get(), "2 weeks")
        self.assertEqual(app.usb_var.get(), "USB обнаружен")
        self.assertEqual(app.connection_var.get(), "Готово")
        self.assertEqual(app.prompt_var.get(), "Switch#")
        self.assertEqual(app.manual_override_var.get(), "Выбор цели: вручную")
        self.assertEqual(app.operator_next_step_var.get(), "Запустите этап 1 или этап 3.")

    def test_handle_event_normalizes_unknown_snapshot_values_to_scan_placeholder(self) -> None:
        app = self.make_app_shell()
        snapshot = DeviceSnapshot(
            port="COM7",
            status_text="Ответ неполный",
            connection_state="unknown",
            prompt_type="",
            model="Не определена",
            firmware="",
            flash="unknown",
            uptime="—",
            usb_state="unknown",
            recommended_next_action="Повторите scan.",
            is_manual_override=False,
        )

        app._handle_event(AppEvent("device_snapshot", {"snapshot": snapshot}))

        self.assertEqual(app.model_var.get(), "Определится после scan")
        self.assertEqual(app.current_fw_var.get(), "Определится после scan")
        self.assertEqual(app.flash_var.get(), "Определится после scan")
        self.assertEqual(app.uptime_var.get(), "Определится после scan")

    def test_handle_event_updates_progress_and_report_button(self) -> None:
        app = self.make_app_shell()

        app._handle_event(AppEvent("progress", {"percent": 60, "stage_name": "Installing"}))
        app._handle_event(AppEvent("report_ready", {"report_path": "C:/reports/final.txt"}))

        self.assertEqual(app.progress.value, 60)
        self.assertEqual(app.progress_stage_var.get(), "Установка образа")
        self.assertEqual(app.progress_percent_var.get(), "60%")
        self.assertEqual(
            app.progress_meta_var.get(),
            "Прогресс установки обновляется по маркерам archive download-sw.",
        )
        self.assertEqual(app.report_button.state, "normal")
        self.assertEqual(app.report_path, Path("C:/reports/final.txt"))

    def test_handle_event_updates_button_states(self) -> None:
        app = self.make_app_shell()

        app._handle_event(
            AppEvent(
                "actions_changed",
                {
                    "scan_enabled": False,
                    "stage1_enabled": True,
                    "stage2_enabled": False,
                    "stage3_enabled": True,
                    "stop_enabled": True,
                },
            )
        )

        self.assertEqual(app.scan_button.state, "disabled")
        self.assertEqual(app.stage1_button.state, "normal")
        self.assertEqual(app.stage2_button.state, "disabled")
        self.assertEqual(app.stage3_button.state, "normal")
        self.assertEqual(app.stop_button.state, "normal")
        self.assertTrue(app.demo_busy)
        self.assertEqual(
            app._demo_action_state,
            {
                "scan_enabled": False,
                "stage1_enabled": True,
                "stage2_enabled": False,
                "stage3_enabled": True,
                "stop_enabled": True,
            },
        )

    def test_handle_event_demo_idle_ready_tracks_marker_and_busy_state(self) -> None:
        app = self.make_app_shell()
        app.demo_mode = True
        app.demo_busy = True

        app._handle_event(
            AppEvent(
                "demo_idle_ready",
                {
                    "marker": "[DEMO] Controller idle: stage2_install_success (completed)",
                    "busy": False,
                },
            )
        )

        self.assertFalse(app.demo_busy)
        self.assertEqual(
            app.last_demo_idle_marker,
            "[DEMO] Controller idle: stage2_install_success (completed)",
        )

    def test_handle_event_tracks_paths_and_preflight_when_session_paths_arrive(self) -> None:
        app = self.make_app_shell()

        app._handle_event(
            AppEvent(
                "session_paths",
                {
                    "log_path": "C:/logs/new.log",
                    "report_path": "C:/logs/new-report.txt",
                    "transcript_path": "C:/logs/new-transcript.txt",
                    "settings_path": "C:/logs/settings/new-settings.json",
                    "manifest_path": "C:/logs/sessions/new/session_manifest.json",
                    "bundle_path": "C:/logs/sessions/new/session_bundle.zip",
                    "event_timeline_path": "C:/logs/sessions/new/event_timeline.json",
                    "dashboard_snapshot_path": "C:/logs/sessions/new/dashboard_snapshot_failed.png",
                    "session_id": "new-session",
                    "session_started_at": 1000.0,
                    "session_started_label": "2026-03-15 14:00:00",
                    "run_mode": "Demo",
                },
            )
        )

        self.assertEqual(app.log_path, Path("C:/logs/new.log"))
        self.assertEqual(app.report_path, Path("C:/logs/new-report.txt"))
        self.assertEqual(app.transcript_path, Path("C:/logs/new-transcript.txt"))
        self.assertEqual(app.settings_path, Path("C:/logs/settings/new-settings.json"))
        self.assertEqual(app.manifest_path, Path("C:/logs/sessions/new/session_manifest.json"))
        self.assertEqual(app.bundle_path, Path("C:/logs/sessions/new/session_bundle.zip"))
        self.assertEqual(app.event_timeline_path, Path("C:/logs/sessions/new/event_timeline.json"))
        self.assertEqual(
            app.dashboard_snapshot_path,
            Path("C:/logs/sessions/new/dashboard_snapshot_failed.png"),
        )
        self.assertEqual(app.log_path_var.get(), str(Path("C:/logs/new.log")))
        self.assertEqual(app.report_path_var.get(), str(Path("C:/logs/new-report.txt")))
        self.assertEqual(app.transcript_path_var.get(), str(Path("C:/logs/new-transcript.txt")))
        self.assertEqual(
            app.manifest_path_var.get().replace("\\", "/"),
            "C:/logs/sessions/new/session_manifest.json",
        )
        self.assertEqual(
            app.bundle_path_var.get().replace("\\", "/"),
            "C:/logs/sessions/new/session_bundle.zip",
        )
        self.assertEqual(app.session_id_var.get(), "new-session")
        self.assertEqual(app.session_started_var.get(), "2026-03-15 14:00:00")
        self.assertEqual(app.session_mode_var.get(), "Demo")

    def test_state_changed_updates_session_summary_vars(self) -> None:
        app = self.make_app_shell()

        app._handle_event(
            AppEvent(
                "state_changed",
                {
                    "state": "INSTALLING",
                    "message": "Stage 2: Установка образа",
                    "current_stage": "Этап 2",
                    "session_elapsed_seconds": 120,
                    "stage_started_at": 1700.0,
                    "last_scan_completed_at": "2026-03-15 14:01:00",
                    "requested_firmware_name": "c2960x.tar",
                },
            )
        )

        self.assertEqual(app.state_var.get(), "Stage 2: Установка образа")
        self.assertEqual(app.current_stage_var.get(), "Этап 2")
        self.assertEqual(app.session_duration_var.get(), "00:02:00")
        self.assertEqual(app.active_stage_started_at_value, 1700.0)
        self.assertEqual(app.last_scan_time_var.get(), "2026-03-15 14:01:00")

    def test_handle_event_updates_operator_message_block(self) -> None:
        app = self.make_app_shell()
        message = SimpleNamespace(
            title="Ошибка подключения",
            detail="Порт занят другой программой.",
            next_step="Закройте терминал и повторите сканирование.",
            severity="error",
        )

        app._handle_event(AppEvent("operator_message", {"message": message}))

        self.assertEqual(app.operator_title_var.get(), "Ошибка подключения")
        self.assertEqual(app.operator_detail_var.get(), "Порт занят другой программой.")
        self.assertEqual(
            app.operator_next_step_var.get(), "Закройте терминал и повторите сканирование."
        )
        self.assertEqual(app.operator_severity_var.get(), "ОШИБКА")

    def test_scan_results_updates_tree_and_scan_status(self) -> None:
        app = self.make_app_shell()
        results = [
            ScanResult(
                target=ConnectionTarget("COM7", "COM7"),
                available=True,
                status_message="Коммутатор готов (Switch#)",
                prompt_type="priv",
                connection_state="ready",
                version="15.2(7)E13",
            )
        ]

        app._handle_event(
            AppEvent(
                "scan_results",
                {"results": results, "selected_target_id": "COM7"},
            )
        )

        self.assertEqual(app.scan_status_var.get(), "Найдено COM-целей: 1. Выбрана цель COM7.")
        self.assertIn("COM7", app.targets_tree.nodes)
        self.assertEqual(app.targets_tree.selection(), ("COM7",))
        self.assertEqual(app.targets_tree.nodes["COM7"]["values"], ("Готово", "Готово"))

    def test_scan_results_compacts_error_text_for_tree_status(self) -> None:
        app = self.make_app_shell()
        results = [
            ScanResult(
                target=ConnectionTarget("COM3", "COM3"),
                available=False,
                status_message=(
                    "Ошибка: could not open port 'COM3': "
                    "OSError(22, 'Превышен таймаут семафора.', None, 121)"
                ),
                prompt_type="",
                connection_state="error",
                version="",
            )
        ]

        app._handle_event(
            AppEvent(
                "scan_results",
                {"results": results, "selected_target_id": "COM3"},
            )
        )

        self.assertEqual(app.targets_tree.nodes["COM3"]["values"], ("Таймаут", "Ошибка"))
        self.assertEqual(app.device_status_summary_var.get(), "Порт не ответил вовремя")

    def test_operator_message_compacts_summary_status_for_dashboard(self) -> None:
        app = self.make_app_shell()
        message = SimpleNamespace(
            title="Ошибка подключения",
            detail=(
                "Ошибка: could not open port 'COM3': "
                "OSError(22, 'Превышен таймаут семафора.', None, 121)"
            ),
            next_step="Проверьте COM-порт.",
            severity="error",
        )

        app._handle_event(AppEvent("operator_message", {"message": message}))

        self.assertEqual(app.device_status_summary_var.get(), "Порт не ответил вовремя")

    def test_notebook_tabs_payload_exposes_hybrid_diagnostics_structure(self) -> None:
        app = self.make_app_shell()

        payload = app._build_notebook_tabs_payload()

        self.assertEqual(sorted(payload), ["Журнал", "Памятка"])
        self.assertTrue(payload["Журнал"]["selected"])
        self.assertIn("click_point", payload["Памятка"])

    def test_workspace_tabs_payload_exposes_operator_split(self) -> None:
        app = self.make_app_shell()
        app.workspace_notebook = DummyNotebook(
            {
                "flash": "Прошивка",
                "metrics": "Состояние и артефакты",
            },
            current="flash",
        )

        payload = app._build_workspace_tabs_payload()

        self.assertEqual(sorted(payload), ["Прошивка", "Состояние и артефакты"])
        self.assertTrue(payload["Прошивка"]["selected"])
        self.assertIn("click_point", payload["Состояние и артефакты"])

    def test_selected_target_changed_updates_tree_and_persists(self) -> None:
        app = self.make_app_shell()
        app.targets_tree.nodes["COM5"] = {"text": "COM5", "values": ()}

        app._handle_event(
            AppEvent("selected_target_changed", {"target_id": "COM5", "manual_override": True})
        )

        self.assertEqual(app.selected_target_var.get(), "COM5")
        self.assertEqual(app.manual_override_var.get(), "Выбор цели: вручную")
        self.assertEqual(app.targets_tree.selection(), ("COM5",))
        app._persist_settings.assert_called_once_with(preferred_target_id="COM5")
        self.assertFalse(app._suppress_target_selection_event)

    def test_on_demo_scenario_selected_updates_controller_and_settings(self) -> None:
        app = self.make_app_shell()
        app.demo_mode = True
        app.demo_scenario_var = DummyVar("Этап 2: успешная установка")
        app.demo_display_to_name = {"Этап 2: успешная установка": "stage2_install_success"}
        app.demo_name_to_display = {"stage2_install_success": "Этап 2: успешная установка"}
        app.selected_demo_scenario_name = "scan_ready"
        app.controller = object.__new__(DemoReplayController)
        app.controller.set_scenario = Mock(return_value=True)
        app._refresh_demo_details = Mock()
        app._log_demo_ui_action = Mock()

        app._on_demo_scenario_selected(None)

        app.controller.set_scenario.assert_called_once_with("stage2_install_success")
        self.assertEqual(app.selected_demo_scenario_name, "stage2_install_success")
        app._refresh_demo_details.assert_called_once_with()
        app._persist_settings.assert_called_once_with()
        app._log_demo_ui_action.assert_called_once_with(
            "Выбран сценарий", "Этап 2: успешная установка"
        )

    def test_demo_scenario_button_updates_controller_and_settings(self) -> None:
        app = self.make_app_shell()
        app.demo_mode = True
        app.demo_display_to_name = {"Этап 2: успешная установка": "stage2_install_success"}
        app.demo_name_to_display = {"stage2_install_success": "Этап 2: успешная установка"}
        app.selected_demo_scenario_name = "scan_ready"
        app.controller = object.__new__(DemoReplayController)
        app.controller.set_scenario = Mock(return_value=True)
        app._refresh_demo_details = Mock()
        app._log_demo_ui_action = Mock()

        app._on_demo_scenario_button("stage2_install_success")

        app.controller.set_scenario.assert_called_once_with("stage2_install_success")
        self.assertEqual(app.selected_demo_scenario_name, "stage2_install_success")
        self.assertEqual(app.demo_scenario_var.get(), "Этап 2: успешная установка")
        app._refresh_demo_details.assert_called_once_with()
        app._persist_settings.assert_called_once_with()
        app._log_demo_ui_action.assert_called_once_with(
            "Выбран сценарий", "Этап 2: успешная установка"
        )

    def test_log_demo_ui_action_appends_log_and_enqueues_event(self) -> None:
        app = self.make_app_shell()
        app.demo_mode = True

        with (
            patch("ciscoautoflash.ui.app.append_session_log") as append_log,
            patch("ciscoautoflash.ui.app.timestamp", return_value="2026-03-15 13:31:54"),
        ):
            app._log_demo_ui_action("Запущен Stage 3", "Проверка")

        append_log.assert_called_once_with(
            app.log_path,
            "[2026-03-15 13:31:54] [DEMO][UI] Запущен Stage 3: Проверка",
        )
        event = app.event_queue.get_nowait()
        self.assertEqual(event.kind, "log")
        self.assertEqual(event.payload["level"], "info")
        self.assertIn("[DEMO][UI] Запущен Stage 3: Проверка", event.payload["line"])

    def test_diagnostics_tab_change_logs_selected_tab_in_demo(self) -> None:
        app = self.make_app_shell()
        app.demo_mode = True
        app._log_demo_ui_action = Mock()
        app.diagnostics_notebook.current = "runbook"

        app._on_diagnostics_tab_changed(SimpleNamespace(widget=app.diagnostics_notebook))

        app._log_demo_ui_action.assert_called_once_with(
            "Открыта вкладка", "Памятка", level="debug"
        )

    def test_demo_action_buttons_log_ui_actions(self) -> None:
        app = self.make_app_shell()
        app.demo_mode = True
        app._log_demo_ui_action = Mock()

        app._on_scan()
        app._on_stage1()
        app._on_stage2()
        app._on_stage3()
        app._on_stop()

        self.assertEqual(
            app._log_demo_ui_action.call_args_list,
            [
                call("Запущен Scan"),
                call("Запущен Stage 1"),
                call("Запущен Stage 2", "Файл: c2960x-universalk9.tar"),
                call("Запущен Stage 3"),
                call("Нажат Stop"),
            ],
        )

    def test_demo_target_selection_logs_ui_action(self) -> None:
        app = self.make_app_shell()
        app.demo_mode = True
        app._log_demo_ui_action = Mock()
        app.targets_tree.nodes["COM5"] = {"text": "COM5", "values": ()}
        app.targets_tree.selection_set("COM5")
        app.controller.select_target = Mock(return_value=True)

        app._on_target_selected(None)

        app._log_demo_ui_action.assert_called_once_with("Выбрана цель", "COM5")

    def test_programmatic_target_selection_does_not_trigger_manual_handler(self) -> None:
        app = self.make_app_shell()
        app.demo_mode = True
        app._suppress_target_selection_event = True
        app._log_demo_ui_action = Mock()
        app.targets_tree.nodes["COM5"] = {"text": "COM5", "values": ()}
        app.targets_tree.selection_set("COM5")
        app.controller.select_target = Mock(return_value=True)

        app._on_target_selected(None)

        app.controller.select_target.assert_not_called()
        app._log_demo_ui_action.assert_not_called()

    def test_manual_target_selection_ignores_already_selected_target(self) -> None:
        app = self.make_app_shell()
        app.demo_mode = True
        app._log_demo_ui_action = Mock()
        app.selected_target_var.set("COM5")
        app.targets_tree.nodes["COM5"] = {"text": "COM5", "values": ()}
        app.targets_tree.selection_set("COM5")
        app.controller.select_target = Mock(return_value=True)

        app._on_target_selected(None)

        app.controller.select_target.assert_not_called()
        app._log_demo_ui_action.assert_not_called()

    def test_drain_events_dispatches_all_items_and_reschedules(self) -> None:
        app = self.make_app_shell()
        handled: list[str] = []
        app._handle_event = lambda event: handled.append(event.kind)
        app._record_event_timeline_entry = Mock()
        app.event_queue.put(AppEvent("log", {"line": "a"}))
        app.event_queue.put(AppEvent("progress", {"percent": 10}))

        app._drain_events()

        self.assertEqual(handled, ["log", "progress"])
        self.assertEqual(app._record_event_timeline_entry.call_count, 2)
        self.assertEqual(app.window.after_calls[0][0], 100)

    def test_open_helpers_delegate_to_open_path(self) -> None:
        app = self.make_app_shell()
        app._open_path = Mock()

        app._open_log()
        app._open_report()
        app._open_transcript()
        app._open_logs_dir()

        expected = [
            ((app.log_path,),),
            ((app.report_path,),),
            ((app.transcript_path,),),
            ((app.session.logs_dir,),),
        ]
        self.assertEqual(app._open_path.call_args_list, expected)

    def test_demo_open_helpers_log_ui_actions(self) -> None:
        app = self.make_app_shell()
        app.demo_mode = True
        app._open_path = Mock()
        app._log_demo_ui_action = Mock()

        app._open_log()
        app._open_report()
        app._open_transcript()
        app._open_logs_dir()

        self.assertEqual(
            app._log_demo_ui_action.call_args_list,
            [
                call("Открыт журнал", str(app.log_path)),
                call("Открыт отчёт", str(app.report_path)),
                call("Открыт транскрипт", str(app.transcript_path)),
                call("Открыта папка логов", str(app.session.logs_dir)),
            ],
        )

    def test_open_session_folder_uses_session_dir(self) -> None:
        app = self.make_app_shell()
        app._open_path = Mock()
        app._open_session_folder()
        app._open_path.assert_called_once_with(app.session.session_dir)

    def test_refresh_hardware_day_summary_uses_latest_preflight_and_snapshot(self) -> None:
        app = self.make_app_shell()
        latest_summary = {
            "status": "READY",
            "completed_at": "2026-04-02T12:00:00",
        }
        snapshot = {
            "console": {"ready": True},
        }
        described = {
            "console": "Видно COM: COM7. Основной кандидат: COM7.",
            "ethernet": "Ethernet up: Ethernet.",
            "ssh": "Host не задан; ping и hidden SSH probe не выполнялись.",
            "live_run_path": "console -> scan -> stage1 -> stage2 -> stage3 -> bundle",
            "return_path": "session bundle -> session folder -> triage_session_return.py",
        }

        with (
            patch(
                "ciscoautoflash.ui.app.load_operator_preflight_summary",
                return_value=latest_summary,
            ),
            patch(
                "ciscoautoflash.ui.app.format_latest_preflight_status",
                return_value="READY (2026-04-02 12:00:00)",
            ),
            patch(
                "ciscoautoflash.ui.app.build_connection_snapshot",
                return_value=snapshot,
            ),
            patch(
                "ciscoautoflash.ui.app.describe_connection_snapshot",
                return_value=described,
            ),
        ):
            app._refresh_hardware_day_summary()

        self.assertEqual(app.hardware_gate_var.get(), "READY (2026-04-02 12:00:00)")
        self.assertIn("COM7", app.hardware_console_var.get())
        self.assertIn("Ethernet", app.hardware_ethernet_var.get())
        self.assertIn("Host не задан", app.hardware_ssh_var.get())
        self.assertIn("Serial-first live run", app.hardware_day_status_var.get())

    def test_schedule_hardware_day_refresh_debounces_with_after_cancel(self) -> None:
        app = self.make_app_shell()

        app._schedule_hardware_day_refresh(delay_ms=500)
        first_handle = app._hardware_day_refresh_after_id
        app._schedule_hardware_day_refresh(delay_ms=500)

        self.assertEqual(app._hardware_day_refresh_request_token, 2)
        self.assertIn(first_handle, app.window.cancelled_after_ids)
        self.assertEqual(app.window.after_calls[-1][0], 500)

    def test_handle_event_scan_results_schedules_hardware_day_refresh(self) -> None:
        app = self.make_app_shell()
        app._schedule_hardware_day_refresh = Mock()

        app._handle_event(AppEvent("scan_results", {"results": [], "selected_target_id": ""}))

        app._schedule_hardware_day_refresh.assert_called_once_with()

    def test_drain_hardware_day_results_ignores_stale_result(self) -> None:
        app = self.make_app_shell()
        app._hardware_day_refresh_request_token = 2
        app._hardware_day_refresh_inflight = True
        app._start_hardware_day_refresh = Mock()
        app._hardware_day_refresh_queue.put(
            {
                "request_token": 1,
                "latest_preflight": {"status": "READY"},
                "snapshot": {"console": {"ready": True}},
                "described": {
                    "console": "COM7",
                    "ethernet": "Ethernet up",
                    "ssh": "not checked",
                    "live_run_path": "console -> scan -> stage1 -> stage2 -> stage3 -> bundle",
                    "return_path": "session bundle -> session folder -> triage_session_return.py",
                },
            }
        )

        app._drain_hardware_day_refresh_results()

        app._start_hardware_day_refresh.assert_called_once_with(2)
        self.assertEqual(app._hardware_day_refresh_applied_token, 0)

    def test_export_session_bundle_updates_footer_and_statuses(self) -> None:
        app = self.make_app_shell()
        app._persist_settings = Mock()
        app._refresh_artifact_statuses = Mock()
        app._log_demo_ui_action = Mock()
        bundle_path = Path("C:/logs/sessions/current/session_bundle.zip")

        with patch(
            "ciscoautoflash.ui.app.export_session_bundle",
            return_value=bundle_path,
        ) as export:
            app._export_session_bundle()

        export.assert_called_once_with(app.session)
        app._persist_settings.assert_called_once_with()
        app._refresh_artifact_statuses.assert_called_once_with()
        self.assertEqual(app.bundle_path, bundle_path)
        self.assertEqual(app.bundle_path_var.get(), str(bundle_path))
        self.assertIn("session_bundle.zip", app.footer_var.get())

    def test_persist_settings_writes_demo_scenario_name(self) -> None:
        app = self.make_app_shell()
        app._persist_settings = CiscoAutoFlashDesktop._persist_settings.__get__(
            app, CiscoAutoFlashDesktop
        )
        app.selected_demo_scenario_name = "stage3_verify"
        app.window.geometry = lambda: "1440x900"
        with patch("ciscoautoflash.ui.app.save_settings") as save_settings:
            app._persist_settings(preferred_target_id="COM7")

        saved = save_settings.call_args.args[1]
        self.assertEqual(saved.demo_scenario_name, "stage3_verify")
        self.assertEqual(saved.preferred_target_id, "COM7")

    def test_open_path_handles_missing_and_existing_paths(self) -> None:
        app = self.make_app_shell()

        with patch("ciscoautoflash.ui.app.messagebox.showinfo") as showinfo:
            app._open_path(Path("C:/definitely/missing.txt"))
            showinfo.assert_called_once()

        existing = Path(__file__)
        with patch("ciscoautoflash.ui.app.os.startfile") as startfile:
            app._open_path(existing)
            startfile.assert_called_once_with(str(existing))

    def test_record_event_timeline_writes_normalized_json(self) -> None:
        app = self.make_app_shell()
        app.current_state_name = "FAILED"
        app.current_stage_var.set("Этап 2")
        app.selected_target_var.set("COM7")
        app.operator_message_code = "timeout"
        app._progress_percent_value = 60
        app.event_timeline_path.unlink(missing_ok=True)
        app.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        app.manifest_path.write_text(
            json.dumps({"artifacts": {}}, ensure_ascii=False),
            encoding="utf-8",
        )

        app._record_event_timeline_entry(AppEvent("state_changed", {"message": "failed"}))

        saved = json.loads(app.event_timeline_path.read_text(encoding="utf-8"))
        self.assertEqual(saved[-1]["kind"], "state_changed")
        self.assertEqual(saved[-1]["state"], "FAILED")
        self.assertEqual(saved[-1]["current_stage"], "Этап 2")
        self.assertEqual(saved[-1]["selected_target_id"], "COM7")
        self.assertEqual(saved[-1]["operator_message_code"], "timeout")
        manifest = json.loads(app.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["artifacts"]["event_timeline_path"],
            str(app.event_timeline_path),
        )

    def test_state_changed_captures_terminal_snapshot_once(self) -> None:
        app = self.make_app_shell()
        app.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        app.manifest_path.write_text(
            json.dumps({"artifacts": {"event_timeline_path": str(app.event_timeline_path)}}),
            encoding="utf-8",
        )
        image = Mock()

        with patch("ciscoautoflash.ui.app.ImageGrab") as image_grab:
            image_grab.grab.return_value = image
            app._handle_event(
                AppEvent(
                    "state_changed",
                    {"state": "FAILED", "message": "failed", "current_stage": "Этап 2"},
                )
            )
            app._handle_event(
                AppEvent(
                    "state_changed",
                    {"state": "FAILED", "message": "failed again", "current_stage": "Этап 2"},
                )
            )

        self.assertEqual(image_grab.grab.call_count, 1)
        self.assertTrue(str(app.dashboard_snapshot_path).endswith("dashboard_snapshot_failed.png"))
        image.save.assert_called_once()

    def test_on_close_disposes_controller_and_window(self) -> None:
        app = self.make_app_shell()

        app._on_close()

        app._persist_settings.assert_called_once_with()
        app.controller.dispose.assert_called_once_with()
        self.assertTrue(app.window.destroyed)


if __name__ == "__main__":
    unittest.main()
