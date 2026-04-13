---
type: mirror
status: active
source_of_truth: repo
repo_refs:
  - C:\PROJECT\README.md
  - C:\PROJECT\AGENTS.md
  - C:\PROJECT\docs
  - C:\PROJECT\tests
  - C:\PROJECT\ciscoautoflash
related:
  - "[[CiscoAutoFlash]]"
  - "[[Knowledge_System_Model]]"
  - "[[CiscoAutoFlash_Current_State]]"
last_verified: 2026-04-12
---

# CiscoAutoFlash Current State Mirror

## Current truth
- Product: Windows desktop utility for Cisco 2960-X flashing over Serial/USB.
- UI: Russian-first ttkbootstrap operator console with split workspaces.
- Code truth: `ciscoautoflash/`, `docs/`, `tests/`, root `AGENTS.md`.

## Active focus
- UI/UX polishing for readability and fit.
- Serial-first hardware workflow.
- Hidden SSH/SCP backend remains non-operator-facing.
- Developer helper layer now includes bootstrap, OBSMEM lint, session close, and UI smoke commands under `scripts/`.
- Repo-quality and helper validation are green after the infrastructure helper pass.

## Notes
- Use this page as the short repo-state bridge.
- Keep deeper narrative in `projects/` and `analyses/`.
- Treat this page as the shortest repo-state mirror after tooling or workflow changes.

## Related
- Project: [[CiscoAutoFlash]]
- Memory model: [[Knowledge_System_Model]]
- Detailed analysis: [[CiscoAutoFlash_Current_State]]

## Read next
- [[CiscoAutoFlash_Current_State]]
- [[Active_Risks]]
- [[Open_Architecture_Questions]]
