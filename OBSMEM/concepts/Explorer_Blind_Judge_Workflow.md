---
type: concept
status: active
aliases:
  - Explorer Blind Judge Workflow
  - Evidence Pack Workflow
  - Blind Judge Workflow
source_of_truth: repo
repo_refs:
  - C:\PROJECT\docs\evidence_workflow.md
  - C:\PROJECT\scripts\run_evidence_pack.py
  - C:\PROJECT\scripts\run_blind_judge.py
  - C:\PROJECT\ciscoautoflash\devtools\evidence_pack.py
  - C:\PROJECT\ciscoautoflash\devtools\blind_judge.py
related:
  - "[[CiscoAutoFlash]]"
  - "[[Knowledge_System_Model]]"
  - "[[Project_Chronicler_Workflow]]"
last_verified: 2026-04-14
---

# Explorer Blind Judge Workflow

## Role
This workflow separates evidence gathering from verdicts during high-stakes work.

## Core rule
`repo truth -> evidence pack -> blind judge -> repo writeback -> OBSMEM mirror -> EchoVault continuity`

## Explorer
Explorer work is allowed to:
- read repo truth
- inspect helper outputs
- gather logs and contradictions
- build candidate hypotheses
- write the structured evidence pack

## Blind Judge
Blind Judge work is allowed to:
- read only the evidence pack
- rank hypotheses
- report confidence
- choose the next action
- call out evidence gaps

It should not read repo code or docs directly for the final verdict step.

## Format policy
- `JSON` stays canonical for helper artifacts.
- `Markdown` stays the human-readable summary.
- `TOON` is only the prompt-facing compressed view for structured evidence arrays.

## Current helper entrypoints
- `python C:\PROJECT\scripts\run_evidence_pack.py`
- `python C:\PROJECT\scripts\run_blind_judge.py`

## Relationship to chronicler
The chronicler preserves the session narrative and wiki layer.
It does not replace the evidence pack or the blind judge verdict for high-stakes decisions.

## Related
- [[CiscoAutoFlash]]
- [[Project_Chronicler_Workflow]]
- [[Knowledge_System_Model]]

## Read next
- [[Project_Chronicler_Workflow]]
- [[Current_Work]]
- [[CiscoAutoFlash_Current_State]]
