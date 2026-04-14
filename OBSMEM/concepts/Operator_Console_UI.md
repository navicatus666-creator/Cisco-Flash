---
type: concept
status: active
aliases:
  - Operator Console UI
source_of_truth: repo
repo_refs:
  - C:\PROJECT\docs\ui\operator_dashboard_references.md
  - C:\PROJECT\ciscoautoflash\ui\app.py
related:
  - "[[CiscoAutoFlash]]"
  - "[[CiscoAutoFlash_Current_State]]"
  - "[[Knowledge_System_Model]]"
last_verified: 2026-04-12
---

# Operator Console UI

## Pattern
Dense desktop console for operational work, not a marketing dashboard.

## Rules
- Table-first center of gravity
- Low header
- Strong primary area for the current task
- Log pane is secondary, but always available
- Do not let all cards have equal visual weight
- Full error text belongs in the main operator card or log, not in tiny summary surfaces
- No overlapping panels, no clipped primary actions, no fake empty whitespace

## Good references
- MobaXterm
- SecureCRT
- WinBox
- PRTG

## Anti-patterns
- web-style hero sections
- decorative KPI tiles with equal weight
- long repeated labels in compact spaces
- putting live workflow and artifacts on the same crowded screen

## Related
- Project: [[CiscoAutoFlash]]
- Current state: [[CiscoAutoFlash_Current_State]]
- Decision context: [[Knowledge_System_Model]]

## Read next
- [[CiscoAutoFlash_Current_State|CiscoAutoFlash Current State]]
- [[CiscoAutoFlash|CiscoAutoFlash]]
