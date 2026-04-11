# Session Artifacts Flow

## Core idea
`CiscoAutoFlash` should be debugged from the session artifact model, not by manually hunting random files.

## Main artifact surfaces
- session folder
- session manifest
- session bundle
- log
- transcript
- report
- event timeline
- dashboard snapshot on `FAILED` / `STOPPED`

## Rules
- Session bundle is the primary diagnostic package.
- Manifest is the compact structured summary.
- Transcript is the raw device conversation.
- Log is the operator-level timeline.
- Report is the final verification surface.

## Return path
1. Bring back bundle or full session folder
2. Run `triage_session_return.py`
3. Read summary first
4. Only then inspect raw files manually

## Why this matters
This keeps post-run debugging deterministic and avoids losing time in ad hoc artifact collection.
