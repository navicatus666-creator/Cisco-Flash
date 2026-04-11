# Hardware Workflow

## Primary path
Serial-first real run for Cisco 2960-X.

## Pre-run
- Run:
  - `python C:\PROJECT\scripts\pre_hardware_preflight.py`
- Optional:
  - `python C:\PROJECT\scripts\pre_hardware_preflight.py --rebuild-bundle`
  - `python C:\PROJECT\scripts\pre_hardware_preflight.py --hardware-day-rehearsal`

## Main live sequence
1. Connect one active console path
2. Launch app
3. `Сканировать`
4. Validate selected target
5. `Этап 1: Сброс`
6. `Этап 2: Установка`
7. `Этап 3: Проверка`
8. Open session folder
9. Export session bundle

## Artifact rule
If only one thing comes back from the field, it should be the `session_bundle_*.zip`.

## Back on dev machine
Run:

```powershell
python C:\PROJECT\scripts\triage_session_return.py "<path-to-session_bundle.zip-or-session-folder>" --output-dir C:\PROJECT\triage_out
```

Read the generated summary before manual digging.

## Optional hidden SSH step
Only after serial success is stable enough:
- configure management IP over console
- enable SCP if needed: `ip scp server enable`
- run hidden helper:

```powershell
python C:\PROJECT\scripts\run_hidden_ssh_check.py --host <switch-ip> --username <user> --password <password> --secret <enable-secret>
```
---
type: project-note
status: active
source_of_truth: repo
repo_refs:
  - C:\PROJECT\docs\pre_hardware\first_hardware_run.md
  - C:\PROJECT\scripts\pre_hardware_preflight.py
  - C:\PROJECT\ciscoautoflash
last_verified: 2026-04-12
---
