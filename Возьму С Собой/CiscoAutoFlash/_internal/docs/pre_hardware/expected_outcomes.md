# Expected Outcomes

## Scan
- `scan_results` event is emitted.
- The selected target is visible in summary cards and preflight.
- The operator card shows a severity-aware message and a concrete next step.
- The diagnostics pane reflects the current session paths.

## Stage 1
- `write erase` only when startup-config exists.
- `vlan.dat` is deleted when present.
- The device returns to `Switch#`.
- `stage1_complete = True`.
- Transcript contains `show startup-config` and `reload`.
- The dashboard clearly moves from reset to reboot wait and then back to ready state.

## Stage 2
- The USB image is found on `usbflash0:` or `usbflash1:`.
- The progress block advances through install markers.
- Quiet success and reboot wait are reflected in the UI as an understandable install flow.
- The device returns after reboot.
- `stage2_complete = True`.
- Transcript contains the `archive download-sw` command.

## Stage 3
- `show version`, `show boot`, `dir flash:` and audit commands run.
- The report file is written.
- Transcript contains verification commands.
- The operator can see where to look in log/report/transcript from the diagnostics pane.
- Final state is `DONE`.
