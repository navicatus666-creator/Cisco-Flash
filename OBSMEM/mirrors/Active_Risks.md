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
- Explorer-only reasoning is still a bias risk for RCA and close-readiness until the new evidence/judge helpers are wired into broader workflows.
- Chronicler/self-maintained OBSMEM files can create false freshness noise if repo-state comparison does not normalize them consistently.
- Rule/docs drift remains a real risk whenever AGENTS/README evolve faster than the short mirror pages that explain them.

## Handling rule
- If a risk changes implementation or operator workflow, promote it back into repo docs/tests/code.

## Related
- Model: [[Knowledge_System_Model]]
- Project: [[CiscoAutoFlash]]

## Read next
- [[Open_Architecture_Questions]]
- [[Hardware_Smoke_Gate]]
- [[CiscoAutoFlash_Current_State]]
