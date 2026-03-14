# Scenario Matrix

| Scenario | Input state | Expected result |
|---|---|---|
| Clean boot to `Switch#` | Device already in privileged prompt | `Сканировать` detects ready state, summary cards show the selected target, and stages 1/3 are enabled |
| User prompt | Device returns `Switch>` | Workflow escalates to `enable`, UI shows prompt state clearly, and the operator card keeps the next step obvious |
| Config dialog after reboot | Device asks initial config dialog question | Workflow sends `no`, operator card remains understandable, and the dashboard returns to ready state |
| USB only on `usbflash1:` | `usbflash0:` empty, `usbflash1:` has image | Stage 2 falls back to `usbflash1:` and this is visible in log/progress/transcript |
| Wrong USB slot or firmware missing | Selected USB path does not contain the tar file | Stage 2 stops with a clear operator message and points the operator to check USB media and firmware name |
| Install quiet success | Install output stops after `installing` | Stage 2 treats quiet period as success and progress/status still remain understandable |
| No answering device | COM port exists but no Cisco prompt | UI shows a clear next step and blocks stage actions |
| ROMMON | Device returns `switch:` | UI marks ROMMON/recovery condition with an error-severity operator message |
| Login required | Device asks for username/password | UI shows login-required next step and does not pretend the target is ready |
| Reboot timeout | Device does not return to `Switch#` after Stage 1 or Stage 2 | Workflow fails fast, the operator card points to the timeout, and artifacts are available for triage |
| Operator abort | Operator presses `Stop` mid-stage | Workflow exits cleanly, buttons recover predictably, and transcript/log remain usable |
