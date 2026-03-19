# Legacy Parity Checklist

Compare the refactored app against `CiscoAutoFlash_GUI_Clean.py`.

- `Сканировать` finds the same practical COM target.
- Operator-visible guidance still covers `press_return`, `login`, `config_dialog`, and `ROMMON` states.
- Stage 1 still handles `startup-config is not present` without unnecessary erase.
- Stage 1 still deletes `vlan.dat` when present.
- Stage 1 still survives the initial config dialog after reboot.
- Stage 2 still uses `archive download-sw /overwrite /reload`.
- Stage 2 still supports USB fallback from `usbflash0:` to `usbflash1:`.
- Stage 2 progress is operator-visible enough to understand `examining -> extracting -> installing -> deleting -> signature -> reboot`.
- Stage 3 still gathers `show version`, `show boot`, `dir flash:`, and audit output.
- Final report contains the same operationally useful information.
- New app does not write runtime artifacts into the repo root.
