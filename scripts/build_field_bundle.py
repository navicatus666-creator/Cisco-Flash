#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404 - trusted local PyInstaller invocation for field bundle build
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CARRY_ROOT = PROJECT_ROOT / "Возьму С Собой"
APP_NAME = "CiscoAutoFlash"
BUNDLE_ROOT = CARRY_ROOT / APP_NAME
BUILD_ROOT = PROJECT_ROOT / "build" / "field_bundle"
WORK_PATH = BUILD_ROOT / "work"
SPEC_PATH = BUILD_ROOT / "spec"
DOCS_SOURCE = PROJECT_ROOT / "docs" / "pre_hardware"
REPLAY_SOURCE = PROJECT_ROOT / "replay_scenarios"
PYTHON_EXE = Path(r"C:\Python314\python.exe")
EXE_PATH = BUNDLE_ROOT / f"{APP_NAME}.exe"
RUNBOOK_DIR = BUNDLE_ROOT / "_internal" / "docs" / "pre_hardware"
REPLAY_DIR = BUNDLE_ROOT / "_internal" / "replay_scenarios"
NOTE_PATH = CARRY_ROOT / "README_ПЕРЕД_ПОЛЕВЫМ_ТЕСТОМ.txt"
LAUNCHER_PATH = CARRY_ROOT / "Запустить CiscoAutoFlash.bat"


def _clean_previous_bundle() -> None:
    for path in (BUNDLE_ROOT, WORK_PATH, SPEC_PATH):
        if path.exists():
            shutil.rmtree(path)


def _build_bundle() -> None:
    carry_docs = f"{DOCS_SOURCE}{os.pathsep}docs/pre_hardware"
    carry_replay = f"{REPLAY_SOURCE}{os.pathsep}replay_scenarios"
    command = [
        str(PYTHON_EXE),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        APP_NAME,
        "--distpath",
        str(CARRY_ROOT),
        "--workpath",
        str(WORK_PATH),
        "--specpath",
        str(SPEC_PATH),
        "--contents-directory",
        "_internal",
        "--add-data",
        carry_docs,
        "--add-data",
        carry_replay,
        "--collect-all",
        "ttkbootstrap",
        "--collect-submodules",
        "serial",
        "--hidden-import",
        "tkinter.scrolledtext",
        str(PROJECT_ROOT / "main.py"),
    ]
    subprocess.run(command, check=True, cwd=str(PROJECT_ROOT))  # nosec B603


def _write_operator_note() -> None:
    NOTE_PATH.write_text(
        textwrap.dedent(
            f"""\
            CiscoAutoFlash — полевой комплект для Cisco 2960-X

            Как запускать
            - Открой `Запустить CiscoAutoFlash.bat`
            - Если bat не сработает, запусти `{APP_NAME}\\{APP_NAME}.exe`

            Что проверить на dev-машине до выезда
            - Запусти:
              `python C:\\PROJECT\\scripts\\pre_hardware_preflight.py`
            - Только после статуса READY переходите к живому smoke

            Что делать на месте
            - Подключись к Cisco 2960-X по Serial/USB
            - Пройди реальный smoke по шагам в приложении
            - Встроенная вкладка `Памятка` читает документы из `docs/pre_hardware`,
              они уже включены в bundle

            Где будут логи и артефакты
            - `%LOCALAPPDATA%\\CiscoAutoFlash\\logs\\`
            - `%LOCALAPPDATA%\\CiscoAutoFlash\\reports\\`
            - `%LOCALAPPDATA%\\CiscoAutoFlash\\transcripts\\`
            - `%LOCALAPPDATA%\\CiscoAutoFlash\\sessions\\<session_id>\\`

            Что привезти обратно
            - `session_bundle_*.zip` из `%LOCALAPPDATA%\\CiscoAutoFlash\\sessions\\<session_id>\\`
            - Если bundle не экспортировался:
              вся папка `%LOCALAPPDATA%\\CiscoAutoFlash\\sessions\\<session_id>\\`
            - При наличии: соответствующие log/report/transcript файлы
            - Для FAILED/STOPPED сессий ожидаются:
              `event_timeline.json` и `dashboard_snapshot_<state>.png`

            Что сделать потом на dev-машине
            - Запусти:
              `python C:\\PROJECT\\scripts\\triage_session_return.py `
              `"<bundle-or-session-folder>" --output-dir C:\\PROJECT\\triage_out`
            - Это соберёт короткую сводку по manifest/report/transcript/log без ручного копания
            - Сначала смотри в ней `failure_class`, `most likely cause`,
              `recommended next capture` и `inspect next`

            Что не входит в комплект
            - Прошивка/образ Cisco
            - MCP, тесты, demo automation, dev tooling
            """
        ),
        encoding="utf-8",
    )


def _write_launcher() -> None:
    LAUNCHER_PATH.write_text(
        textwrap.dedent(
            f"""\
            @echo off
            setlocal
            start "" "%~dp0{APP_NAME}\\{APP_NAME}.exe"
            """
        ),
        encoding="utf-8",
    )


def _validate_bundle() -> None:
    expected = [
        EXE_PATH,
        RUNBOOK_DIR / "pre_hardware_readiness_gate.md",
        RUNBOOK_DIR / "hardware_smoke_checklist.md",
        RUNBOOK_DIR / "expected_outcomes.md",
        RUNBOOK_DIR / "scenario_matrix.md",
        RUNBOOK_DIR / "legacy_parity_checklist.md",
        REPLAY_DIR / "stage2_firmware_missing.toml",
        REPLAY_DIR / "stage2_log_transcript_disagreement.toml",
        REPLAY_DIR / "stage3_artifact_incomplete.toml",
        REPLAY_DIR / "stage3_report_state_mismatch.toml",
        REPLAY_DIR / "stage3_verify.toml",
        REPLAY_DIR / "full_install_verify.toml",
    ]
    missing = [str(path) for path in expected if not path.exists()]
    if missing:
        raise RuntimeError(f"Bundle is missing expected files: {missing}")


def main() -> int:
    CARRY_ROOT.mkdir(parents=True, exist_ok=True)
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    _clean_previous_bundle()
    _build_bundle()
    _write_operator_note()
    _write_launcher()
    _validate_bundle()
    print(f"Field bundle ready: {BUNDLE_ROOT}")
    print(f"Launcher: {LAUNCHER_PATH}")
    print(f"Operator note: {NOTE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
