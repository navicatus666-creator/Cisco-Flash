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
last_verified: 2026-04-14
---

# Active Risks

## Current risks
- UI still needs final spacing/padding polish under real operator usage.
- Hidden SSH/SCP path exists in backend but is intentionally not exposed in UI yet.
- Real hardware smoke remains the decisive gate for the serial-first operator flow.
- `session_close` will keep flagging drift if repo/docs changes are not mirrored back into OBSMEM after substantial sessions.
- `Current_Work` remains freshness-sensitive and must be refreshed after meaningful git transitions, not trusted blindly.

## Handling rule
- If a risk changes implementation or operator workflow, promote it back into repo docs/tests/code.

## Related
- Model: [[Knowledge_System_Model]]
- Project: [[CiscoAutoFlash]]

## Read next
- [[Open_Architecture_Questions]]
- [[Hardware_Smoke_Gate]]
- [[CiscoAutoFlash_Current_State]]
