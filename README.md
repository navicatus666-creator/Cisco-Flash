# CiscoAutoFlash

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
- `ttkbootstrap` for the desktop UI
- `pyserial` for Serial/USB transport
- SSH/SCP backend stack: `Netmiko + Paramiko + ntc-templates`
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

Demo mode reuses replay fixtures under `replay_scenarios/`, writes artifacts into `%LOCALAPPDATA%\CiscoAutoFlash\demo\`, and exists only for click-smoke without real hardware.

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
pip-audit -r requirements.txt --progress-spinner off --timeout 10
python -m vulture ciscoautoflash main.py tests vulture_whitelist.py
```

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
