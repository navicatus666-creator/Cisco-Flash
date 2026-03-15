from __future__ import annotations

import sys
import types
import unittest
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
from ciscoautoflash.ui.app import CiscoAutoFlashDesktop


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
        self.destroyed = False

    def after(self, delay: int, callback) -> None:
        self.after_calls.append((delay, callback))

    def destroy(self) -> None:
        self.destroyed = True


class CiscoAutoFlashDesktopSmokeTests(unittest.TestCase):
    def make_app_shell(self) -> CiscoAutoFlashDesktop:
        app = object.__new__(CiscoAutoFlashDesktop)
        app.window = DummyWindow()
        app.event_queue = Queue()
        app.scan_button = DummyButton()
        app.stage1_button = DummyButton()
        app.stage2_button = DummyButton()
        app.stage3_button = DummyButton()
        app.stop_button = DummyButton()
        app.report_button = DummyButton()
        app.artifact_bundle_button = DummyButton()
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
        app.firmware_input_var = DummyVar("c2960x-universalk9.tar")
        app.demo_scenario_var = DummyVar("")
        app.demo_description_var = DummyVar("")
        app.demo_actions_var = DummyVar("")
        app.log_path = Path("C:/logs/current.log")
        app.report_path = Path("C:/logs/report.txt")
        app.transcript_path = Path("C:/logs/transcript.txt")
        app.settings_path = Path("C:/logs/settings/settings.json")
        app.manifest_path = Path("C:/logs/sessions/current/session_manifest.json")
        app.bundle_path = Path("C:/logs/sessions/current/session_bundle.zip")
        app.session_started_at_value = 0.0
        app.active_stage_started_at_value = None
        sessions_dir = Path("C:/logs/sessions")
        session_dir = sessions_dir / "current"
        for directory in (sessions_dir, session_dir):
            directory.mkdir(parents=True, exist_ok=True)
        app.session = SimpleNamespace(
            logs_dir=Path("C:/logs"),
            sessions_dir=sessions_dir,
            session_dir=session_dir,
            session_id="test",
            started_at=0.0,
            manifest_path=app.manifest_path,
            bundle_path=app.bundle_path,
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
        app._suppress_target_selection_event = False
        app.selected_demo_scenario_name = ""
        app.demo_display_to_name = {}
        app.controller = Mock()
        app._persist_settings = Mock()
        return app

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
        app.event_queue.put(AppEvent("log", {"line": "a"}))
        app.event_queue.put(AppEvent("progress", {"percent": 10}))

        app._drain_events()

        self.assertEqual(handled, ["log", "progress"])
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

    def test_on_close_disposes_controller_and_window(self) -> None:
        app = self.make_app_shell()

        app._on_close()

        app._persist_settings.assert_called_once_with()
        app.controller.dispose.assert_called_once_with()
        self.assertTrue(app.window.destroyed)


if __name__ == "__main__":
    unittest.main()
