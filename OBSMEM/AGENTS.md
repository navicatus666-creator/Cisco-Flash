# OBSMEM AGENTS

Read this file first when working inside `C:\PROJECT\OBSMEM`.

Rules:
1. `C:\PROJECT` code, docs, tests, and runbooks are the project source of truth.
2. `OBSMEM` is a supplemental wiki for research, synthesis, decisions, and knowledge maintenance.
3. Raw materials under `raw/` are immutable.
4. Prefer updating existing pages over creating duplicates.
5. Every non-trivial synthesis should update [index.md](C:\PROJECT\OBSMEM\index.md) and append a line to [log.md](C:\PROJECT\OBSMEM\log.md).
6. Put project-specific current state in repo docs first; mirror only the useful summary here.
7. Use short, explicit page titles and strong cross-links.
8. Keep pages markdown-first and Obsidian-friendly.
9. When a repo decision is stable and worth remembering, create or update a durable page in `decisions/` or `projects/`.
10. When new research arrives, summarize it in `sources/` or `analyses/`, not in `projects/`.
11. When the question is about implementation truth, read repo files first and only then consult OBSMEM.

Expected structure:
- `inbox/` — unsorted intake
- `raw/` — immutable raw sources
- `sources/` — summaries of raw sources
- `projects/` — project workspaces
- `concepts/` — stable ideas and reusable patterns
- `analyses/` — comparisons and deeper syntheses
- `decisions/` — durable decisions
- `daily/` — dated notes
- `templates/` — reusable note templates

Memory model:
- Repo docs/code/tests = truth
- EchoVault = session continuity
- vector-memory = semantic recall
- OBSMEM = editable long-form wiki

Operational workflow:
1. Read repo truth first.
2. Make or verify the code/doc change in `C:\PROJECT`.
3. Mirror only the durable synthesis into `OBSMEM`.
4. Update [index.md](C:\PROJECT\OBSMEM\index.md) and [log.md](C:\PROJECT\OBSMEM\log.md).
