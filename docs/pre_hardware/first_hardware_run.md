# First Hardware Run

Primary document for the first real Cisco 2960-X smoke pass.

## Goal

Validate the refactored Serial/USB workflow from source:
- `Сканировать`
- `Этап 1: Сброс`
- `Этап 2: Установка`
- `Этап 3: Проверка`

Current preferred execution path is the source run on the dev machine:

```powershell
python C:\PROJECT\main.py
```

The portable carry bundle path is optional and not part of the default next
hardware step until portable/release work resumes:

```powershell
C:\PROJECT\Возьму С Собой\Запустить CiscoAutoFlash.bat
```

## Pre-run gate

Before connecting the switch, confirm `pre_hardware_readiness_gate.md` is fully green.
Use this file as the execution runbook only after the software, demo, replay, and artifact gates are already closed.
Local preflight now explicitly includes:
- `python C:\PROJECT\scripts\pre_hardware_preflight.py`
- This one command runs the public pre-hardware validation gate: full `unittest` plus `python -m build`
- Optional final pass: `python C:\PROJECT\scripts\pre_hardware_preflight.py --rebuild-bundle`
- Hardware-day rehearsal pass: `python C:\PROJECT\scripts\pre_hardware_preflight.py --hardware-day-rehearsal`
- The dashboard now mirrors this through the read-only `Подготовка к железу` block: latest local gate, console/USB snapshot, Ethernet state, and the exact live-run / bring-back path.
- Bluetooth serial ports may be listed by Windows, but they are not valid Cisco console paths and must not make the hardware-day rehearsal green.

## Before connecting the switch

- Confirm runtime data is written to `%LOCALAPPDATA%\CiscoAutoFlash\`.
- Confirm the session folder is created under `%LOCALAPPDATA%\CiscoAutoFlash\sessions\...`.
- Confirm the expected firmware tar filename is known.
- Confirm all planned cables are available:
  - one primary console path: `RJ-45 console` or `USB mini-Type B console`
  - one backup console path
  - one `RJ45-RJ45` Ethernet cable for optional management/SSH after serial is stable
  - one USB flash drive with the firmware image
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
- Backup console path kept unplugged or idle
- Firmware filename
- USB slot in use: `usbflash0:` or `usbflash1:`
- Target selection mode: auto or manual override
- Prompt before the run: `Switch#`, `Switch>`, `switch:`, login, or no response

## Run steps

1. Connect exactly one console path as the active software path.
2. Keep the second console path only as fallback; do not use two console sessions in parallel.
3. Connect the Ethernet cable from the PC to a normal switch port, but do not start SSH work yet.
4. Launch the app from source and confirm only one instance opens.
5. Run `Сканировать`.
6. Confirm the selected target is correct in summary cards and preflight.
7. Confirm the `Подготовка к железу` block shows:
   - a green local gate
   - at least one non-Bluetooth console candidate
   - the expected serial-first live-run and bring-back flow
8. Confirm the operator card shows a concrete next step.
9. If the wrong target is selected, switch to the correct COM port manually before any stage.
10. Start `Этап 1: Сброс`.
11. Record Stage 1 duration and the prompt seen after reboot.
12. If Stage 1 fails, stop the run and capture artifacts immediately.
13. Start `Этап 2: Установка`.
14. Confirm the progress block remains understandable through install markers or quiet success.
15. Record Stage 2 duration, actual USB path used, and prompt after reboot.
16. If Stage 2 fails, stop the run and capture artifacts immediately.
17. Start `Этап 3: Проверка`.
18. Confirm the report is generated and visible through the diagnostics pane.
19. Open the session folder and export the session bundle.
20. Record Stage 3 duration and final dashboard state.
21. Before closing the app, confirm the final `session_bundle_*.zip` really exists in the current session folder.

## Optional hidden SSH pass after serial success

Only do this after the serial run is stable enough that you trust the switch state.

1. Through the console, configure a management IP and local SSH access.
2. If SCP will be tested, enable it on the switch: `ip scp server enable`.
3. Give the PC Ethernet adapter an IP in the same subnet.
4. Verify `ping` to the switch.
5. Run the hidden engineering helper:

```powershell
python C:\PROJECT\scripts\run_hidden_ssh_check.py --host <switch-ip> --username <user> --password <password> --secret <enable-secret>
```

6. If you also want to validate SCP upload helper readiness, add:

```powershell
--scp-file C:\path\to\firmware.tar
```

7. Keep the generated `ssh_check_summary.json` and `ssh_check_summary.md` from the helper session folder with the rest of the returned artifacts.

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
- `ssh_check_summary.json` / `.md` path if the hidden SSH helper was used
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
