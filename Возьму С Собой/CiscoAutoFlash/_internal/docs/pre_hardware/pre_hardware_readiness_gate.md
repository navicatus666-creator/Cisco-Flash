# Pre-Hardware Readiness Gate

Use this gate before the first real Cisco 2960-X Serial/USB run.

## Scope

This gate is only for the current v1 path:
- Cisco 2960-X
- Serial/USB workflow
- source run via `python C:\PROJECT\main.py`

Do not treat this gate as release approval or SSH feature approval.

## Software gate

All of these must be true before touching real hardware:
- `python -m unittest discover -s C:\PROJECT\tests -v` is green
- `ruff check .` is green
- `mypy ciscoautoflash` is green
- `bandit -q -r ciscoautoflash` is green
- `python -m build` succeeds
- `python C:\PROJECT\main.py --demo` starts cleanly

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

## Runtime and artifact gate

Confirm these on the local machine:
- runtime data stays under `%LOCALAPPDATA%\CiscoAutoFlash\`
- demo data stays under `%LOCALAPPDATA%\CiscoAutoFlash\demo\`
- source runs create a session folder under `%LOCALAPPDATA%\CiscoAutoFlash\sessions\...`
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

## Handoff to the first hardware run

When this gate is green:
- use `first_hardware_run.md` as the execution runbook
- keep `hardware_smoke_checklist.md` nearby during the run
- use `expected_outcomes.md`, `scenario_matrix.md`, and `bug_capture_template.md` to evaluate and record failures
