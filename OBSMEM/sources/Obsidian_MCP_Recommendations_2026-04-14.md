---
type: source-summary
status: active
aliases:
  - Obsidian MCP Recommendations 2026-04-14
  - Obsidian MCP Sources Summary
source_of_truth: repo
repo_refs:
  - C:\PROJECT\OBSMEM\README.md
  - C:\PROJECT\OBSMEM\index.md
  - C:\PROJECT\README.md
related:
  - "[[Obsidian_MCP_Integration_Policy]]"
  - "[[Knowledge_System_Model]]"
  - "[[Project_Chronicler_Workflow]]"
last_verified: 2026-04-14
---

# Obsidian MCP Recommendations 2026-04-14

## Sources
- [Obsidian forum post: experiences and recommendations](https://forum.obsidian.md/t/obsidian-mcp-servers-experiences-and-recommendations/99936/5)
- [MCPVault](https://mcpvault.org/)

## Useful ideas extracted
- Use a separate test vault before enabling any write-capable Obsidian MCP against the main vault.
- Treat template execution as a formatting accelerator, not a replacement for repo-first truth.
- Add quick-open flows for canonical vault pages such as `Current_Work`, today's daily note, `log`, and `index`.
- Prefer local vault access, safe frontmatter handling, and no-cloud sync behavior.
- Track Obsidian/MCP integration choices as explicit policy instead of ad hoc experiments.

## Not adopted directly
- A second live write path into the main `OBSMEM` vault through an external Obsidian MCP server.
- Plugin-driven mutation of the production vault without first validating behavior in a test vault.

## Why
- The current chronicler already writes safely into `OBSMEM`.
- Repo code/docs/tests remain the implementation source of truth.
- A second write path is useful only after the current workflow has proven stable over multiple sessions.

## Related
- [[Obsidian_MCP_Integration_Policy]]
- [[Project_Chronicler_Workflow]]
- [[Knowledge_System_Model]]

## Read next
- [[Obsidian_MCP_Integration_Policy]]
- [[Current_Work]]
