---
type: analysis
status: active
source_of_truth: repo
repo_refs:
  - C:\PROJECT\AGENTS.md
  - C:\PROJECT\OBSMEM\AGENTS.md
related:
  - "[[Knowledge_System_Model]]"
  - "[[CiscoAutoFlash]]"
last_verified: 2026-04-12
---

# Memory Lint Checklist

## Goal
Keep OBSMEM navigable for both humans and agents.

## Checks
1. Pages with stale `last_verified`
2. Broken or outdated `repo_refs`
3. Pages with no meaningful inbound or outbound links
4. Duplicate notes that should collapse into one canonical page
5. Decisions that should be marked `superseded`
6. Important repo changes that are not mirrored in `mirrors/`, `projects/`, or `decisions/`

## Use
- Run this after several substantial sessions or after major architectural changes.
- Update repo truth first when the lint reveals implementation drift.
