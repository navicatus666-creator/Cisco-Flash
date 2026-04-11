---
type: mirror
status: active
aliases:
  - Hardware Smoke Gate
source_of_truth: repo
repo_refs:
  - C:\PROJECT\docs\pre_hardware\first_hardware_run.md
  - C:\PROJECT\scripts\pre_hardware_preflight.py
  - C:\PROJECT\docs\pre_hardware
related:
  - "[[Knowledge_System_Model]]"
  - "[[CiscoAutoFlash]]"
  - "[[Hardware_Workflow]]"
last_verified: 2026-04-12
---

# Hardware Smoke Gate

## Gate summary
- Canonical runbook: `docs/pre_hardware/first_hardware_run.md`
- Canonical gate command: `python C:\PROJECT\scripts\pre_hardware_preflight.py`
- Diagnostic package: session bundle from `%LOCALAPPDATA%\CiscoAutoFlash\sessions\<session_id>\`

## Use
- This page is the short readiness bridge.
- Full operator truth still lives in repo runbooks and scripts.

## Related
- Model: [[Knowledge_System_Model]]
- Project: [[CiscoAutoFlash]]
- Workflow: [[Hardware_Workflow]]
