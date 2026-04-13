# MCP Stack Map

Current machine-level MCP stack for `CiscoAutoFlash`.

This document exists to keep the configured Codex MCP servers aligned with their
real upstream repositories and current pinned versions. Treat it as the
reference map for audits and upgrades.

## Source of truth

- Runtime config: [`C:\Users\MySQL\.codex\config.toml`](C:\Users\MySQL\.codex\config.toml)
- Project rules: [`C:\PROJECT\AGENTS.md`](C:\PROJECT\AGENTS.md)
- Global defaults: [`C:\Users\MySQL\.codex\AGENTS.md`](C:\Users\MySQL\.codex\AGENTS.md)

## Active upstreams

| MCP name | Upstream | Local runtime | Current pin / version | Status |
|---|---|---|---|---|
| `context-mode` | [mksglu/context-mode](https://github.com/mksglu/context-mode) | `npx context-mode --mcp` | `1.0.75` | current |
| `echovault` | [mraza007/echovault](https://github.com/mraza007/echovault) | `memory.exe mcp` | `0.4.0` | current |
| `repo-map` | [pdavis68/RepoMapper](https://github.com/pdavis68/RepoMapper) | local checkout | commit `3ef8914b3a2271695ac9e4b07ce1e8bf5a4c9be6` | current |
| `tree-sitter` | [jgravelle/jcodemunch-mcp](https://github.com/jgravelle/jcodemunch-mcp) | `uvx jcodemunch-mcp` | `1.41.0` | current pinned runtime |
| `code-graph` | [entrepeneur4lyf/code-graph-mcp](https://github.com/entrepeneur4lyf/code-graph-mcp) | `code-graph-mcp.exe` | `1.2.4` | current |
| `vector-memory` | [xsaven/vector-memory-mcp](https://github.com/xsaven/vector-memory-mcp) | `uv run ...\\vector-memory-mcp\\main.py` | `1.10.0` | current |

## Active hosted and managed MCPs

| MCP name | Upstream / provider | Local runtime | Current pin / version | Status |
|---|---|---|---|---|
| `fetch` | PyPI `mcp-server-fetch` | `uvx mcp-server-fetch` | `2025.4.7` | current |
| `context7` | hosted `mcp.context7.com` | remote MCP | app-managed | optional / currently disabled |
| `exa` | hosted `mcp.exa.ai` | remote MCP | app-managed | optional / currently disabled |
| `sequential-thinking` | npm `@modelcontextprotocol/server-sequential-thinking` | `npx` | `2025.12.18` | current |
| `github-mcp` | GitHub app / plugin-managed | connector + app tools | app-managed | enabled |

## Not our active upstreams

These repositories are related or similarly named, but they are not the current
source of the active MCP stack on this machine:

- [cyanheads/repo-map](https://github.com/cyanheads/repo-map)
- [FalkorDB/code-graph](https://github.com/FalkorDB/code-graph)
- [CodeGraphContext/CodeGraphContext](https://github.com/CodeGraphContext/CodeGraphContext)
- [CartographAI/mcp-server-codegraph](https://github.com/CartographAI/mcp-server-codegraph)
- [thijse/MemoryVectorStore](https://github.com/thijse/MemoryVectorStore)

## External Obsidian MCP references

These are useful research inputs for the `OBSMEM` workflow, but they are not
part of the active runtime stack on this machine:

- [Obsidian forum discussion on MCP servers](https://forum.obsidian.md/t/obsidian-mcp-servers-experiences-and-recommendations/99936/5)
- [bitbonsai/mcpvault](https://github.com/bitbonsai/mcpvault)
- [MCPVault homepage](https://mcpvault.org/)

Current project policy:
- assimilate useful ideas such as test-vault-first experiments, quick-open
  flows, and template-aware note handling;
- do not connect a write-capable external Obsidian MCP directly to the main
  `C:\PROJECT\OBSMEM` vault until it has been validated in a separate test
  vault and documented in repo truth.

## Current operational notes

- `context-mode`, `echovault`, `repo-map`, `code-graph`, and `vector-memory`
  are aligned with the configured stack and currently usable.
- `fetch`, `context7`, and `exa` are optional in global config. Keep them
  disabled by default for a tighter local-only coding profile, and enable them
  only for sessions that actually need external docs or web discovery.
- `tree-sitter` works through `jcodemunch-mcp` because the older Windows path
  through `@nendo/tree-sitter-mcp` required Visual Studio C++ build tools.
- Upstream currently shows `1.42.0`, but the latest version verified to resolve
  through `uvx` on this machine is `1.41.0`.
- `code-graph` is functional but can be sluggish on some direct calls.
- `repo-map` is configured and healthy, but in some sessions it may not surface
  as a separate callable tool in the active manifest.
- `echovault` is intentionally newer than the latest PyPI release because this
  machine uses the upstream git-based `0.4.0` line.

## Upgrade policy

- Safe to update in-place:
  - `context-mode`
  - `echovault`
  - `code-graph-mcp`
  - `vector-memory-mcp`
- Update with local verification:
  - `RepoMapper`
- Controlled upgrade only:
  - `jcodemunch-mcp`

`jcodemunch-mcp` should stay on the latest version that is verified to resolve
through `uvx` on this machine. If `1.42.0` starts resolving correctly later,
upgrade it only as a separate change:

1. bump the pin in [`C:\Users\MySQL\.codex\config.toml`](C:\Users\MySQL\.codex\config.toml)
2. restart Codex so the new MCP server is actually used
3. rerun:
   - `python C:\PROJECT\scripts\check_mcp_runtime.py`
   - `python C:\PROJECT\scripts\run_project_bootstrap.py`
   - `python C:\PROJECT\scripts\run_obsmem_lint.py --vault C:\PROJECT\OBSMEM --strict`
   - hosted smoke: `context7`, `exa`, `fetch`

## Read next

- [`C:\PROJECT\AGENTS.md`](C:\PROJECT\AGENTS.md)
- [`C:\PROJECT\README.md`](C:\PROJECT\README.md)
