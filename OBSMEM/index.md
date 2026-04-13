# OBSMEM Index

## Core
- [[README]] — как использовать vault
- [[AGENTS]] — правила для Codex и человека
- [[log]] — хронология изменений vault
- [[decisions/Knowledge_System_Model|Knowledge_System_Model decision]] — долговечное решение по memory model
- [[Knowledge_System_Model]] — canonical entrypoint в memory model

## Projects
- [[CiscoAutoFlash]] — главная project page
- [[CiscoAutoFlash_Current_State]] — canonical entrypoint к актуальному состоянию
- [[analyses/CiscoAutoFlash_Current_State_2026-04-12|CiscoAutoFlash_Current_State_2026-04-12]] — последний подробный snapshot
- [[Hardware_Workflow]] — serial-first реальный run и возврат артефактов

## Mirrors
- [[mirrors/CiscoAutoFlash_Current_State|CiscoAutoFlash_Current_State mirror]] — короткая карта текущего repo-state
- [[Active_Risks]] — активные риски и ограничения
- [[Open_Architecture_Questions]] — открытые архитектурные вопросы
- [[Hardware_Smoke_Gate]] — краткий статус готовности к реальному железу

## Concepts
- [[Operator_Console_UI]] — принципы UI/UX для плотной desktop-консоли
- [[Session_Artifacts_Flow]] — как session folder, manifest и bundle используются в процессе

## Sources
- [[LLM_Wiki_Pattern]] — как использовать persistent wiki-layer без подмены source of truth репозитория

## Knowledge lint
- [[analyses/Memory_Lint_Checklist|Memory_Lint_Checklist]] — как проверять wiki на stale refs, дубликаты и сироты

## Tooling
- `python C:\PROJECT\scripts\run_project_bootstrap.py` — единый bootstrap truth-gate
- `python C:\PROJECT\scripts\run_obsmem_lint.py --vault C:\PROJECT\OBSMEM` — структурный lint vault
- `python C:\PROJECT\scripts\run_session_close.py` — close-readiness и mirror-gap analysis
- `python C:\PROJECT\scripts\run_ui_smoke.py --close-ms 1500` — быстрый smoke для demo UI

## Working Folders
- [[inbox/README|inbox]] — входящие материалы
- [[raw/README|raw]] — сырые источники
- [[sources/README|sources]] — source summaries
- [[analyses/README|analyses]] — сравнения и syntheses
- [[decisions/README|decisions]] — долговечные решения
- [[daily/README|daily]] — заметки по дням
- [[mirrors/README|mirrors]] — краткие зеркала repo-state и открытых рисков
- [[templates/README|templates]] — шаблоны страниц

## Read next
- [[CiscoAutoFlash]]
- [[Knowledge_System_Model]]
- [[CiscoAutoFlash_Current_State]]
