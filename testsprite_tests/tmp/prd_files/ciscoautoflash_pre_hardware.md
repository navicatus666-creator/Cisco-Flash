# CiscoAutoFlash Pre-Hardware Context

## Product

CiscoAutoFlash is a Windows desktop application for Cisco 2960-X maintenance workflows.
The current shipping phase is serial-first and USB-aware. The app is intended to support
real operator use on hardware, while also providing a demo and replay workflow for
pre-hardware validation.

## Current Goal

The current milestone is pre-hardware readiness. The software should be stable enough for a
real smoke run on a Cisco 2960-X, while all non-hardware flows remain testable without the
switch.

## In-Scope Workflows

- Scan and detect target state over serial/USB
- Stage 1 reboot and config-dialog handling
- Stage 2 install flow and timeout/error handling
- Stage 3 verification and reporting
- Session artifact export, including bundle creation
- Demo mode and replay scenarios for dry runs

## Out-Of-Scope For This Phase

- Broad multi-device family support
- Full SSH-first operator UX
- Production release automation beyond Windows field packaging

## Technical Context

- Language: Python 3.14
- UI: ttkbootstrap / tkinter desktop dashboard
- Serial transport: pyserial
- Optional SSH backend pieces: Netmiko, Paramiko, ntc-templates
- Packaging: PyInstaller onedir bundle for Windows carry-and-run testing
- Runtime artifacts: `%LOCALAPPDATA%\\CiscoAutoFlash\\`

## Architecture

- `ciscoautoflash/ui`: dashboard and operator-facing controls
- `ciscoautoflash/core`: workflow, reporting, session artifacts, transports
- `ciscoautoflash/replay`: replay and demo harness
- `replay_scenarios`: canned stage scenarios
- `tests`: unit and integration tests
- `docs/pre_hardware`: readiness and hardware runbooks

## Quality And Validation

- Unit and integration tests exist under `tests/`
- Replay fixtures cover scan, stage1, stage2, stage3, and full install/verify paths
- Demo mode is used for GUI self-test work without real hardware
- Real operator artifacts must include log, transcript, report, manifest, and bundle

## Current Constraints

- The primary operator target is Cisco 2960-X over serial/USB
- Demo artifacts must stay under `%LOCALAPPDATA%\\CiscoAutoFlash\\demo`
- Hidden SSH/SCP backend code exists but is not yet exposed in the UI
- Pre-hardware work should avoid destabilizing the field-test baseline

## What TestSprite Should Focus On

- Understand the project structure and current phase
- Identify strong and weak testing areas
- Suggest useful test strategy improvements without rewriting the app
- Prefer read-only analysis and planning over large automatic changes
