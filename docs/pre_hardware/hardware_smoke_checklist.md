# Hardware Smoke Checklist

Primary run path: `first_hardware_run.md`.

## Before power-on
- The app starts either from the carry bundle launcher or from `python C:\PROJECT\main.py`.
- Runtime data is created in `%LOCALAPPDATA%\CiscoAutoFlash\`.
- One primary console path is chosen, the backup console path is available, and the firmware tar name is known.
- `RJ45-RJ45` Ethernet is available for optional management/SSH after the serial smoke is stable.
- The dashboard shows summary cards, preflight, operator card, diagnostics notebook, and session artifact paths.
- The local preflight gate is already green on the dev machine:
  `python C:\PROJECT\scripts\pre_hardware_preflight.py`

## Serial/USB operator flow
- Launch the app and confirm only one instance opens.
- Run `Сканировать` and confirm the expected COM target is selected or manually selectable.
- Verify preflight shows selected target, firmware, profile, last scan, and session paths.
- Verify the operator card changes severity and next-step guidance when scan conditions change.
- Run `Этап 1: Сброс` and confirm prompt recovery after reboot.
- Run `Этап 2: Установка` and confirm install progress updates, quiet success handling, and USB path detection.
- Run `Этап 3: Проверка` and confirm report generation and final diagnostics state.
- Open the session folder and export the session bundle before closing the app.

## Optional hidden SSH pass
- Do this only after the serial smoke is stable.
- Keep only one active console path in software; the second console path is fallback only.
- Configure management IP and local SSH through the console first.
- Verify `ping` before any hidden SSH check.
- Run `python C:\PROJECT\scripts\run_hidden_ssh_check.py --host <switch-ip> --username <user> --password <password> --secret <enable-secret>`.
- If SCP readiness is needed, add `--scp-file <path-to-firmware.tar>` after `ip scp server enable` is configured on the switch.

## Collect after each run
- `log` file
- `transcript` file
- `report` file
- `manifest` file
- `session folder`
- `session bundle`
- `event_timeline.json`
- `dashboard_snapshot_<state>.png` if a failure or stop occurred
- `ssh_check_summary.json` / `.md` if the hidden SSH helper was used

## First intake on the dev machine
- Bring back `session_bundle_*.zip` first; if that fails, bring back the whole session folder.
- Run `python C:\PROJECT\scripts\triage_session_return.py "<bundle-or-session-folder>" --output-dir C:\PROJECT\triage_out`.
- Read the triage summary before opening raw files by hand.
- Use its `failure_class`, `most likely cause`, `recommended next capture`, and `inspect next` fields to drive the first bug write-up.
- Use the `timeline` section to confirm the last normalized event/state before reading raw logs.
- Only after that move into the raw `manifest`, `report`, `transcript`, and `log`.
