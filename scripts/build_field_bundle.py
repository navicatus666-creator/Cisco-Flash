#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
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
PYTHON_EXE = Path(r"C:\Python314\python.exe")
EXE_PATH = BUNDLE_ROOT / f"{APP_NAME}.exe"
RUNBOOK_DIR = BUNDLE_ROOT / "_internal" / "docs" / "pre_hardware"
NOTE_PATH = CARRY_ROOT / "README_ПЕРЕД_ПОЛЕВЫМ_ТЕСТОМ.txt"
LAUNCHER_PATH = CARRY_ROOT / "Запустить CiscoAutoFlash.bat"


def _clean_previous_bundle() -> None:
    for path in (BUNDLE_ROOT, WORK_PATH, SPEC_PATH):
        if path.exists():
            shutil.rmtree(path)


def _build_bundle() -> None:
    carry_data = f"{DOCS_SOURCE}{os.pathsep}docs/pre_hardware"
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
        carry_data,
        "--collect-all",
        "ttkbootstrap",
        "--collect-submodules",
        "serial",
        "--hidden-import",
        "tkinter.scrolledtext",
        str(PROJECT_ROOT / "main.py"),
    ]
    subprocess.run(command, check=True, cwd=str(PROJECT_ROOT))


def _write_operator_note() -> None:
    NOTE_PATH.write_text(
        textwrap.dedent(
            f"""\
            CiscoAutoFlash — полевой комплект для Cisco 2960-X

            Как запускать
            - Открой `Запустить CiscoAutoFlash.bat`
            - Если bat не сработает, запусти `{APP_NAME}\\{APP_NAME}.exe`

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
            - Последнюю папку `%LOCALAPPDATA%\\CiscoAutoFlash\\sessions\\<session_id>\\`
            - `session_bundle_*.zip` из этой папки
            - При наличии: соответствующие log/report/transcript файлы

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
