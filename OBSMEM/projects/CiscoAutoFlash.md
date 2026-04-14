---
type: project-note
status: active
aliases:
  - CiscoAutoFlash
source_of_truth: repo
repo_refs:
  - C:\PROJECT\README.md
  - C:\PROJECT\AGENTS.md
  - C:\PROJECT\docs
  - C:\PROJECT\tests
  - C:\PROJECT\ciscoautoflash
related:
  - "[[Knowledge_System_Model]]"
  - "[[CiscoAutoFlash_Current_State]]"
  - "[[Hardware_Workflow]]"
  - "[[Operator_Console_UI]]"
last_verified: 2026-04-13
---

# CiscoAutoFlash

## Role
Desktop utility for Cisco 2960-X flashing over Serial/USB with a Russian-first operator dashboard.

## Canonical Truth
- Code: [`C:\PROJECT\ciscoautoflash`](C:\PROJECT\ciscoautoflash)
- Docs: [`C:\PROJECT\docs`](C:\PROJECT\docs)
- Tests: [`C:\PROJECT\tests`](C:\PROJECT\tests)
- Project instructions: [`C:\PROJECT\AGENTS.md`](C:\PROJECT\AGENTS.md)

## Current Focus
- UI/UX polishing for a one-screen operator console
- table-first flashing workspace
- metrics/artifacts workspace kept separate from live execution
- OBSMEM chronicler workflow for current work, daily notes, and durable milestone capture

## Current Product Shape
- Supported now:
  - Cisco Catalyst 2960-X
  - Serial/USB path
  - Stage 1 reset
  - Stage 2 USB install
  - Stage 3 verification/report
- Not exposed in UI yet:
  - hidden SSH/SCP backend
- Dev-only:
  - `--demo` replay mode using fixtures from `replay_scenarios/`

## Current Architecture Notes
- Flash tab = live operator workflow
- Metrics/artifacts tab = context, readiness, artifact actions
- EchoVault = continuity between sessions
- vector-memory = supplemental semantic recall
- OBSMEM = long-form research and synthesis
- Current_Work = living short-form session snapshot
- Chronicler workflow = the OBSMEM process that keeps Current_Work and daily notes aligned

## Current Knowledge Model
- Repo = truth
- OBSMEM = editable long-form wiki
- EchoVault = continuity between sessions
- vector-memory = fuzzy semantic recall

See also:
- [Knowledge System Model](C:\PROJECT\OBSMEM\decisions\Knowledge_System_Model.md)
- [CiscoAutoFlash Current State](C:\PROJECT\OBSMEM\analyses\CiscoAutoFlash_Current_State_2026-04-12.md)
- [Hardware Workflow](C:\PROJECT\OBSMEM\projects\Hardware_Workflow.md)

## Useful Repo Pages
- [`C:\PROJECT\docs\ui\operator_dashboard_references.md`](C:\PROJECT\docs\ui\operator_dashboard_references.md)
- [`C:\PROJECT\docs\pre_hardware\first_hardware_run.md`](C:\PROJECT\docs\pre_hardware\first_hardware_run.md)

## Open Threads
- Final polish of spacing/padding in the flash tab
- Future hidden SSH/SCP exposure only after serial-first phase is stable
- Chronicler writeback discipline: keep durable outcomes mirrored into the wiki without duplicating repo truth

## Related
- Model: [[Knowledge System Model]]
- Current state: [[CiscoAutoFlash Current State]]
- Workflow: [[Hardware Workflow]]
- UI concept: [[Operator Console UI]]

## Read next
- [[CiscoAutoFlash_Current_State|CiscoAutoFlash Current State]]
- [[Knowledge_System_Model|Knowledge System Model]]
- [[Current_Work|Current Work]]
- [[Project_Chronicler_Workflow|Project Chronicler Workflow]]
