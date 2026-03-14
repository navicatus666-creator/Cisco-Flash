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
- Current stack: Python 3.14, `ttkbootstrap`, `pyserial`, `Netmiko`, `Paramiko`, `ntc-templates`
- Current operator-facing workflow: Cisco 2960-X over Serial/USB
- Current dev UI is a Russian-first ttkbootstrap dashboard with preflight, operator status, target selection, notebook diagnostics, and session artifact actions
- Backend-only SSH/SCP transport in `ciscoautoflash/core/ssh_transport.py` is integration-ready for hidden verify/report/transcript flow and SCP upload helper work, but the UI is still serial-first and does not expose SSH yet
- Internal SSH target metadata contract: required `host`, `username`, `password`; optional `secret`, `device_type`, `port`, `timeout`, `banner_timeout`, `auth_timeout`, `session_timeout`, `file_system`
- SCP prerequisite on the switch: `ip scp server enable`
- Internal replay harness exists in `ciscoautoflash/replay/` with canned fixtures in `replay_scenarios/`; use it for pre-hardware regression checks before touching a real switch
- Pre-hardware validation artifacts live in `docs/pre_hardware/` and should be kept in sync with the refactored workflow
- Primary first-switch runbook: `docs/pre_hardware/first_hardware_run.md`
- Additional Cisco families are still planned later; do not assume they already exist in code unless verified
- Prefer changing the refactored package under `ciscoautoflash/`; treat `CiscoAutoFlash_GUI_Clean.py` as legacy behavior reference unless the task explicitly targets it
- When architecture, commands, or operator workflow change, update this section so future sessions inherit the current state

