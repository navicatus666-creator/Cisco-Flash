---
type: mirror
status: active
source_of_truth: repo
repo_refs:
  - C:\PROJECT\AGENTS.md
  - C:\PROJECT\README.md
related:
  - "[[CiscoAutoFlash]]"
  - "[[Knowledge_System_Model]]"
  - "[[CiscoAutoFlash_Current_State]]"
last_verified: 2026-04-13
---

# OBSMEM

Локальный Obsidian vault для `CiscoAutoFlash` и связанных инженерных заметок.

Назначение:
- хранить исследования, syntheses, решения и заметки, которые неудобно держать только в чате;
- не заменять код, тесты и docs в репозитории;
- работать вместе с Codex, EchoVault и vector-memory.

Правило истины:
- код, tests, docs и runbooks в `C:\PROJECT` остаются source of truth для проекта;
- `OBSMEM` — это knowledge layer для исследований, связей и long-form заметок;
- `EchoVault` хранит continuity между сессиями;
- `vector-memory` остаётся только дополнительным semantic recall.

Старт:
1. Открой эту папку как vault в Obsidian.
2. Прочитай [[AGENTS]].
3. Начинай навигацию с [[index]].
4. Хронология изменений ведётся в [[log]].

## Canonical hubs
- [[CiscoAutoFlash]]
- [[Knowledge_System_Model]]
- [[CiscoAutoFlash_Current_State]]
- [[Current_Work]]
- [[Project_Chronicler_Workflow]]

## Operational helpers
- Repo bootstrap: `python C:\PROJECT\scripts\run_project_bootstrap.py`
- OBSMEM lint: `python C:\PROJECT\scripts\run_obsmem_lint.py --vault C:\PROJECT\OBSMEM`
- Session close analysis: `python C:\PROJECT\scripts\run_session_close.py`
- UI smoke: `python C:\PROJECT\scripts\run_ui_smoke.py --close-ms 1500`

## Chronicler workflow
- `Current_Work` is the living session snapshot that the chronicler keeps up to date.
- `daily/` notes capture dated narrative from the same durable session summary.
- `log.md` stays the chronological backbone for important milestones and durable events.
- Use the chronicler concept page for the exact writeback contract: [[Project_Chronicler_Workflow]].

These commands write reports into `C:\PROJECT\build\devtools\...`. They do not replace repo truth; they enforce the existing repo-first and promotion rules.

## Read next
- [[index]]
- [[analyses/Memory_Lint_Checklist|Memory_Lint_Checklist]]
- [[Current_Work]]
