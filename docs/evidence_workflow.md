# CiscoAutoFlash Evidence Workflow

`CiscoAutoFlash` now has a structured high-stakes reasoning layer on top of the
existing helper stack.

Core rule:

`repo truth -> evidence pack -> blind judge -> repo writeback -> OBSMEM mirror -> EchoVault continuity`

## Purpose

Use this workflow when a decision is expensive to get wrong:
- session close
- RCA and triage
- competing fix choice
- operator workflow verdicts
- hardware smoke readiness

The goal is to separate:
- **Explorer** work: gather facts and candidate hypotheses
- **Blind Judge** work: read only the structured evidence pack and return a compact verdict

## Helpers

Build the evidence pack:

```powershell
python C:\PROJECT\scripts\run_evidence_pack.py
python C:\PROJECT\scripts\run_evidence_pack.py --task-type repo-health
```

Run the blind judge:

```powershell
python C:\PROJECT\scripts\run_blind_judge.py
python C:\PROJECT\scripts\run_blind_judge.py --evidence-json C:\PROJECT\build\devtools\evidence_pack\<timestamp>\summary.json
```

## Artifacts

Evidence pack writes:
- `build\devtools\evidence_pack\<timestamp>\summary.json`
- `build\devtools\evidence_pack\<timestamp>\summary.md`
- `build\devtools\evidence_pack\<timestamp>\summary.toon`

Blind judge writes:
- `build\devtools\blind_judge\<timestamp>\summary.json`
- `build\devtools\blind_judge\<timestamp>\summary.md`
- `build\devtools\blind_judge\<timestamp>\summary.toon`

## Format policy

- `JSON` is canonical for helper/tooling artifacts.
- `Markdown` is the human-readable summary.
- `TOON` is prompt-facing compression for homogeneous evidence sections.

Do not replace repo docs, configs, or API payloads with `TOON`.

## Current scope

Current evidence pack focuses on repo/session-close style evidence:
- live git state
- live `session_close` analysis
- live `OBSMEM` lint
- latest bootstrap artifact
- latest UI smoke artifact
- structured hypotheses, supporting evidence, contradictions, and unknowns

The blind judge consumes only the evidence pack. It does not read repo code or
repo docs directly.

## Read next

- `C:\PROJECT\AGENTS.md`
- `C:\PROJECT\README.md`
- `C:\PROJECT\scripts\run_project_bootstrap.py`
- `C:\PROJECT\scripts\run_session_close.py`
