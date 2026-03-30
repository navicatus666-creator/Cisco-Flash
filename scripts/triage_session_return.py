#!/usr/bin/env python3


def main() -> int:
    from ciscoautoflash.devtools.session_return_triage import main as run_triage

    return run_triage()


if __name__ == "__main__":
    raise SystemExit(main())
