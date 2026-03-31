# First Hardware Run

Primary document for the first real Cisco 2960-X smoke pass.

## Goal

Validate the refactored Serial/USB workflow from source:
- `Сканировать`
- `Этап 1: Сброс`
- `Этап 2: Установка`
- `Этап 3: Проверка`

Preferred execution path on the work PC is the portable carry bundle:

```powershell
C:\PROJECT\Возьму С Собой\Запустить CiscoAutoFlash.bat
```

If the field PC is unavailable and you are running on the dev machine instead, source run is still valid:

```powershell
python C:\PROJECT\main.py
```

## Pre-run gate

Before connecting the switch, confirm `pre_hardware_readiness_gate.md` is fully green.
Use this file as the execution runbook only after the software, demo, replay, and artifact gates are already closed.
Local preflight now explicitly includes:
- `python C:\PROJECT\scripts\pre_hardware_preflight.py`
- This one command runs `check_mcp_runtime.py`, full `unittest`, `python -m build`, and `run_demo_gui_smoke.py`
- Optional final pass: `python C:\PROJECT\scripts\pre_hardware_preflight.py --rebuild-bundle`

## Before connecting the switch

- Confirm runtime data is written to `%LOCALAPPDATA%\CiscoAutoFlash\`.
- Confirm the session folder is created under `%LOCALAPPDATA%\CiscoAutoFlash\sessions\...`.
- Confirm the expected firmware tar filename is known.
- Confirm a console cable and USB flash drive are available.
- Keep these supporting docs nearby:
  - `hardware_smoke_checklist.md`
  - `pre_hardware_readiness_gate.md`
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
17. Before closing the app, confirm the final `session_bundle_*.zip` really exists in the current session folder.

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

## Quick failure classification

Use the first matching bucket before filling `bug_capture_template.md`:
- `firmware_missing`: operator card says the image file is missing, or the transcript/log shows `Firmware file not found` / `No such file` around `dir usbflash0:` or `dir usbflash1:`
- `timeout`: operator card says timeout, or Stage 2 stalls after `archive download-sw` without a clean completion
- `stopped`: the run was aborted by the operator and the final message says the operation was stopped
- `other`: anything else; attach the summary from `triage_session_return.py` and quote the final operator message verbatim

## Capture after every run

- `log` path
- `transcript` path
- `report` path
- `manifest` path
- `session bundle` path
- `event_timeline.json` path
- `session folder` path
- `dashboard_snapshot_<state>.png` path for `FAILED` / `STOPPED`
- final operator message and severity
- final stage durations from the report/manifest
- whether target selection was automatic or manual
- If you can only bring back one thing, bring back `session_bundle_*.zip`.
- If the bundle export fails, bring back the whole session folder plus matching log/report/transcript files.

## First triage step back on the dev machine

Before opening files manually, run:

```powershell
python C:\PROJECT\scripts\triage_session_return.py "<path-to-session_bundle.zip-or-session-folder>" --output-dir C:\PROJECT\triage_out
```

Use the generated summary as the first source of truth:
- `failure_class`
- `most likely cause`
- `recommended next capture`
- `inspect next`
- `issues` for missing/empty/inconsistent artifacts
- `timeline` summary for the last normalized event/state/stage
- Do not start manual file-by-file digging until you have read this summary once.

## Compare against expectations

- Use `expected_outcomes.md` for stage-by-stage success criteria.
- Use `scenario_matrix.md` for failure-mode coverage and what the UI should communicate.
- Use `legacy_parity_checklist.md` if behavior differs from `CiscoAutoFlash_GUI_Clean.py`.
- Use `bug_capture_template.md` to file any failure consistently.

## Back at the dev machine

Run the new intake tool on the returned artifacts before manual digging:

```powershell
python C:\PROJECT\scripts\triage_session_return.py "<path-to-session_bundle.zip-or-session-folder>" --output-dir C:\PROJECT\triage_out
```
