# First Hardware Run

Primary document for the first real Cisco 2960-X smoke pass.

## Goal

Validate the refactored Serial/USB workflow from source:
- `Сканировать`
- `Этап 1: Сброс`
- `Этап 2: Установка`
- `Этап 3: Проверка`

Do not use the portable build for the first pass. Run from source:

```powershell
python C:\PROJECT\main.py
```

## Before connecting the switch

- Confirm runtime data is written to `%LOCALAPPDATA%\CiscoAutoFlash\`.
- Confirm the session folder is created under `%LOCALAPPDATA%\CiscoAutoFlash\sessions\...`.
- Confirm the expected firmware tar filename is known.
- Confirm a console cable and USB flash drive are available.
- Keep these supporting docs nearby:
  - `hardware_smoke_checklist.md`
  - `expected_outcomes.md`
  - `scenario_matrix.md`
  - `bug_capture_template.md`
  - `legacy_parity_checklist.md`

## Record before the run

- Date/time
- Operator
- Device model / serial
- Console COM port
- Firmware filename
- USB slot in use: `usbflash0:` or `usbflash1:`
- Target selection mode: auto or manual override
- Prompt before the run: `Switch#`, `Switch>`, `switch:`, login, or no response

## Run steps

1. Launch the app from source and confirm only one instance opens.
2. Run `Сканировать`.
3. Confirm the selected target is correct in summary cards and preflight.
4. Confirm the operator card shows a concrete next step.
5. If the wrong target is selected, switch to the correct COM port manually before any stage.
6. Start `Этап 1: Сброс`.
7. Record Stage 1 duration and the prompt seen after reboot.
8. If Stage 1 fails, stop the run and capture artifacts immediately.
9. Start `Этап 2: Установка`.
10. Confirm the progress block remains understandable through install markers or quiet success.
11. Record Stage 2 duration, actual USB path used, and prompt after reboot.
12. If Stage 2 fails, stop the run and capture artifacts immediately.
13. Start `Этап 3: Проверка`.
14. Confirm the report is generated and visible through the diagnostics pane.
15. Open the session folder and export the session bundle.
16. Record Stage 3 duration and final dashboard state.

## Stop conditions

Stop the run and capture artifacts immediately if any of these happen:
- no responding Cisco prompt after `Сканировать`
- `ROMMON` / `switch:`
- login or enable password required
- wrong COM target is selected and cannot be corrected
- firmware file is not found on USB
- reboot timeout after Stage 1 or Stage 2
- install timeout or obvious install error
- operator abort

## Capture after every run

- `log` path
- `transcript` path
- `report` path
- `manifest` path
- `session bundle` path
- screenshot of the final dashboard state on failure
- final operator message and severity
- final stage durations from the report/manifest
- whether target selection was automatic or manual

## Compare against expectations

- Use `expected_outcomes.md` for stage-by-stage success criteria.
- Use `scenario_matrix.md` for failure-mode coverage and what the UI should communicate.
- Use `legacy_parity_checklist.md` if behavior differs from `CiscoAutoFlash_GUI_Clean.py`.
- Use `bug_capture_template.md` to file any failure consistently.
