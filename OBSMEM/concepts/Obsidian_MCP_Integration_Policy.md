---
type: concept
status: active
aliases:
  - Obsidian MCP Policy
  - OBSMEM Obsidian Integration Policy
source_of_truth: repo
repo_refs:
  - C:\PROJECT\README.md
  - C:\PROJECT\AGENTS.md
  - C:\PROJECT\OBSMEM\README.md
  - C:\PROJECT\scripts\run_obsmem_chronicler.py
  - C:\PROJECT\scripts\run_obsmem_open.py
related:
  - "[[Knowledge_System_Model]]"
  - "[[Project_Chronicler_Workflow]]"
  - "[[Obsidian_MCP_Recommendations_2026-04-14]]"
last_verified: 2026-04-14
---

# Obsidian MCP Integration Policy

## Role
Defines how external Obsidian MCP ideas are adopted without breaking the repo-first OBSMEM model.

## Current decision
- The main `OBSMEM` vault remains file-first and chronicler-first.
- External write-capable Obsidian MCP servers are experimental and should not be connected directly to the main vault yet.
- All experimentation must start in a separate test vault.

## Adopted useful ideas
- test-vault-first policy for new Obsidian MCP plugins or servers
- explicit template usage for repeatable note structure
- quick-open helper for canonical pages
- source summaries for external Obsidian/MCP recommendations

## Operating rules
1. Main `OBSMEM` stays under the repo's existing AGENTS, lint, and chronicler workflow.
2. Any new Obsidian MCP plugin or server must be evaluated in a test vault first.
3. If a feature proves useful, prefer bringing the behavior into repo helpers or OBSMEM rules rather than adding uncontrolled plugin writes.
4. If a future direct Obsidian MCP integration is enabled for the main vault, document it in repo truth and update `docs/mcp_stack.md`.

## Quick-open flow
- `python C:\PROJECT\scripts\run_obsmem_open.py current-work`
- `python C:\PROJECT\scripts\run_obsmem_open.py daily`
- `python C:\PROJECT\scripts\run_obsmem_open.py log`
- `python C:\PROJECT\scripts\run_obsmem_open.py index`

## Test vault policy
- Use a separate vault for plugin/server experiments.
- Keep the main `OBSMEM` vault free from experimental write paths until behavior is validated.
- Promote only stable workflow improvements back into repo truth and the main vault.

## Related
- [[Project_Chronicler_Workflow]]
- [[Obsidian_MCP_Recommendations_2026-04-14]]
- [[Knowledge_System_Model]]

## Read next
- [[Current_Work]]
- [[Project_Chronicler_Workflow]]
