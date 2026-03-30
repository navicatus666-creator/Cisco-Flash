# Portable Build Smoke Checklist

## Launch
- Start the carry bundle launcher or `dist/CiscoAutoFlash/CiscoAutoFlash.exe`.
- Confirm the window opens without Python console noise or import errors.
- Confirm a second instance is blocked.

## Runtime behavior
- Confirm `%LOCALAPPDATA%\CiscoAutoFlash\logs` is created.
- Confirm `%LOCALAPPDATA%\CiscoAutoFlash\reports` is created.
- Confirm `%LOCALAPPDATA%\CiscoAutoFlash\transcripts` is created.
- Confirm `%LOCALAPPDATA%\CiscoAutoFlash\settings\settings.json` is created after closing the app.

## UI smoke
- `Scan` button is enabled at startup.
- `Open log`, `Open report`, `Open transcript`, and `Open logs dir` do not crash.
- Preflight shows selected target, firmware, profile, and session paths.
- `Open session folder` resolves the current session location.
- `Export session bundle` creates a `session_bundle_*.zip` in the active session folder.
