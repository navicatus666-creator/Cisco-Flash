---
type: mirror
status: active
aliases:
  - Active Risks
source_of_truth: repo
repo_refs:
  - C:\PROJECT\AGENTS.md
  - C:\PROJECT\docs\pre_hardware\first_hardware_run.md
  - C:\PROJECT\ciscoautoflash\ui\app.py
related:
  - "[[Knowledge_System_Model]]"
  - "[[CiscoAutoFlash]]"
last_verified: 2026-04-12
---

# Active Risks

## Current risks
- UI still needs final spacing/padding polish under real operator usage.
- Hidden SSH/SCP path exists in backend but is intentionally not exposed in UI yet.
- Real hardware smoke remains the decisive gate for the serial-first operator flow.

## Handling rule
- If a risk changes implementation or operator workflow, promote it back into repo docs/tests/code.

## Related
- Model: [[Knowledge_System_Model]]
- Project: [[CiscoAutoFlash]]
