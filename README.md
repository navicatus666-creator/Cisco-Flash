# CiscoAutoFlash

[![CI Status](https://github.com/navicatus666-creator/Cisco-Flash/actions/workflows/checks.yml/badge.svg)](https://github.com/navicatus666-creator/Cisco-Flash/actions/workflows/checks.yml)
[![Python 3.14](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Ruff](https://img.shields.io/badge/Lint-Ruff-D7FF64?logo=ruff&logoColor=black)](https://github.com/astral-sh/ruff)
[![Bandit](https://img.shields.io/badge/Security-Bandit-F45D48)](https://bandit.readthedocs.io/)
[![Mypy](https://img.shields.io/badge/Type%20Check-Mypy-2A6DB2)](https://mypy-lang.org/)
[![UI ttkbootstrap](https://img.shields.io/badge/UI-ttkbootstrap-2772C8)](https://ttkbootstrap.readthedocs.io/)

CiscoAutoFlash is a Windows desktop utility for Cisco switch maintenance.

Current supported workflow:
- Cisco Catalyst 2960-X
- Serial/USB path
- Stage 1 reset, Stage 2 USB install, Stage 3 verification/report

Current limits:
- The refactored app under `ciscoautoflash/` is the active codebase.
- `CiscoAutoFlash_GUI_Clean.py` is legacy reference only.
- Backend-only SSH/SCP transport is integration-ready (`Netmiko`-based), but the desktop UI is still serial-first in V1.
- TFTP, SFTP, and additional Cisco families are out of scope until the serial V1 workflow is hardened.

## Stack

- Python 3.14
- `Pillow` for runtime screenshots and image helpers
- `ttkbootstrap` for the desktop UI
- `pyserial` for Serial/USB transport
- SSH/SCP backend stack: `Netmiko` (with its transitively installed SSH dependencies)
- Packaging: `PyInstaller` one-folder build (не в активном dev-цикле до hardware smoke)

## Run

```powershell
python C:\PROJECT\main.py
```

## Demo Mode

Dev-only demo playback is available directly in the desktop UI:

```powershell
python C:\PROJECT\main.py --demo
python C:\PROJECT\main.py --demo --demo-scenario stage2_install_success
```

Demo mode reuses replay fixtures under `replay_scenarios/`, writes artifacts into `%LOCALAPPDATA%\CiscoAutoFlash\demo\`, and exists for manual dry-runs without real hardware.

Each session now also keeps a per-session folder under `%LOCALAPPDATA%\CiscoAutoFlash\sessions\...` with:
- `session_manifest_*.json`
- `session_bundle_*.zip` after export

## Replay Harness

Internal pre-hardware replay lives under `ciscoautoflash/replay` with canned scenarios in `replay_scenarios/`.

Use it to regression-check prompt handling and stage flow without touching a real switch:

```powershell
python -m ciscoautoflash.replay scan_ready --show-events
python -m ciscoautoflash.replay stage2_install_success
```

This is a dev-only tool. The desktop demo mode is built on top of the same fixtures, but neither replaces real hardware smoke.

## Hidden SSH Backend

The repo now contains a hidden SSH/SCP backend for future work:
- transport: `ciscoautoflash/core/ssh_transport.py`
- current scope: hidden probe, hidden Stage 3 verify/report/transcript flow, and SCP upload helper
- current non-goal: no SSH transport selector in the desktop UI yet
- engineering helper after serial smoke: `python C:\PROJECT\scripts\run_hidden_ssh_check.py --host <switch-ip> --username <user> --password <password> --secret <enable-secret>`

Internal SSH target metadata contract:
- required: `host`, `username`, `password`
- optional: `secret`, `device_type`, `port`, `timeout`, `banner_timeout`, `auth_timeout`, `session_timeout`, `file_system`

SCP prerequisite on the switch:
- `ip scp server enable`

## Tests

Primary repo test command:

```powershell
python -m unittest discover -s C:\PROJECT\tests -v
```

Alternative runner after installing dev extras:

```powershell
python -m pytest
```

## Quality

```powershell
python -m ruff check .
python -m ruff format --check .
python -m mypy ciscoautoflash
python -m bandit -r ciscoautoflash
python -m deptry .
lint-imports
python -m pipdeptree --warn fail
python -m pip_audit --progress-spinner off
python -m vulture ciscoautoflash main.py tests vulture_whitelist.py
```

## Developer Helpers

Fast operational helpers now live under `ciscoautoflash.devtools` with thin wrappers in `scripts/`.

```powershell
python C:\PROJECT\scripts\run_project_bootstrap.py
python C:\PROJECT\scripts\run_obsmem_lint.py --vault C:\PROJECT\OBSMEM
python C:\PROJECT\scripts\run_obsmem_open.py current-work
python C:\PROJECT\scripts\run_obsmem_chronicler.py --once
python C:\PROJECT\scripts\run_obsmem_chronicler.py --watch --interval 120 --session-label "UI work"
python C:\PROJECT\scripts\run_obsmem_chronicler.py --event-type win --message "Fixed layout collision"
python C:\PROJECT\scripts\run_session_close.py
python C:\PROJECT\scripts\run_ui_smoke.py --close-ms 1500
```

Artifacts are written under `build\devtools\...`:
- `bootstrap\...` — repo/runtime truth-gate snapshot
- `memory_lint\...` — OBSMEM structure and drift report
- `obsmem_chronicler\...` — Current Work, daily-note, and event-stream sync reports
- `session_close\...` — close-readiness report and optional draft path
- `ui_smoke\...` — demo-mode auto-close smoke run

Notes:
- `run_obsmem_lint.py --strict` fails on `error` findings.
- `run_obsmem_open.py` is the quick-open bridge into Obsidian for `Current_Work`, today's daily note, `log`, and `index`.
- `run_obsmem_chronicler.py --watch` is the intended background session companion. It keeps `OBSMEM\mirrors\Current_Work.md`, the current daily note, and runtime events aligned while you work.
- Use manual chronicler events for durable wins, failures, discoveries, decisions, and next steps; implementation-relevant truth still has to go into repo files first.
- External Obsidian MCP plugins/servers should be trialed in a separate test vault before any direct write path is considered for the main `OBSMEM` vault.
- `run_session_close.py` is analysis-only by default; use `--write-obsmem-draft` or `--save-echovault` explicitly.
- `run_ui_smoke.py` uses demo mode plus the app-level smoke env hooks and should be the default fast gate after UI edits.

## Dependency Workflow

Source of truth:
- `pyproject.toml`
- `uv.lock`

Recommended sync/install flow:

```powershell
uv lock
uv sync --extra ssh --extra dev --extra build
```

Recommended dependency hygiene after changing versions:

```powershell
python -m deptry .
lint-imports
python -m pipdeptree --warn fail
python -m pip_audit --progress-spinner off
python -m unittest discover -s C:\PROJECT\tests -v
python -m build C:\PROJECT
```

`requirements.txt` is kept only as a minimal compatibility bootstrap for runtime installs. Do not treat it as the primary dependency definition.

Pre-commit local activation:

```powershell
pre-commit install
pre-commit run --all-files
```

## GitHub Automation

The repo now includes:
- [`C:\PROJECT\.github\dependabot.yml`](C:\PROJECT\.github\dependabot.yml) for weekly dependency PRs
- [`C:\PROJECT\.github\workflows\checks.yml`](C:\PROJECT\.github\workflows\checks.yml) for Windows-based quality gates on push to `main` and on pull request

## Build

Build оставлен в репозитории, но до hardware smoke не является частью повседневного цикла.


Install build dependencies:

```powershell
python -m pip install .[build]
```

Build the Windows one-folder distribution:

```powershell
pyinstaller C:\PROJECT\CiscoAutoFlash.spec --noconfirm
```

The packaged output is created under `dist\CiscoAutoFlash\`.

## Runtime Data

Runtime-writable data should live outside the repo in:

```text
%LOCALAPPDATA%\CiscoAutoFlash\
```

Expected runtime contents:
- `logs\`
- `reports\`
- `transcripts\`
- `sessions\<session_id>\`
- `settings\settings.json`

This keeps packaged builds writable on Windows and avoids writing operator data back into the repo root.

## Developer MCP State

Active Codex/MCP state currently lives under user-home paths:

```text
C:\Users\MySQL\.codex\
C:\Users\MySQL\.memory\
```

Keep MCP caches, indexes, and logs out of `C:\PROJECT\` so repository scans stay clean. This state is separate from operator runtime data in `%LOCALAPPDATA%\CiscoAutoFlash\`.

Canonical MCP upstream map and pin status:
- [`C:\PROJECT\docs\mcp_stack.md`](C:\PROJECT\docs\mcp_stack.md)
- Hosted MCPs `context7`, `exa`, and `fetch` are optional on this machine. Enable them only for sessions that actually need external docs or web discovery.

## Pre-Hardware Docs

Primary first-switch runbook:
- `first_hardware_run.md`

Supporting artifacts under `docs/pre_hardware/`:
- `hardware_smoke_checklist.md`
- `scenario_matrix.md`
- `expected_outcomes.md`
- `bug_capture_template.md`
- `legacy_parity_checklist.md`
- `portable_build_smoke_checklist.md` (appendix only, not the primary path before first hardware smoke)
