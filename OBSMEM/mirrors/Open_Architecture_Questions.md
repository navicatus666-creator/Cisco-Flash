---
type: mirror
status: active
aliases:
  - Open Architecture Questions
source_of_truth: repo
repo_refs:
  - C:\PROJECT\AGENTS.md
  - C:\PROJECT\docs
  - C:\PROJECT\ciscoautoflash
related:
  - "[[Knowledge_System_Model]]"
  - "[[CiscoAutoFlash]]"
  - "[[Active_Risks]]"
last_verified: 2026-04-14
---

# Open Architecture Questions

## Open questions
- When and how should hidden SSH/SCP become an operator-facing capability, if at all?
- What is the final operator-grade layout for the flash workspace after real-device testing?
- Which future Cisco families should be added after 2960-X is stable?
- Should bootstrap/session-close helper outputs stay local-only forever, or should part of them later feed CI/reporting summaries?
- Should `run_project_bootstrap.py` stay quality/runtime-only, or eventually gain an opt-in OBSMEM strict-lint mode for knowledge-heavy sessions?
- When should the standalone `evidence_pack` and `blind_judge` helpers be integrated into `session_close`, hardware triage, or PR-review flows?
- Which parts of the evidence pack should stay JSON-only, and which should expose TOON by default for LLM-facing review steps?
- Should helper-produced freshness logic compare against raw git dirtiness or a normalized repo view that excludes chronicler-managed mirror files?
- Should repo health and mirror freshness eventually get one shared verdict contract instead of separate helper summaries plus blind-judge review?

## Rule
- Keep speculative reasoning here.
- Promote settled answers into repo truth and durable decision pages.

## Related
- Model: [[Knowledge_System_Model]]
- Project: [[CiscoAutoFlash]]
- Risks: [[Active_Risks]]

## Read next
- [[Active_Risks]]
- [[Hardware_Smoke_Gate]]
- [[CiscoAutoFlash_Current_State]]
