---
type: analysis
status: active
source_of_truth: repo
repo_refs:
  - C:\PROJECT\README.md
  - C:\PROJECT\AGENTS.md
  - C:\PROJECT\docs
  - C:\PROJECT\tests
  - C:\PROJECT\ciscoautoflash
related:
  - "[[CiscoAutoFlash]]"
  - "[[CiscoAutoFlash_Current_State]]"
  - "[[Hardware_Workflow]]"
  - "[[Operator_Console_UI]]"
  - "[[Knowledge_System_Model]]"
last_verified: 2026-04-12
---

# CiscoAutoFlash Current State — 2026-04-12

## Product
Windows desktop utility for Cisco switch maintenance.

## Supported workflow
- Cisco Catalyst 2960-X
- Serial/USB path
- Stage 1 reset
- Stage 2 USB install
- Stage 3 verification/report

## Current UI state
- Russian-first ttkbootstrap operator dashboard
- Two main workspaces:
  - `Прошивка`
  - `Состояние и артефакты`
- Flash workspace is table-first and execution-first
- Metrics/artifacts workspace holds readiness, context, and session files
- Diagnostics on the flash tab are limited to:
  - `Журнал`
  - `Памятка`

## Current engineering shape
- Active refactored app: `ciscoautoflash/`
- Legacy reference only: `CiscoAutoFlash_GUI_Clean.py`
- Hidden SSH/SCP backend exists but is not exposed in UI
- Demo replay mode exists for dry runs

## Tooling and quality
- Python 3.14
- `ttkbootstrap`
- `Pillow`
- `pyserial`
- `Netmiko` backend stack
- Quality gates:
  - `ruff`
  - `mypy`
  - `bandit`
  - `deptry`
  - `import-linter`
  - `pipdeptree`
  - `pip-audit`
  - `unittest`
  - `build`

## CI state
- GitHub Actions `Checks` on `main` is green
- Dependabot is configured but PRs are optional, not mandatory for current work

## Runtime/artifacts model
- Operator runtime data lives in `%LOCALAPPDATA%\\CiscoAutoFlash\\`
- Session folder per run
- `session_manifest_*.json`
- `session_bundle_*.zip`
- `triage_session_return.py` is the first intake tool after a real run

## Main current risk
UI/UX still needs final polish in spacing, density, and visual hierarchy, but structure is now much healthier than the old one-screen overload.

## Related
- Project: [[CiscoAutoFlash]]
- UI concept: [[Operator Console UI]]
- Workflow: [[Hardware Workflow]]
- Model: [[Knowledge System Model]]

## Read next
- [[CiscoAutoFlash_Current_State|CiscoAutoFlash Current State]]
- [[Hardware_Workflow|Hardware Workflow]]
- [[Active_Risks|Active Risks]]
