"""Vulture allowlist for dynamic contracts and test doubles.

These names are intentionally present for protocol/classvar contracts, future
transport integration, or test harness state that is set indirectly.
"""

selected_transport = None
transport_type = None
PRECHECK = None
install_strategy = None
strip_prompt = None
strip_command = None


class _:
    focused = None
    interrupted = None
