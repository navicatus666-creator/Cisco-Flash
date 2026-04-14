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
12. Promotion rule: if knowledge changes project behavior, architecture contracts, test expectations, operator workflow, or implementation decisions, write it back into repo files; keep only the long-form reasoning here.
13. OBSMEM must not be the only place where implementation-relevant truth exists.
14. Chronicler workflow: keep `mirrors/Current_Work.md` as the living local short-form snapshot, keep `daily/` notes aligned with durable session events, and record durable milestones in `log.md`.
15. Chronicler outputs should preserve manual notes sections and keep `related`, `Read next`, and `last_verified` discipline intact.
16. External Obsidian MCP plugins or servers must be tested in a separate test vault before they are allowed to write into the main `C:\PROJECT\OBSMEM` vault.
17. Assimilate useful external Obsidian ideas into repo helpers, templates, and explicit policy pages first; do not add a second uncontrolled write path into the main vault.

Expected structure:
- `inbox/` — unsorted intake
- `raw/` — immutable raw sources
- `sources/` — summaries of raw sources
- `projects/` — project workspaces
- `concepts/` — stable ideas and reusable patterns
- `analyses/` — comparisons and deeper syntheses
- `decisions/` — durable decisions
- `mirrors/` — compressed mirrors of repo state, risks, gates, and open questions
- `daily/` — dated notes
- `templates/` — reusable note templates

Frontmatter contract for important pages:
- `type`: `analysis` | `concept` | `decision` | `project-note` | `source-summary` | `mirror`
- `status`: `active` | `draft` | `superseded` | `archived`
- `source_of_truth`: usually `repo`
- `repo_refs`: absolute repo paths or major repo anchors
- `last_verified`: `YYYY-MM-DD`

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
5. End each substantial session with: repo update if needed, OBSMEM mirror if useful, EchoVault checkpoint, and no repo-truth left only in `vector-memory`.

Memory lint:
1. Check pages with stale `last_verified`.
2. Check `repo_refs` that no longer match repo files.
3. Mark superseded decisions explicitly.
4. Collapse duplicates when two pages cover the same durable concept.
5. Add or update `mirrors/` pages when repo state changes materially.
6. Keep `Current_Work` fresh as a local live mirror and keep `daily` pages aligned with the latest durable session summary.
7. Keep Obsidian integration policy explicit: main vault stable, experimental vault separate, useful behavior promoted only after validation.
8. For high-stakes verdicts, prefer the Explorer -> Evidence Pack -> Blind Judge workflow over single-loop judgment; keep JSON canonical and TOON prompt-facing only.
