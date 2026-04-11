# CiscoAutoFlash Operator Dashboard References

## Goal

Build a fixed desktop operator console for Cisco switch flashing that stays stable at 1600x960 and 1920x1080, keeps all primary actions visible, and avoids overlap, clipping, and geometry drift.

## Best References

1. MobaXterm
   - https://mobaxterm.mobatek.net/features.html
   - Strong reference for dense desktop workflow: left session tree, toolbar, terminal tabs, split work surfaces.
2. SecureCRT
   - https://www.vandyke.com/products/securecrt/
   - Strong reference for tab groups, dockable command tools, session management, and terminal-first operator work.
3. PRTG
   - https://www.paessler.com/prtg
   - Strong reference for status emphasis, dashboards, maps, and a clean shell around dense monitoring content.
4. Cisco Catalyst Center
   - https://www.cisco.com/site/us/en/products/networking/catalyst-center/index.html
   - Strong reference for assurance, automation, centralized management, and network-operations hierarchy.
5. MikroTik WinBox
   - https://mikrotik.com/software
   - Strong reference for compact Windows operator UX where lists and tables matter more than large cards.

## Shared Patterns Across Good Operator Tools

- Persistent left inventory/session/device area.
- Central task area for the current operation and its primary controls.
- Diagnostics isolated in a dedicated right or bottom region.
- Tables and lists take precedence over decorative cards.
- Compact toolbars and action strips outperform large button stacks.
- Only important things get strong color: active tab, primary action, warning, error, success.
- Geometry remains stable when text changes; labels wrap or truncate instead of resizing the whole window.

## Layout Recommendation For CiscoAutoFlash

- Header: 110-130 px max, including title and state badge.
- Left panel: 360-420 px.
  - `Найденные устройства`
  - Dense table, stable columns, no hidden footer block under it.
- Center panel: 760-860 px.
  - Top status strip
  - Firmware + stage buttons + primary actions in a compact operator band
  - Session context + operator hint + progress grouped below as one logical block
- Right panel: 420-480 px.
  - `Журнал / Артефакты / Памятка`
  - Light notebook shell, dark log viewport only

## Anti-Patterns To Avoid

- Equal-width panes.
- Repeated nested labelframes with the same visual weight.
- Oversized top area that steals vertical space from the working panes.
- Long action rows without grouping.
- Progress, operator hint, and session context split into unrelated blocks with different height logic.
- Dynamic labels that resize the window instead of wrapping inside a fixed area.

## Styling Direction

- InRack-inspired light shell.
- White and light-slate surfaces.
- Brand blue as the only strong primary color.
- Cyan only as a secondary accent.
- Dark log viewport for terminal readability, not a dark whole diagnostics column.
- System-safe typography only; monospace limited to logs and terminal/prompt fields.

