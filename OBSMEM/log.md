# OBSMEM Log

## [2026-04-12] init | Vault bootstrap
- Создан локальный Obsidian vault `C:\PROJECT\OBSMEM`.
- Добавлены структура папок, правила в `AGENTS.md`, индекс, лог и стартовые шаблоны.
- Зафиксировано правило: `OBSMEM` дополняет repo, но не заменяет source of truth в `C:\PROJECT`.
- Добавлена стартовая source-summary страница по паттерну `LLM Wiki`.

## [2026-04-12] sync | Repo truth mirrored into OBSMEM
- Добавлена явная модель памяти и ролей между repo, OBSMEM, EchoVault и vector-memory.
- Добавлены страницы о текущем состоянии `CiscoAutoFlash`, hardware workflow и session artifacts flow.
- `projects/CiscoAutoFlash.md` обновлена как главный проектный entrypoint для vault.

## [2026-04-12] harden | Promotion, frontmatter, mirrors, and lint rules
- Добавлены `promotion rule` и `session close protocol` в repo и OBSMEM AGENTS.
- Для ключевых страниц и шаблонов введён frontmatter-контракт с `type`, `status`, `source_of_truth`, `repo_refs`, `last_verified`.
- Добавлен слой `mirrors/` для кратких карт repo-state, рисков, открытых вопросов и hardware gate.
- Зафиксирован короткий `memory lint` workflow для проверки stale refs, superseded решений и дубликатов.

## [2026-04-12] link | Hub pages and canonical related links
- Исправлен frontmatter у ключевых страниц: теперь он находится вверху файла, а не внизу.
- Добавлены `related`-связи и `Read next` секции для основных project/concept/analysis/source pages.
- Появились canonical hub pages для `Knowledge System Model` и `CiscoAutoFlash Current State`.
- Добавлен `Memory Lint Checklist` как отдельная точка входа для проверки связности vault.

## [2026-04-12] ops | Helper commands and lint discipline
- Добавлены developer helper-команды для repo bootstrap, OBSMEM lint, session close и UI smoke.
- `OBSMEM` страницы mirrors и `Memory_Lint_Checklist` доведены до единого `related` / `Read next` формата.
- Устранён дублирующий canonical topic между concept и decision-страницами `Knowledge System Model`.
- Vault и repo docs теперь описывают helpers как operational layer поверх repo-first workflow.

## [2026-04-14] obsidian | External MCP ideas assimilated safely
- Добавлен `run_obsmem_open.py` как quick-open bridge для `Current_Work`, daily note, `log` и `index`.
- Зафиксирована policy page `Obsidian_MCP_Integration_Policy` с правилом: write-capable Obsidian MCP plugins/servers сначала идут в отдельный test vault.
- Добавлена source-summary страница по внешним Obsidian MCP рекомендациям и `MCPVault`.
- Полезные идеи ассимилированы в текущий repo-first workflow без добавления второго live write-path в основной `OBSMEM`.

## [2026-04-14] evidence | Explorer and blind-judge layer added
- Добавлены `run_evidence_pack.py` и `run_blind_judge.py` как новый high-stakes helper-слой поверх existing devtools.
- `JSON` оставлен каноническим helper-форматом, а `TOON` добавлен только как prompt-facing compression для однородных evidence sections.
- В `OBSMEM` добавлена concept page `Explorer_Blind_Judge_Workflow` и index/tooling navigation обновлён под новый workflow.
