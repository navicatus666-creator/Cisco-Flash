---
type: source-summary
status: active
aliases:
  - LLM Wiki Pattern
source_of_truth: repo
repo_refs:
  - C:\PROJECT\AGENTS.md
  - C:\PROJECT\OBSMEM\AGENTS.md
related:
  - "[[CiscoAutoFlash]]"
  - "[[Knowledge_System_Model]]"
last_verified: 2026-04-12
---

# LLM Wiki Pattern

## Source
Основано на тексте `LLM Wiki`, который описывает паттерн personal knowledge base с persistent markdown wiki между raw sources и ответами LLM.

## Why it matters
Идея полезна для нашей схемы, потому что разделяет:
- сырые источники;
- поддерживаемую LLM wiki;
- правила работы через `AGENTS.md`.

## Key takeaways
- Не отвечать каждый раз напрямую из сырых источников.
- Поддерживать накапливаемый wiki-layer как долговечный артефакт.
- Синтез, связи и contradictions должны жить в markdown, а не исчезать в чате.
- LLM должен не только искать, но и обслуживать knowledge base.

## Adaptation for CiscoAutoFlash
- Для `CiscoAutoFlash` каноническая истина всё равно остаётся в repo:
  - code
  - docs
  - tests
  - runbooks
- `OBSMEM` годится как дополнительный research/wiki слой.
- `EchoVault` хранит continuity между сессиями.
- `vector-memory` помогает semantic recall.

## Contradictions / caveats
- Нельзя переносить source of truth проекта во внешний vault.
- Нельзя подменять repo docs страницами в Obsidian.
- Wiki полезна только если обновляется дисциплинированно.

## Related
- Project: [[CiscoAutoFlash]]
- Model: [[Knowledge_System_Model]]

## Read next
- [[CiscoAutoFlash|CiscoAutoFlash]]
- [[Knowledge_System_Model|Knowledge System Model]]
- [[index]]
