---
type: concept
status: active
aliases:
  - Chronicler Workflow
  - Project Chronicler
  - OBSMEM Chronicler
source_of_truth: repo
repo_refs:
  - C:\PROJECT\OBSMEM\AGENTS.md
  - C:\PROJECT\OBSMEM\README.md
  - C:\PROJECT\OBSMEM\index.md
  - C:\PROJECT\OBSMEM\mirrors\Current_Work.md
  - C:\PROJECT\OBSMEM\daily\README.md
  - C:\PROJECT\OBSMEM\templates\current-work.md
related:
  - "[[Knowledge_System_Model]]"
  - "[[Current_Work]]"
  - "[[CiscoAutoFlash]]"
  - "[[Hardware_Workflow]]"
last_verified: 2026-04-13
---

# Project Chronicler Workflow

## Role
The chronicler is the OBSMEM maintenance workflow that keeps the wiki current while work is happening.

## Purpose
- preserve a compact current-work snapshot
- turn session outcomes into durable wiki pages
- keep daily notes and the chronological log aligned with important events
- surface wins, losses, discoveries, and decisions in a readable form

## Inputs
- repo truth and active diffs
- current helper outputs
- manual session notes
- durable milestones worth preserving

## Outputs
- `[[Current_Work]]`
- `daily/YYYY-MM-DD.md`
- `log.md` for durable milestones
- updated hub pages when the session changes project understanding

## Operating rules
1. Repo truth stays primary.
2. Chronicler writes the short-form snapshot first.
3. Daily notes capture the narrative version of the same session.
4. Durable events get a log entry.
5. Long-form reasoning stays in OBSMEM, but implementation-relevant facts must still be promoted back to repo docs/code/tests.

## What to record
- wins
- failures
- discoveries
- fragile assumptions
- helper output worth remembering
- next actions

## What to avoid
- duplicating full repo truth
- turning OBSMEM into a second source of code behavior
- scattering one-off notes that do not link back to the hubs

## Writeback contract
- Keep `Current_Work` concise and current.
- Keep daily notes aligned with the same session summary.
- Append durable milestones to `log.md`.
- Update `index.md` when a new durable page or hub is added.
- Refresh `Current_Work` after meaningful git transitions; `run_session_close.py` treats stale branch/HEAD/commit/dirty-count data as a close blocker.

## Related
- [[Current_Work]]
- [[Knowledge_System_Model]]
- [[CiscoAutoFlash]]

## Read next
- [[Current_Work]]
- [[CiscoAutoFlash_Current_State]]
