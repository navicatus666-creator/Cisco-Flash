# Hardware Smoke Checklist

Primary run path: `first_hardware_run.md`.

## Before power-on
- The app starts either from the carry bundle launcher or from `python C:\PROJECT\main.py`.
- Runtime data is created in `%LOCALAPPDATA%\CiscoAutoFlash\`.
- Console cable, USB flash drive, and firmware tar name are known.
- The dashboard shows summary cards, preflight, operator card, diagnostics notebook, and session artifact paths.
- The local preflight gate is already green on the dev machine, including two consecutive passes of `python C:\PROJECT\scripts\run_demo_gui_smoke.py`.

## Serial/USB operator flow
- Launch the app and confirm only one instance opens.
- Run `Сканировать` and confirm the expected COM target is selected or manually selectable.
- Verify preflight shows selected target, firmware, profile, last scan, and session paths.
- Verify the operator card changes severity and next-step guidance when scan conditions change.
- Run `Этап 1: Сброс` and confirm prompt recovery after reboot.
- Run `Этап 2: Установка` and confirm install progress updates, quiet success handling, and USB path detection.
- Run `Этап 3: Проверка` and confirm report generation and final diagnostics state.
- Open the session folder and export the session bundle before closing the app.

## Collect after each run
- `log` file
- `transcript` file
- `report` file
- `manifest` file
- `session folder`
- `session bundle`
- screenshot of final dashboard state if a failure occurred

## First intake on the dev machine
- Bring back `session_bundle_*.zip` first; if that fails, bring back the whole session folder.
- Run `python C:\PROJECT\scripts\triage_session_return.py "<bundle-or-session-folder>" --output-dir C:\PROJECT\triage_out`.
- Read the triage summary before opening raw files by hand.
- Use its `failure_class`, `most likely cause`, `recommended next capture`, and `inspect next` fields to drive the first bug write-up.
