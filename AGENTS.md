# context-mode — MANDATORY routing rules

You have context-mode MCP tools available. These rules are NOT optional — they protect your context window from flooding. A single unrouted command can dump 56 KB into context and waste the entire session. Codex Desktop does not automatically enforce context-mode routing for this project, so these instructions are the enforcement mechanism. Follow them strictly.

## BLOCKED commands — do NOT use these

### curl / wget — FORBIDDEN
Do NOT use `curl` or `wget` in any shell command. They dump raw HTTP responses directly into your context window.
Instead use:
- `mcp__context-mode__ctx_fetch_and_index(url, source)` to fetch and index web pages
- `mcp__context-mode__ctx_execute(language: "javascript", code: "const r = await fetch(...)")` to run HTTP calls in sandbox

### Inline HTTP — FORBIDDEN
Do NOT run inline HTTP calls via `node -e "fetch(..."`, `python -c "requests.get(..."`, or similar patterns. They bypass the sandbox and flood context.
Instead use:
- `mcp__context-mode__ctx_execute(language, code)` to run HTTP calls in sandbox — only stdout enters context

### Direct web fetching — FORBIDDEN
Do NOT use any direct URL fetching tool. Raw HTML can exceed 100 KB.
Instead use:
- `mcp__context-mode__ctx_fetch_and_index(url, source)` then `mcp__context-mode__ctx_search(queries)` to query the indexed content

## REDIRECTED tools — use sandbox equivalents

### Shell (>20 lines output)
Shell is ONLY for: `git`, `mkdir`, `rm`, `mv`, `cd`, `ls`, `npm install`, `pip install`, and other short-output commands.
For everything else, use:
- `mcp__context-mode__ctx_batch_execute(commands, queries)` — run multiple commands + search in ONE call
- `mcp__context-mode__ctx_execute(language: "shell", code: "...")` — run in sandbox, only stdout enters context

### File reading (for analysis)
If you are reading a file to **edit** it → reading is correct (edit needs content in context).
If you are reading to **analyze, explore, or summarize** → use `mcp__context-mode__ctx_execute_file(path, language, code)` instead. Only your printed summary enters context. The raw file stays in the sandbox.

### grep / search (large results)
Search results can flood context. Use `mcp__context-mode__ctx_execute(language: "shell", code: "grep ...")` to run searches in sandbox. Only your printed summary enters context.

## Tool selection hierarchy

1. **GATHER**: `mcp__context-mode__ctx_batch_execute(commands, queries)` — Primary tool. Runs all commands, auto-indexes output, returns search results. ONE call replaces 30+ individual calls.
2. **FOLLOW-UP**: `mcp__context-mode__ctx_search(queries: ["q1", "q2", ...])` — Query indexed content. Pass ALL questions as array in ONE call.
3. **PROCESSING**: `mcp__context-mode__ctx_execute(language, code)` | `mcp__context-mode__ctx_execute_file(path, language, code)` — Sandbox execution. Only stdout enters context.
4. **WEB**: `mcp__context-mode__ctx_fetch_and_index(url, source)` then `mcp__context-mode__ctx_search(queries)` — Fetch, chunk, index, query. Raw HTML never enters context.
5. **INDEX**: `mcp__context-mode__ctx_index(content, source)` — Store content in FTS5 knowledge base for later search.

## Session workflow defaults

- Start non-trivial reasoning with `mcp__sequential-thinking__sequentialthinking` before choosing deeper tool work, then use the rest of the MCP stack according to the task.
- At session start, load durable project context with `mcp__echovault__memory_context` and run a targeted `mcp__echovault__memory_search` before making assumptions about prior decisions or environment state.
- Treat `EchoVault` as the primary durable memory. Use `vector-memory` as a supplemental semantic baseline, not as the sole source of truth for recent project decisions.
- If `vector-memory` is used in a session, read its `cookbook(init)` guidance first, search before storing, and keep `EchoVault` as the canonical durable memory for recent project decisions.
- If `EchoVault` save is unhealthy or unavailable, checkpoint the same outcome into `vector-memory` before ending the session, and treat `vector-memory` as the temporary fallback until `EchoVault` is healthy again.
- For code work, prefer combining `tree-sitter`, `code-graph`, and `repo-map` instead of relying on raw grep alone. Use `tree-sitter` for symbols and file content, `code-graph` for dependency and caller/callee analysis, and `repo-map` for compact repository structure snapshots.
- If code-intelligence output looks stale, incomplete, or inconsistent with local files, trust direct repository reads first, then refresh/rebuild the relevant MCP index before making structural claims.
- For docs and external references, use `Context7` first for library and API documentation, `Exa` for broader current web discovery, and `context-mode` web routing for direct page fetch/index/search flows.
- Fallback order matters: if `Context7` is unavailable use `Exa`; if code-intel MCPs are unavailable use local repository inspection; if `github-mcp` is unavailable or auth-blocked use local `git` and `gh`.
- When multiple independent local reads or MCP checks are needed, use `multi_tool_use.parallel` to gather them in parallel instead of serial tool calls.
- Use multi-agents only when the user explicitly asks for delegation or parallel agent work, or when the task clearly has independent sidecar subtasks that do not block the immediate local step. Keep agent scopes narrow and write ownership disjoint.
- In multi-agent work, one primary agent owns the final merge. Delegated agents should stay read-only or own disjoint files, and each handoff must include touched files, commands or tests run, and unresolved assumptions.
- During Codex runtime instability or allocator crashes, prefer short sequential MCP steps over `request_user_input` bursts, broad status polling, or unnecessary fan-out until the session is stable again.
- Before ending any session with decisions, fixes, or environment changes, save the outcome to `EchoVault` so the next session inherits the working state.

## Output constraints

- Keep responses under 500 words.
- Write artifacts (code, configs, PRDs) to FILES — never return them as inline text. Return only: file path + 1-line description.
- When indexing content, use descriptive source labels so others can `search(source: "label")` later.

## ctx commands

| Command | Action |
|---------|--------|
| `ctx stats` | Call the `stats` MCP tool and display the full output verbatim |
| `ctx doctor` | Call the `doctor` MCP tool, run the returned shell command, display as checklist |
| `ctx upgrade` | Call the `upgrade` MCP tool, run the returned shell command, display as checklist |

## Project context — CiscoAutoFlash

- This repository contains the refactored CiscoAutoFlash desktop application in `ciscoautoflash/` and the legacy reference implementation in `CiscoAutoFlash_GUI_Clean.py`.
- Main desktop entrypoint: `python C:\PROJECT\main.py`
- Main test command: `python -m unittest discover -s C:\PROJECT\tests -v`
- Dependency source of truth: `pyproject.toml` + `uv.lock` (`requirements.txt` is compatibility-only)
- Current stack: Python 3.14, `Pillow`, `ttkbootstrap`, `pyserial`, `Netmiko` (SSH dependencies arrive transitively)
- Dependency hygiene gates: `deptry .`, `lint-imports`, `python -m pipdeptree --warn fail`, `python -m pip_audit --progress-spinner off`
- Current operator-facing workflow: Cisco 2960-X over Serial/USB
- Current dev UI is a Russian-first ttkbootstrap dashboard with preflight, operator status, target selection, notebook diagnostics, session artifact actions, and a dev-only `--demo` replay mode
- Backend-only SSH/SCP transport in `ciscoautoflash/core/ssh_transport.py` is integration-ready for hidden verify/report/transcript flow and SCP upload helper work, but the UI is still serial-first and does not expose SSH yet
- Internal SSH target metadata contract: required `host`, `username`, `password`; optional `secret`, `device_type`, `port`, `timeout`, `banner_timeout`, `auth_timeout`, `session_timeout`, `file_system`
- SCP prerequisite on the switch: `ip scp server enable`
- Internal replay harness exists in `ciscoautoflash/replay/` with canned fixtures in `replay_scenarios/`; use it for pre-hardware regression checks before touching a real switch
- Demo UI entrypoint for manual dry-runs without hardware: `python C:\PROJECT\main.py --demo`
- Demo artifacts must stay under `%LOCALAPPDATA%\CiscoAutoFlash\demo\`; do not mix them with normal operator runs
- Each runtime session now has a dedicated folder under `%LOCALAPPDATA%\CiscoAutoFlash\sessions\<session_id>\` with `session_manifest_*.json` and on-demand `session_bundle_*.zip`
- The dashboard exposes `Open session folder` and `Export session bundle`; use the bundle as the primary diagnostic package after failures instead of hand-collecting files
- Active Codex/MCP state currently lives in user-home paths under `C:\Users\MySQL\.codex\` and `C:\Users\MySQL\.memory\`; keep MCP caches and indexes out of `C:\PROJECT\` so repo scans stay clean
- Operator/runtime artifacts must still stay under `%LOCALAPPDATA%\CiscoAutoFlash\`; do not redirect desktop-app session data into Codex or MCP storage paths
- Supplemental Obsidian knowledge vault lives in `C:\PROJECT\OBSMEM\`; use it for long-form research, syntheses, and human-readable knowledge pages, but do not treat it as the source of truth over repo code/docs/tests
- Durable implementation truth still goes into repo docs/code/tests first; mirror only the stable synthesis into `C:\PROJECT\OBSMEM\`, and update its `index.md` and `log.md` when that wiki gains meaningful new pages
- Promotion rule: if knowledge changes project behavior, architecture contracts, test expectations, operator workflow, or implementation decisions, it must be written back into repo files; `OBSMEM` may keep the long-form reasoning, but it must not be the only place where implementation-relevant truth exists
- Session close protocol: before ending a substantial session, update repo truth first when needed, then mirror durable synthesis into `C:\PROJECT\OBSMEM\`, then save a concise continuity checkpoint to `EchoVault`; do not leave the latest project truth only in `vector-memory`
- Pre-hardware validation artifacts live in `docs/pre_hardware/` and should be kept in sync with the refactored workflow
- Primary first-switch runbook: `docs/pre_hardware/first_hardware_run.md`
- Additional Cisco families are still planned later; do not assume they already exist in code unless verified
- Prefer changing the refactored package under `ciscoautoflash/`; treat `CiscoAutoFlash_GUI_Clean.py` as legacy behavior reference unless the task explicitly targets it
- When architecture, commands, or operator workflow change, update this section so future sessions inherit the current state

