# Hardware Smoke Checklist

Primary run path: `first_hardware_run.md`.

## Before power-on
- The app starts from source via `python C:\PROJECT\main.py`.
- Runtime data is created in `%LOCALAPPDATA%\CiscoAutoFlash\`.
- Console cable, USB flash drive, and firmware tar name are known.
- The dashboard shows summary cards, preflight, operator card, diagnostics notebook, and session artifact paths.

## Serial/USB operator flow
- Launch the app and confirm only one instance opens.
- Run `Сканировать` and confirm the expected COM target is selected or manually selectable.
- Verify preflight shows selected target, firmware, profile, last scan, and session paths.
- Verify the operator card changes severity and next-step guidance when scan conditions change.
- Run `Этап 1: Сброс` and confirm prompt recovery after reboot.
- Run `Этап 2: Установка` and confirm install progress updates, quiet success handling, and USB path detection.
- Run `Этап 3: Проверка` and confirm report generation and final diagnostics state.

## Collect after each run
- `log` file
- `transcript` file
- `report` file
- screenshot of final dashboard state if a failure occurred
