from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pyautogui  # type: ignore[import-untyped]
from pywinauto import Desktop  # type: ignore[import-untyped]
from pywinauto.base_wrapper import BaseWrapper  # type: ignore[import-untyped]

from ciscoautoflash.replay.loader import load_scenarios

WINDOW_TITLE_PATTERN = re.compile(r"CiscoAutoFlash")
DEFAULT_SCENARIOS = (
    "scan_ready",
    "stage1_reboot_config_dialog",
    "stage2_install_success",
    "stage2_install_timeout",
    "stage3_verify",
)
TAB_RETRY_OFFSETS = (
    (0, 0),
    (-14, 0),
    (14, 0),
    (0, -6),
    (0, 6),
    (-22, 0),
    (22, 0),
)
SELECTOR_RETRY_OFFSETS = (
    (0, 0),
    (-10, 0),
    (10, 0),
    (-16, 0),
    (16, 0),
)
TAB_STEP_ALIASES = {
    "Журнал": "journal",
    "Артефакты сессии": "artifacts",
    "Памятка": "runbook",
}
LOG_FILE_RE = re.compile(r"^ciscoautoflash_(\d{8}_\d{6})\.log$")


@dataclass(slots=True)
class SmokeStepResult:
    name: str
    passed: bool
    evidence: list[str] = field(default_factory=list)
    screenshot_before: str = ""
    screenshot_after: str = ""
    produced_paths: list[str] = field(default_factory=list)


class SmokeFailure(RuntimeError):
    pass


class DemoGuiSmokeRunner:
    def __init__(
        self,
        *,
        python_executable: Path,
        scenario_names: tuple[str, ...],
        output_dir: Path,
        window_timeout: float,
        delay_ms: int,
    ) -> None:
        self.python_executable = python_executable
        self.scenario_names = scenario_names
        self.output_dir = output_dir
        self.window_timeout = window_timeout
        self.delay_ms = delay_ms
        self.project_root = Path(__file__).resolve().parents[1]
        scenario_definitions = load_scenarios()
        self.combo_order = [scenario.name for scenario in scenario_definitions]
        self.scenario_display_by_name = {
            scenario.name: scenario.display_name for scenario in scenario_definitions
        }
        local_appdata = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        self.demo_root = local_appdata / "CiscoAutoFlash" / "demo"
        self.automation_map_path = (
            self.demo_root / "smoke_artifacts" / "current" / "automation_map.json"
        )
        self.automation_map: dict[str, object] = {}
        self.results: list[SmokeStepResult] = []
        self.process: subprocess.Popen[bytes] | None = None
        self.window: BaseWrapper | None = None
        self.session_dir: Path | None = None
        self.log_path: Path | None = None
        self.report_path: Path | None = None
        self.transcript_path: Path | None = None
        self.manifest_path: Path | None = None
        self.bundle_path: Path | None = None
        self._step_log_cursor = 0
        self._step_recent_log_offsets: dict[Path, int] = {}
        self.run_started_at = 0.0
        self._last_marker_line = ""

    def run(self) -> int:
        if len(self.scenario_names) < 5:
            raise SmokeFailure(
                "Smoke runner requires five scenario names in workflow order: "
                "scan, stage1, stage2 success, stage2 timeout, stage3."
            )
        self.output_dir.mkdir(parents=True, exist_ok=True)
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.12
        try:
            self._launch_demo()
            self._baseline_step()
            self._tab_step("Артефакты сессии")
            self._tab_step("Памятка")
            self._tab_step("Журнал")
            self._scan_step()
            self._scenario_selector_step(self.scenario_names[1])
            self._stage1_step()
            self._scenario_selector_step(self.scenario_names[2])
            self._stage2_success_step()
            self._scenario_selector_step(self.scenario_names[3])
            self._stop_step()
            self._scenario_selector_step(self.scenario_names[4])
            self._stage3_step()
            self._artifact_steps()
            self._write_reports()
            return 0
        finally:
            self._shutdown_demo()

    def _launch_demo(self) -> None:
        env = os.environ.copy()
        env["CISCOAUTOFLASH_SMOKE_MODE"] = "1"
        env["CISCOAUTOFLASH_AUTOMATION_MAP"] = "1"
        env["CISCOAUTOFLASH_AUTO_START_SCAN"] = "0"
        env["CISCOAUTOFLASH_DEMO_DELAY_MS"] = str(self.delay_ms)
        self.run_started_at = time.time()
        self.process = subprocess.Popen(
            [
                str(self.python_executable),
                str(self.project_root / "main.py"),
                "--demo",
                "--demo-scenario",
                self.scenario_names[0],
            ],
            cwd=self.project_root,
            env=env,
        )
        self.window = self._wait_for_window()
        self._stabilize_window()
        self._wait_for_current_session_paths()
        self._refresh_automation_map()

    def _shutdown_demo(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is not None:
            return
        try:
            if self.window is not None:
                self.window.set_focus()
                pyautogui.hotkey("alt", "f4")
                self.process.wait(timeout=5)
                return
        except Exception:
            pass
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)

    def _wait_for_window(self) -> BaseWrapper:
        deadline = time.time() + self.window_timeout
        desktop = Desktop(backend="uia")
        while time.time() < deadline:
            for window in desktop.windows():
                title = window.window_text().strip()
                if WINDOW_TITLE_PATTERN.search(title):
                    return window
            time.sleep(0.25)
        raise SmokeFailure("Demo window was not found before timeout.")

    def _refresh_paths(self) -> None:
        payload = self._refresh_automation_map(timeout=0.5, raise_on_timeout=False)
        session_payload = payload.get("session") if isinstance(payload, dict) else None
        if isinstance(session_payload, dict):
            session_dir = session_payload.get("session_dir")
            log_path = session_payload.get("log_path")
            report_path = session_payload.get("report_path")
            transcript_path = session_payload.get("transcript_path")
            manifest_path = session_payload.get("manifest_path")
            bundle_path = session_payload.get("bundle_path")
            if (
                isinstance(session_dir, str)
                and isinstance(log_path, str)
                and isinstance(report_path, str)
                and isinstance(transcript_path, str)
                and isinstance(manifest_path, str)
                and isinstance(bundle_path, str)
                and session_dir
                and log_path
            ):
                self.session_dir = Path(session_dir)
                self.log_path = Path(log_path)
                self.report_path = Path(report_path)
                self.transcript_path = Path(transcript_path)
                self.manifest_path = Path(manifest_path)
                self.bundle_path = Path(bundle_path)
                return

        sessions_dir = self.demo_root / "sessions"
        logs_dir = self.demo_root / "logs"
        reports_dir = self.demo_root / "reports"
        transcripts_dir = self.demo_root / "transcripts"
        recent_logs = sorted(
            [
                path
                for path in logs_dir.glob("ciscoautoflash_*.log")
                if path.stat().st_mtime >= self.run_started_at
            ],
            key=lambda path: path.stat().st_mtime,
        )
        if recent_logs:
            self.log_path = recent_logs[-1]
            match = LOG_FILE_RE.match(self.log_path.name)
            if match is None:
                raise SmokeFailure(f"Unexpected demo log filename: {self.log_path.name}")
            session_id = match.group(1)
            self.session_dir = sessions_dir / session_id
        else:
            session_dirs = sorted(
                [
                    path
                    for path in sessions_dir.glob("*")
                    if path.is_dir() and path.stat().st_mtime >= self.run_started_at
                ],
                key=lambda path: path.stat().st_mtime,
            )
            if not session_dirs:
                raise SmokeFailure("Demo session folder was not created for the current run.")
            self.session_dir = session_dirs[-1]
            session_id = self.session_dir.name
            self.log_path = logs_dir / f"ciscoautoflash_{session_id}.log"
        self.report_path = reports_dir / f"install_report_{session_id}.txt"
        self.transcript_path = transcripts_dir / f"transcript_{session_id}.log"
        self.manifest_path = self.session_dir / "session_manifest.json"
        self.bundle_path = self.session_dir / f"session_bundle_{session_id}.zip"

    def _wait_for_current_session_paths(self, timeout: float = 15.0) -> None:
        deadline = time.time() + timeout
        last_error = "Current demo session paths were not detected."
        while time.time() < deadline:
            try:
                self._refresh_paths()
            except SmokeFailure as exc:
                last_error = str(exc)
                time.sleep(0.2)
                continue
            if self.log_path is not None and self.session_dir is not None:
                return
            time.sleep(0.2)
        raise SmokeFailure(last_error)

    def _wait_for_session_rollover(
        self,
        previous_session_dir: Path | None,
        timeout: float = 15.0,
    ) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self._refresh_paths()
            except SmokeFailure:
                time.sleep(0.2)
                continue
            if (
                self.log_path is not None
                and self.session_dir is not None
                and self.session_dir != previous_session_dir
            ):
                self._refresh_paths()
                return
            time.sleep(0.2)
        raise SmokeFailure("Demo session did not roll over after Scan.")

    def _refresh_automation_map(
        self,
        timeout: float = 5.0,
        *,
        raise_on_timeout: bool = True,
    ) -> dict[str, object]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                payload = json.loads(self.automation_map_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(0.2)
                continue
            if isinstance(payload, dict) and payload:
                self.automation_map = payload
                return payload
            time.sleep(0.2)
        if raise_on_timeout:
            raise SmokeFailure(
                f"Automation map was not available: {self.automation_map_path}"
            )
        return self.automation_map

    @staticmethod
    def _point_from_payload(payload: object, key: str = "click_point") -> tuple[int, int] | None:
        if not isinstance(payload, dict):
            return None
        point = payload.get(key)
        if not isinstance(point, dict):
            return None
        x = point.get("x")
        y = point.get("y")
        if not isinstance(x, int) or not isinstance(y, int):
            return None
        return (x, y)

    def _lookup_control_point(self, name: str) -> tuple[int, int] | None:
        payload = self._refresh_automation_map(timeout=1.5)
        controls = payload.get("controls")
        if not isinstance(controls, dict):
            return None
        return self._point_from_payload(controls.get(name))

    def _lookup_tab_point(self, tab_name: str) -> tuple[int, int] | None:
        payload = self._refresh_automation_map(timeout=1.5)
        tabs = payload.get("tabs")
        if not isinstance(tabs, dict):
            return None
        items = tabs.get("items")
        if not isinstance(items, dict):
            return None
        return self._point_from_payload(items.get(tab_name))

    def _selector_payload(self) -> dict[str, object]:
        payload = self._refresh_automation_map(timeout=1.5)
        selector = payload.get("selector")
        return selector if isinstance(selector, dict) else {}

    def _lookup_selector_button_point(self, scenario_name: str) -> tuple[int, int] | None:
        selector = self._selector_payload()
        buttons = selector.get("buttons")
        if not isinstance(buttons, dict):
            return None
        return self._point_from_payload(buttons.get(scenario_name))

    def _baseline_step(self) -> None:
        def verify() -> list[str]:
            self._refresh_paths()
            self._refresh_automation_map()
            evidence = [f"Window title: {self.window.window_text() if self.window else 'N/A'}"]
            for path in (self.session_dir, self.log_path):
                if path is None or not path.exists():
                    raise SmokeFailure(f"Expected runtime path is missing: {path}")
                evidence.append(f"Present: {path}")
            if self.automation_map_path.exists():
                evidence.append(f"Automation map: {self.automation_map_path}")
            return evidence

        self._run_step("baseline_visibility", verify)

    def _stabilize_window(self) -> None:
        if self.window is None:
            raise SmokeFailure("Demo window is not attached.")
        self.window.set_focus()
        self.window.maximize()
        time.sleep(0.8)

    def _tab_step(self, tab_name: str) -> None:
        def action() -> None:
            self._click_tab(tab_name)

        def verify() -> list[str]:
            payload = self._refresh_automation_map()
            state = payload.get("state")
            if not isinstance(state, dict):
                raise SmokeFailure("Automation map did not provide state payload after tab click.")
            selected_tab = str(state.get("selected_tab", ""))
            if selected_tab != tab_name:
                raise SmokeFailure(
                    f"Selected tab mismatch after click: expected {tab_name}, got {selected_tab}"
                )
            evidence = [f"Selected tab: {selected_tab}"]
            if self._last_marker_line:
                evidence.append(self._last_marker_line)
            return evidence

        self._run_step(f"tab_{TAB_STEP_ALIASES[tab_name]}", verify, action=action)

    def _scenario_selector_step(self, scenario_name: str) -> None:
        def action() -> None:
            self._wait_for_demo_idle_if_needed()
            self._select_scenario(scenario_name)

        def verify() -> list[str]:
            scenario_display = self.scenario_display_by_name[scenario_name]
            payload = self._refresh_automation_map()
            selector = payload.get("selector")
            if not isinstance(selector, dict):
                raise SmokeFailure("Automation map did not provide selector payload after change.")
            current_name = str(selector.get("current_name", ""))
            current_display = str(selector.get("current_display", ""))
            if current_name != scenario_name or current_display != scenario_display:
                raise SmokeFailure(
                    "Scenario selector mismatch after change: "
                    f"expected {scenario_name}/{scenario_display}, got "
                    f"{current_name}/{current_display}"
                )
            evidence = [f"Scenario active: {current_name} -> {current_display}"]
            if self._last_marker_line:
                evidence.append(self._last_marker_line)
            return evidence

        self._run_step(f"scenario_{scenario_name}", verify, action=action)

    def _scan_step(self) -> None:
        previous_session_dir = self.session_dir

        def action() -> None:
            self._click_button("scan")

        def verify() -> list[str]:
            self._wait_for_session_rollover(previous_session_dir)
            self._refresh_automation_map()
            manifest = self._wait_for_manifest(
                lambda data: data.get("selected_target_id") == "COM5",
                "selected_target_id == COM5",
            )
            idle_evidence = self._wait_for_demo_idle()
            return [
                f"Selected target: {manifest.get('selected_target_id', '')}",
                self._wait_for_log_marker_from_start("Выбрана цель"),
                *idle_evidence,
            ]

        self._run_step("scan", verify, action=action)

    def _stage1_step(self) -> None:
        def action() -> None:
            self._click_button("stage1")

        def verify() -> list[str]:
            transcript = self._wait_for_file_contains(
                self.transcript_path,
                "Would you like to enter the initial configuration dialog",
            )
            transcript = self._wait_for_file_contains(self.transcript_path, "| no")
            stage_marker = self._wait_for_new_log_marker("[DEMO][UI] Запущен Stage 1")
            idle_evidence = self._wait_for_demo_idle()
            return [
                transcript,
                stage_marker,
                *idle_evidence,
            ]

        self._run_step("stage1", verify, action=action)

    def _stage2_success_step(self) -> None:
        def action() -> None:
            self._click_button("stage2")

        def verify() -> list[str]:
            transcript = self._wait_for_file_contains(
                self.transcript_path,
                "all software images installed",
            )
            stage_marker = self._wait_for_new_log_marker("[DEMO][UI] Запущен Stage 2")
            idle_evidence = self._wait_for_demo_idle()
            return [
                transcript,
                stage_marker,
                *idle_evidence,
            ]

        self._run_step("stage2_success", verify, action=action)

    def _stop_step(self) -> None:
        def action() -> None:
            self._click_button("stage2")
            time.sleep(max(0.15, self.delay_ms / 2000))
            self._click_button("stop")

        def verify() -> list[str]:
            manifest = self._wait_for_manifest(
                lambda data: data.get("final_state") == "FAILED",
                "final_state == FAILED after stop",
            )
            stop_marker = self._wait_for_new_log_marker("Проигрывание остановлено")
            idle_evidence = self._wait_for_demo_idle()
            return [
                stop_marker,
                f"State after stop: {manifest.get('final_state', '')}",
                *idle_evidence,
            ]

        self._run_step("stop_during_busy_demo", verify, action=action)

    def _stage3_step(self) -> None:
        def action() -> None:
            self._click_button("stage3")

        def verify() -> list[str]:
            self._wait_for_file_exists(self.report_path)
            manifest = self._wait_for_manifest(
                lambda data: data.get("final_state") == "DONE",
                "final_state == DONE",
            )
            return [
                self._wait_for_new_log_marker("[DEMO][UI] Запущен Stage 3"),
                f"Report: {self.report_path}",
                f"Manifest final_state: {manifest.get('final_state', '')}",
            ]

        self._run_step("stage3_verify", verify, action=action)

    def _artifact_steps(self) -> None:
        artifact_steps = [
            ("open_log", self.log_path),
            ("open_report", self.report_path),
            ("open_transcript", self.transcript_path),
            ("open_logs_dir", self.log_path.parent if self.log_path else None),
            ("open_session_dir", self.session_dir),
        ]
        for name, expected_path in artifact_steps:
            if expected_path is None:
                raise SmokeFailure(f"Artifact path was not resolved for step {name}.")
            self._run_step(
                name,
                lambda path=expected_path: self._verify_smoke_open(path),
                action=lambda button_name=name: self._click_button(button_name),
            )

        self._run_step(
            "export_bundle",
            self._verify_bundle_export,
            action=lambda: self._click_button("export_bundle"),
        )

    def _verify_smoke_open(self, expected_path: Path) -> list[str]:
        path = expected_path.resolve()
        marker_line = self._wait_for_new_log_marker(f"Smoke-mode open suppressed: {path}")
        payload = self._refresh_automation_map()
        state = payload.get("state") if isinstance(payload, dict) else None
        last_smoke_open_path = ""
        if isinstance(state, dict):
            last_smoke_open_path = str(state.get("last_smoke_open_path", ""))
        if last_smoke_open_path != str(path):
            raise SmokeFailure(
                "Automation map last_smoke_open_path mismatch: "
                f"expected {path}, got {last_smoke_open_path or '<empty>'}"
            )
        self._refresh_paths()
        if path.exists():
            return [marker_line, f"Smoke open confirmed: {path}"]
        raise SmokeFailure(f"Expected open target does not exist: {path}")

    def _verify_bundle_export(self) -> list[str]:
        self._wait_for_file_exists(self.bundle_path)
        return [
            self._wait_for_new_log_marker("Экспортирован session bundle"),
            f"Bundle: {self.bundle_path}",
        ]

    def _run_step(
        self,
        name: str,
        verify,
        *,
        action=None,
        produced_paths: list[Path] | None = None,
    ) -> None:
        before = self._capture(name, "before")
        self._step_log_cursor = self._snapshot_log_cursor()
        self._step_recent_log_offsets = self._snapshot_recent_log_offsets()
        self._last_marker_line = ""
        if action is not None:
            action()
        self._refresh_paths()
        evidence = verify()
        after = self._capture(name, "after")
        self.results.append(
            SmokeStepResult(
                name=name,
                passed=True,
                evidence=evidence,
                screenshot_before=str(before),
                screenshot_after=str(after),
                produced_paths=[str(path) for path in (produced_paths or []) if path is not None],
            )
        )

    def _state_payload(self) -> dict[str, object]:
        payload = self._refresh_automation_map(timeout=1.5, raise_on_timeout=False)
        state = payload.get("state") if isinstance(payload, dict) else None
        return state if isinstance(state, dict) else {}

    @staticmethod
    def _state_bool(state: dict[str, object], key: str) -> bool:
        return bool(state.get(key, False))

    def _wait_for_demo_idle_if_needed(self, timeout: float = 15.0) -> list[str]:
        state = self._state_payload()
        if not state:
            return []
        if not self._state_bool(state, "demo_busy") and not self._state_bool(state, "stop_enabled"):
            return []
        return self._wait_for_demo_idle(timeout=timeout)

    def _wait_for_demo_idle(self, timeout: float = 15.0) -> list[str]:
        deadline = time.time() + timeout
        marker_line = ""
        while time.time() < deadline:
            if not marker_line:
                marker_line = self._wait_for_new_log_marker(
                    "[DEMO] Controller idle:",
                    timeout=0.6,
                    raise_on_timeout=False,
                )
            state = self._state_payload()
            if state:
                demo_busy = self._state_bool(state, "demo_busy")
                stop_enabled = self._state_bool(state, "stop_enabled")
                last_idle_marker = str(state.get("last_demo_idle_marker", "")).strip()
                if marker_line and not demo_busy and not stop_enabled and last_idle_marker:
                    if last_idle_marker in marker_line:
                        return [
                            marker_line,
                            (
                                "Demo idle confirmed: "
                                f"busy={demo_busy}, stop_enabled={stop_enabled}"
                            ),
                        ]
            time.sleep(0.1)
        raise SmokeFailure(
            "Demo controller did not become idle before the next scenario switch."
        )

    def _capture(self, name: str, phase: str) -> Path:
        path = self.output_dir / f"{name}_{phase}.png"
        pyautogui.screenshot(str(path))
        return path

    def _click_button(self, name: str) -> None:
        point = self._lookup_control_point(name)
        if point is None:
            raise SmokeFailure(f"Automation map does not provide click point for control: {name}")
        self._click_absolute(*point)

    def _click_tab(self, tab_name: str) -> None:
        marker = f"[DEMO][UI] Открыта вкладка: {tab_name}"
        point = self._lookup_tab_point(tab_name)
        if point is None:
            raise SmokeFailure(f"Automation map does not provide click point for tab: {tab_name}")
        self._last_marker_line = self._retry_click_point_with_marker(
            point,
            TAB_RETRY_OFFSETS,
            marker,
        )

    def _select_scenario(self, scenario_name: str) -> None:
        if scenario_name not in self.combo_order:
            raise SmokeFailure(f"Scenario is not available in combo order: {scenario_name}")
        marker = f"[DEMO][UI] Выбран сценарий: {self.scenario_display_by_name[scenario_name]}"
        scenario_button_point = self._lookup_selector_button_point(scenario_name)
        if scenario_button_point is not None:
            self._last_marker_line = self._retry_click_point_with_marker(
                scenario_button_point,
                ((0, 0), (-8, 0), (8, 0), (0, -4), (0, 4)),
                marker,
            )
            return
        combo_items = self._selector_items()
        target_display = self.scenario_display_by_name[scenario_name]
        if target_display not in combo_items:
            raise SmokeFailure(
                f"Scenario display is not available in selector items: {target_display}"
            )
        target_index = combo_items.index(target_display)
        for x_offset, y_offset in SELECTOR_RETRY_OFFSETS:
            selector = self._selector_payload()
            current_index = self._selector_current_index(combo_items, selector)
            arrow_point = self._point_from_payload(selector, "arrow_click_point")
            selector_point = self._point_from_payload(selector)
            if arrow_point is None and selector_point is None:
                raise SmokeFailure("Automation map does not provide selector click points.")
            if arrow_point is not None:
                self._click_absolute(arrow_point[0] + x_offset, arrow_point[1] + y_offset)
            else:
                self._click_absolute(selector_point[0] + x_offset, selector_point[1] + y_offset)
            marker_line = self._try_selector_sequence(current_index, target_index, marker)
            if marker_line:
                self._last_marker_line = marker_line
                return
            pyautogui.press("escape")
            time.sleep(0.1)
        raise SmokeFailure(f"Scenario selector did not switch to {scenario_name}.")

    def _selector_items(self) -> list[str]:
        selector = self._selector_payload()
        items = selector.get("items")
        if isinstance(items, list) and items:
            return [str(item) for item in items]
        return list(self.scenario_display_by_name.values())

    @staticmethod
    def _selector_current_index(combo_items: list[str], selector: dict[str, object]) -> int | None:
        current_display = str(selector.get("current_display", ""))
        if current_display in combo_items:
            return combo_items.index(current_display)
        return None

    def _try_selector_sequence(
        self,
        current_index: int | None,
        target_index: int,
        marker: str,
    ) -> str:
        time.sleep(0.12)
        pyautogui.hotkey("alt", "down")
        time.sleep(0.12)
        if current_index is None:
            pyautogui.press("home")
            time.sleep(0.05)
            key = "down"
            count = target_index
        else:
            delta = target_index - current_index
            key = "down" if delta >= 0 else "up"
            count = abs(delta)
        for _ in range(count):
            pyautogui.press(key)
            time.sleep(0.05)
        pyautogui.press("enter")
        time.sleep(0.6)
        return self._wait_for_new_log_marker(marker, timeout=1.8, raise_on_timeout=False)

    def _click_absolute(self, x: int, y: int) -> None:
        if self.window is None:
            raise SmokeFailure("Demo window is not attached.")
        self.window.set_focus()
        pyautogui.click(x, y)
        time.sleep(0.3)

    def _retry_click_point_with_marker(
        self,
        point: tuple[int, int],
        offsets: tuple[tuple[int, int], ...],
        marker: str,
    ) -> str:
        for x_offset, y_offset in offsets:
            self._click_absolute(point[0] + x_offset, point[1] + y_offset)
            marker_line = self._wait_for_new_log_marker(
                marker,
                timeout=1.0,
                raise_on_timeout=False,
            )
            if marker_line:
                return marker_line
        raise SmokeFailure(f"Target did not emit expected log marker: {marker}")

    def _read_log_text(self) -> str:
        if self.log_path is None or not self.log_path.exists():
            return ""
        return self.log_path.read_text(encoding="utf-8", errors="ignore")

    def _snapshot_log_cursor(self) -> int:
        if self.log_path is None or not self.log_path.exists():
            return 0
        return self.log_path.stat().st_size

    def _recent_logs(self) -> list[Path]:
        logs_dir = self.demo_root / "logs"
        if not logs_dir.exists():
            return []
        return sorted(
            [
                path
                for path in logs_dir.glob("ciscoautoflash_*.log")
                if path.stat().st_mtime >= self.run_started_at
            ],
            key=lambda path: path.stat().st_mtime,
        )

    def _snapshot_recent_log_offsets(self) -> dict[Path, int]:
        return {
            path: path.stat().st_size
            for path in self._recent_logs()
            if path.exists()
        }

    @staticmethod
    def _read_log_delta_for_path(path: Path, cursor: int) -> str:
        if not path.exists():
            return ""
        with path.open("rb") as handle:
            handle.seek(cursor)
            return handle.read().decode("utf-8", errors="ignore")

    def _read_log_delta(self, cursor: int) -> str:
        if self.log_path is None or not self.log_path.exists():
            return ""
        with self.log_path.open("rb") as handle:
            handle.seek(cursor)
            return handle.read().decode("utf-8", errors="ignore")

    def _wait_for_new_log_marker(
        self,
        marker: str,
        *,
        timeout: float = 15.0,
        raise_on_timeout: bool = True,
    ) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            found_logs = False
            for path in self._recent_logs():
                found_logs = True
                cursor = self._step_recent_log_offsets.get(path, 0)
                contents = self._read_log_delta_for_path(path, cursor)
                next_cursor = path.stat().st_size if path.exists() else cursor
                for line in contents.splitlines():
                    if marker in line:
                        self._step_recent_log_offsets[path] = next_cursor
                        if path == self.log_path:
                            self._step_log_cursor = next_cursor
                        return line
                self._step_recent_log_offsets[path] = next_cursor
            if not found_logs:
                self._step_recent_log_offsets = {}
            time.sleep(0.2)
        if raise_on_timeout:
            raise SmokeFailure(f"Log did not contain expected fresh marker: {marker}")
        return ""

    def _wait_for_log_marker_from_start(self, marker: str, timeout: float = 15.0) -> str:
        previous_recent_offsets = dict(self._step_recent_log_offsets)
        previous_cursor = self._step_log_cursor
        self._step_recent_log_offsets = {path: 0 for path in self._recent_logs()}
        self._step_log_cursor = 0
        try:
            return self._wait_for_new_log_marker(marker, timeout=timeout)
        finally:
            self._step_recent_log_offsets = previous_recent_offsets
            self._step_log_cursor = previous_cursor

    def _wait_for_file_exists(self, path: Path | None, timeout: float = 15.0) -> Path:
        if path is None:
            raise SmokeFailure("Expected file path was not initialized.")
        deadline = time.time() + timeout
        while time.time() < deadline:
            if path.exists():
                return path
            time.sleep(0.2)
        raise SmokeFailure(f"Expected file was not created: {path}")

    def _wait_for_file_contains(
        self,
        path: Path | None,
        text: str,
        timeout: float = 15.0,
    ) -> str:
        target = self._wait_for_file_exists(path, timeout=timeout)
        deadline = time.time() + timeout
        while time.time() < deadline:
            contents = target.read_text(encoding="utf-8", errors="ignore")
            if text in contents:
                return f"{target.name} contains: {text}"
            time.sleep(0.2)
        raise SmokeFailure(f"Expected text was not found in {target}: {text}")

    def _wait_for_manifest(
        self,
        predicate,
        description: str,
        timeout: float = 15.0,
    ) -> dict[str, object]:
        manifest_path = self._wait_for_file_exists(self.manifest_path, timeout=timeout)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                time.sleep(0.2)
                continue
            if predicate(data):
                return data
            time.sleep(0.2)
        raise SmokeFailure(f"Manifest did not satisfy condition: {description}")

    def _write_reports(self) -> None:
        results_path = self.output_dir / "gui_smoke_results.json"
        summary_path = self.output_dir / "gui_smoke_summary.md"
        payload = {
            "window_timeout_seconds": self.window_timeout,
            "delay_ms": self.delay_ms,
            "session_dir": str(self.session_dir) if self.session_dir else "",
            "log_path": str(self.log_path) if self.log_path else "",
            "report_path": str(self.report_path) if self.report_path else "",
            "transcript_path": str(self.transcript_path) if self.transcript_path else "",
            "manifest_path": str(self.manifest_path) if self.manifest_path else "",
            "bundle_path": str(self.bundle_path) if self.bundle_path else "",
            "steps": [asdict(item) for item in self.results],
        }
        results_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        lines = [
            "# CiscoAutoFlash Demo GUI Smoke Summary",
            "",
            f"- Output dir: `{self.output_dir}`",
            f"- Session dir: `{self.session_dir}`",
            f"- Delay ms: `{self.delay_ms}`",
            "",
            "## GUI Steps",
            "",
        ]
        for result in self.results:
            status = "PASS" if result.passed else "FAIL"
            lines.append(f"- `{result.name}`: {status}")
            for evidence in result.evidence:
                lines.append(f"  - {evidence}")
            if result.produced_paths:
                lines.append(f"  - Produced: {', '.join(result.produced_paths)}")
        lines.extend(
            [
                "",
                "## Coverage Matrix",
                "",
                "| Feature | Coverage | Notes |",
                "| --- | --- | --- |",
                "| Scenario selector | GUI smoke | Verified through demo UI log entries. |",
                (
                    "| Scan / Stage1 / Stage2 / Stage3 / Stop | GUI smoke + replay/unit | "
                    "Buttons are exercised in demo; deeper behavior stays covered by automated "
                    "replay tests. |"
                ),
                (
                    "| Notebook tabs | GUI smoke | Verified through the smoke-only notebook "
                    "log hook. |"
                ),
                (
                    "| Log/report/transcript/session folder actions | GUI smoke | Smoke mode "
                    "suppresses `os.startfile()` and verifies resolved paths without focus loss. |"
                ),
                (
                    "| Hidden SSH verify/report path | unit/replay | Deliberately not faked by "
                    "desktop clicks. |"
                ),
                (
                    "| Real Serial/USB transport and live switch timing | hardware only | "
                    "Deferred to the first 2960-X runbook. |"
                ),
            ]
        )
        summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run CiscoAutoFlash demo GUI smoke checks.")
    parser.add_argument(
        "--scenario",
        action="append",
        dest="scenarios",
        help="Scenario names in selector order. Defaults to the core pre-hardware set.",
    )
    parser.add_argument(
        "--window-timeout",
        type=float,
        default=20.0,
        help="Seconds to wait for the demo window.",
    )
    parser.add_argument(
        "--delay-ms",
        type=int,
        default=180,
        help="Playback delay passed into demo mode for more stable GUI smoke.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Optional explicit output directory for smoke artifacts.",
    )
    parser.add_argument(
        "--python",
        type=Path,
        default=Path(sys.executable),
        help="Python executable used to launch the demo app.",
    )
    return parser


def default_output_dir() -> Path:
    local_appdata = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return local_appdata / "CiscoAutoFlash" / "demo" / "smoke_artifacts" / timestamp


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    scenarios = tuple(args.scenarios or DEFAULT_SCENARIOS)
    output_dir = args.output_dir or default_output_dir()
    runner = DemoGuiSmokeRunner(
        python_executable=args.python,
        scenario_names=scenarios,
        output_dir=output_dir,
        window_timeout=args.window_timeout,
        delay_ms=args.delay_ms,
    )
    try:
        return runner.run()
    except SmokeFailure as exc:
        failure_path = output_dir.resolve()
        failure_path.mkdir(parents=True, exist_ok=True)
        (failure_path / "gui_smoke_failure.txt").write_text(str(exc) + "\n", encoding="utf-8")
        print(f"GUI smoke failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
