---
type: decision
status: active
aliases:
  - Knowledge System Model Decision
source_of_truth: repo
repo_refs:
  - C:\PROJECT\AGENTS.md
  - C:\PROJECT\README.md
  - C:\PROJECT\docs
  - C:\PROJECT\tests
related:
  - "[[CiscoAutoFlash]]"
  - "[[Knowledge_System_Model]]"
  - "[[LLM_Wiki_Pattern]]"
last_verified: 2026-04-12
---

# Knowledge System Model Decision

## Context
`CiscoAutoFlash` now has several overlapping knowledge and memory layers:
- repo code/docs/tests
- `OBSMEM`
- `EchoVault`
- `vector-memory`

Without a clear role split, future sessions will duplicate, contradict, or overwrite knowledge in the wrong place.

## Decision
Use a four-layer model:

### 1. Repo = canonical project truth
- code
- tests
- runbooks
- README
- root `AGENTS.md`

### 2. OBSMEM = editable long-form wiki
Use for:
- research summaries
- syntheses
- comparisons
- stable decision pages
- conceptual maps

Do **not** use OBSMEM as the canonical source of truth for runtime behavior if that truth already exists in repo docs/code/tests.

### 3. EchoVault = operational continuity
Use for:
- what changed this session
- why it changed
- what to do next
- stable gotchas worth reusing

### 4. vector-memory = supplemental semantic recall
Use for:
- “where have we seen something similar?”
- fuzzy recall of related patterns or earlier discussions

## Tradeoffs
- Keeping OBSMEM inside the repo makes it easy to version and browse, but it increases the need for discipline.
- Some knowledge will exist both in repo docs and in OBSMEM, but the repo remains authoritative.

## Follow-up
- Always write implementation truth into repo first.
- Then mirror the durable synthesis into OBSMEM.
- Keep `index.md` and `log.md` updated when OBSMEM grows.
- Periodically lint OBSMEM for stale repo refs, duplicates, and superseded decisions.

## Related
- Project: [[CiscoAutoFlash]]
- Pattern source: [[LLM_Wiki_Pattern]]

## Read next
- [[Knowledge_System_Model]]
- [[CiscoAutoFlash]]
