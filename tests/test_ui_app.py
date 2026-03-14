from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock, patch

if "ttkbootstrap" not in sys.modules:
    ttkbootstrap_stub = types.SimpleNamespace(
        Window=object,
        Frame=object,
        Labelframe=object,
        Label=object,
        Button=object,
        Entry=object,
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
        app.progress = DummyProgress()
        app.log_box = DummyLogBox()
        app.targets_tree = DummyTree()
        app.state_var = DummyVar()
        app.state_badge_var = DummyVar()
        app.transport_mode_var = DummyVar("Serial/USB")
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
        app.selected_target_var = DummyVar()
        app.scan_status_var = DummyVar()
        app.log_path_var = DummyVar()
        app.report_path_var = DummyVar()
        app.transcript_path_var = DummyVar()
        app.settings_path_var = DummyVar()
        app.log_status_var = DummyVar()
        app.report_status_var = DummyVar()
        app.transcript_status_var = DummyVar()
        app.settings_status_var = DummyVar()
        app.firmware_input_var = DummyVar("c2960x-universalk9.tar")
        app.log_path = Path("C:/logs/current.log")
        app.report_path = Path("C:/logs/report.txt")
        app.transcript_path = Path("C:/logs/transcript.txt")
        app.settings_path = Path("C:/logs/settings/settings.json")
        app.settings = AppSettings(preferred_target_id="")
        app.scan_results = {}
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
                },
            )
        )

        self.assertEqual(app.log_path, Path("C:/logs/new.log"))
        self.assertEqual(app.report_path, Path("C:/logs/new-report.txt"))
        self.assertEqual(app.transcript_path, Path("C:/logs/new-transcript.txt"))
        self.assertEqual(app.settings_path, Path("C:/logs/settings/new-settings.json"))
        self.assertEqual(app.log_path_var.get(), str(Path("C:/logs/new.log")))
        self.assertEqual(app.report_path_var.get(), str(Path("C:/logs/new-report.txt")))
        self.assertEqual(app.transcript_path_var.get(), str(Path("C:/logs/new-transcript.txt")))

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

        expected = [
            ((app.log_path,),),
            ((app.report_path,),),
            ((app.transcript_path,),),
        ]
        self.assertEqual(app._open_path.call_args_list, expected)

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
