# Pre-Hardware Readiness Gate

Use this gate before the first real Cisco 2960-X Serial/USB run.

## Scope

This gate is only for the current v1 path:
- Cisco 2960-X
- Serial/USB workflow
- execution via either:
  - primary: source run `python C:\PROJECT\main.py`
  - optional later: portable carry bundle on the field PC

Do not treat this gate as release approval, portable-build approval, or SSH
feature approval.

## Software gate

All of these must be true before touching real hardware:
- `python -m unittest discover -s C:\PROJECT\tests -v` is green
- `python -m build` succeeds
- `python C:\PROJECT\main.py --demo` opens cleanly for a short manual operator check
- if you plan to use the portable carry bundle, `portable_build_smoke_checklist.md` is green

## Demo and replay gate

All of these must be true before touching real hardware:
- core replay fixtures for `scan`, `stage1`, `stage2`, and `stage3` are green
- the full replay fixture covers `scan -> stage1 -> stage2 -> stage3` in one dry run
- demo mode can reach `Этап 3: Проверка` and produce:
  - report
  - transcript
  - manifest
  - session bundle
- visible dashboard actions are smoke-checked:
  - `Сканировать`
  - `Этап 1`
  - `Этап 2`
  - `Этап 3`
  - `Стоп`
  - diagnostics tabs
  - session artifact actions

## Advisory static-analysis gate

Track these before release work, but they are not the blocking gate for the first real hardware pass:
- `ruff check C:\PROJECT`
- `mypy C:\PROJECT\ciscoautoflash`
- `bandit -q -r C:\PROJECT\ciscoautoflash`

Current interpretation:
- software behavior, replay, packaging, and live demo smoke are the blocking criteria
- remaining static-analysis findings can be handled after the first real switch run if they do not affect the Serial/USB workflow

## Runtime and artifact gate

Confirm these on the local machine:
- runtime data stays under `%LOCALAPPDATA%\CiscoAutoFlash\`
- demo data stays under `%LOCALAPPDATA%\CiscoAutoFlash\demo\`
- real runs create a session folder under `%LOCALAPPDATA%\CiscoAutoFlash\sessions\...`
- the app can expose or export:
  - log
  - transcript
  - report
  - manifest
  - session bundle

## Open risks that are still acceptable before hardware

These risks are expected to remain open until the first real switch run:
- real COM-port timing and reconnect timing
- real prompt recovery after reboot
- real USB media behavior and path detection
- real install duration and quiet-success timing
- real operator interaction with the physical switch and cable state

## Do not proceed if any of these are true

- demo or replay gates are red
- report, transcript, manifest, or bundle generation is inconsistent
- session artifact actions point to the wrong paths
- the selected target cannot be trusted after scan
- the firmware tar name or USB path is still uncertain
- the only visible COM ports are Bluetooth serial ports instead of a real USB/RJ-45 Cisco console path

## Handoff to the first hardware run

When this gate is green:
- use `first_hardware_run.md` as the execution runbook
- keep `hardware_smoke_checklist.md` nearby during the run
- use `expected_outcomes.md`, `scenario_matrix.md`, and `bug_capture_template.md` to evaluate and record failures
- after bringing artifacts back, run `python C:\PROJECT\scripts\triage_session_return.py "<bundle-or-session-folder>" --output-dir C:\PROJECT\triage_out`
