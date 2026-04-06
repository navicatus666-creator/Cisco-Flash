from __future__ import annotations

import json
import os
import subprocess  # nosec B404
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from serial.tools import list_ports

POWERSHELL_ADAPTER_SNAPSHOT = (
    "Get-NetAdapter | "
    "Select-Object Name,InterfaceDescription,Status,MacAddress,LinkSpeed,MediaType | "
    "ConvertTo-Json -Compress"
)
ETHERNET_TOKENS = ("ethernet", "gigabit", "gbe", "lan", "i219", "i225", "realtek", "intel")
WIFI_TOKENS = ("wi-fi", "wifi", "wireless", "wlan")
VIRTUAL_TOKENS = ("bluetooth", "virtual", "loopback", "vpn", "hyper-v", "vmware", "tap")
USB_TOKENS = ("usb", "uart", "serial")
CISCO_TOKENS = ("cisco", "console")
SYSTEM_ROOT = Path(os.environ.get("SystemRoot", r"C:\Windows"))
POWERSHELL_EXE = str(
    SYSTEM_ROOT / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
)
PING_EXE = str(SYSTEM_ROOT / "System32" / "PING.EXE")


def _hidden_subprocess_kwargs() -> dict[str, Any]:
    if sys.platform != "win32":
        return {}
    kwargs: dict[str, Any] = {}
    startupinfo_cls = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_cls is not None:
        startupinfo = startupinfo_cls()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        kwargs["startupinfo"] = startupinfo
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if creationflags:
        kwargs["creationflags"] = creationflags
    return kwargs


def _timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def resolve_runtime_preflight_paths(
    output_dir_name: str,
    *,
    runtime_root: Path | None = None,
) -> dict[str, Path]:
    if runtime_root is None:
        from ciscoautoflash.config import default_runtime_root

        runtime_root = default_runtime_root()
    preflight_root = Path(runtime_root) / "preflight"
    output_dir = preflight_root / output_dir_name
    return {
        "preflight_root": preflight_root,
        "output_dir": output_dir,
        "summary_json": output_dir / "preflight_summary.json",
        "summary_md": output_dir / "preflight_summary.md",
        "latest_summary_json": preflight_root / "latest_preflight_summary.json",
    }


def _combined_text(*parts: object) -> str:
    return " ".join(str(part or "") for part in parts).strip().lower()


def _adapter_kind(name: str, description: str) -> str:
    combined = _combined_text(name, description)
    if any(token in combined for token in WIFI_TOKENS):
        return "wifi"
    if any(token in combined for token in VIRTUAL_TOKENS):
        return "other"
    if any(token in combined for token in ETHERNET_TOKENS):
        return "ethernet"
    return "other"


def _normalize_console_port(port: object) -> dict[str, Any]:
    device = str(getattr(port, "device", "") or "")
    description = str(getattr(port, "description", "") or "")
    manufacturer = str(getattr(port, "manufacturer", "") or "")
    product = str(getattr(port, "product", "") or "")
    hwid = str(getattr(port, "hwid", "") or "")
    combined = _combined_text(device, description, manufacturer, product, hwid)
    return {
        "device": device,
        "description": description,
        "manufacturer": manufacturer,
        "product": product,
        "hwid": hwid,
        "vid": getattr(port, "vid", None),
        "pid": getattr(port, "pid", None),
        "serial_number": str(getattr(port, "serial_number", "") or ""),
        "location": str(getattr(port, "location", "") or ""),
        "is_usb": any(token in combined for token in USB_TOKENS),
        "looks_like_cisco_console": any(token in combined for token in CISCO_TOKENS),
    }


def _collect_console_ports() -> dict[str, Any]:
    items = sorted(
        (_normalize_console_port(port) for port in list_ports.comports()),
        key=lambda item: item["device"],
    )
    usb_candidates = [item["device"] for item in items if item["is_usb"]]
    cisco_candidates = [
        item["device"] for item in items if item["looks_like_cisco_console"]
    ]
    recommended_primary = ""
    for candidates in (cisco_candidates, usb_candidates):
        if candidates:
            recommended_primary = candidates[0]
            break
    if not recommended_primary and items:
        recommended_primary = str(items[0]["device"])
    return {
        "items": items,
        "total_ports": len(items),
        "ready": bool(items),
        "usb_candidates": usb_candidates,
        "cisco_candidates": cisco_candidates,
        "recommended_primary": recommended_primary,
    }


def _collect_network_adapters() -> dict[str, Any]:
    if sys.platform != "win32":
        return {
            "available": False,
            "items": [],
            "ethernet_present": False,
            "ethernet_up": [],
            "ethernet_disconnected": [],
            "error": "Windows adapter snapshot is unavailable on this platform.",
        }
    try:
        completed = subprocess.run(
            [POWERSHELL_EXE, "-NoProfile", "-Command", POWERSHELL_ADAPTER_SNAPSHOT],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            **_hidden_subprocess_kwargs(),
        )  # nosec B603
    except OSError as exc:
        return {
            "available": False,
            "items": [],
            "ethernet_present": False,
            "ethernet_up": [],
            "ethernet_disconnected": [],
            "error": str(exc),
        }
    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0:
        return {
            "available": False,
            "items": [],
            "ethernet_present": False,
            "ethernet_up": [],
            "ethernet_disconnected": [],
            "error": stderr or f"powershell returned {completed.returncode}",
        }
    raw = (completed.stdout or "").strip()
    if not raw:
        records: list[dict[str, Any]] = []
    else:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            records = [parsed]
        elif isinstance(parsed, list):
            records = [item for item in parsed if isinstance(item, dict)]
        else:
            records = []
    items: list[dict[str, str]] = []
    ethernet_up: list[str] = []
    ethernet_disconnected: list[str] = []
    ethernet_present = False
    for record in records:
        name = str(record.get("Name", "") or "")
        description = str(record.get("InterfaceDescription", "") or "")
        status = str(record.get("Status", "") or "")
        adapter_type = _adapter_kind(name, description)
        item = {
            "name": name,
            "description": description,
            "status": status,
            "mac_address": str(record.get("MacAddress", "") or ""),
            "link_speed": str(record.get("LinkSpeed", "") or ""),
            "media_type": str(record.get("MediaType", "") or ""),
            "adapter_type": adapter_type,
        }
        items.append(item)
        if adapter_type != "ethernet":
            continue
        ethernet_present = True
        status_upper = status.upper()
        if status_upper == "UP":
            ethernet_up.append(name or description or "Ethernet")
        elif status_upper == "DISCONNECTED":
            ethernet_disconnected.append(name or description or "Ethernet")
    return {
        "available": True,
        "items": items,
        "ethernet_present": ethernet_present,
        "ethernet_up": ethernet_up,
        "ethernet_disconnected": ethernet_disconnected,
        "error": stderr,
    }


def _ping_host(host: str) -> dict[str, Any]:
    completed = subprocess.run(
        [PING_EXE, "-n", "1", host],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        **_hidden_subprocess_kwargs(),
    )  # nosec B603
    lines = [
        line.strip()
        for line in (completed.stdout or "").splitlines()
        if line.strip()
    ]
    return {
        "attempted": True,
        "host": host,
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "summary": lines[-1] if lines else "",
    }


def _probe_hidden_ssh(
    *,
    host: str,
    username: str,
    password: str,
    secret: str,
) -> dict[str, Any]:
    from ciscoautoflash.config import AppConfig
    from ciscoautoflash.core.models import ConnectionTarget
    from ciscoautoflash.core.ssh_transport import SshTransportFactory
    from ciscoautoflash.profiles import build_c2960x_profile

    config = AppConfig()
    target = ConnectionTarget(
        id=f"ssh:{host}",
        label=f"SSH {host}",
        metadata={
            "host": host,
            "username": username,
            "password": password,
            "secret": secret,
            "device_type": "cisco_ios",
            "port": 22,
            "file_system": "flash:",
        },
    )
    factory = SshTransportFactory(config.timing, [target], transcript_path=None)
    probe = factory.probe(target, build_c2960x_profile().prompts, config.timing.scan_probe_timeout)
    return {
        "attempted": True,
        "host": host,
        "available": probe.available,
        "connection_state": probe.connection_state,
        "prompt_type": probe.prompt_type or "",
        "status_message": probe.status_message,
        "recommended_next_action": probe.recommended_next_action,
        "error_code": probe.error_code,
    }


def build_connection_snapshot(
    *,
    host: str = "",
    username: str = "",
    password: str = "",
    secret: str = "",
) -> dict[str, Any]:
    host = host.strip()
    snapshot = {
        "generated_at": _timestamp(),
        "console": _collect_console_ports(),
        "network": _collect_network_adapters(),
        "ping": {
            "attempted": False,
            "host": host,
            "ok": False,
            "returncode": None,
            "summary": "",
        },
        "ssh_probe": {
            "attempted": False,
            "host": host,
            "available": False,
            "connection_state": "",
            "prompt_type": "",
            "status_message": "",
            "recommended_next_action": "",
            "error_code": "",
        },
    }
    if host:
        snapshot["ping"] = _ping_host(host)
        if username.strip() and password.strip():
            snapshot["ssh_probe"] = _probe_hidden_ssh(
                host=host,
                username=username.strip(),
                password=password.strip(),
                secret=secret.strip(),
            )
    return snapshot


def describe_connection_snapshot(snapshot: dict[str, Any]) -> dict[str, str]:
    console = snapshot.get("console", {})
    network = snapshot.get("network", {})
    ping = snapshot.get("ping", {})
    ssh_probe = snapshot.get("ssh_probe", {})
    console_items = console.get("items", []) if isinstance(console, dict) else []
    usb_candidates = console.get("usb_candidates", []) if isinstance(console, dict) else []
    recommended_primary = (
        str(console.get("recommended_primary", "")) if isinstance(console, dict) else ""
    )
    if not console_items:
        console_text = (
            "COM-порты не видны. Подключите один основной console path и держите "
            "второй как резерв."
        )
    else:
        ports = ", ".join(str(item.get("device", "")) for item in console_items)
        candidate_note = (
            f" Основной кандидат: {recommended_primary}."
            if recommended_primary
            else ""
        )
        usb_note = f" USB-кандидаты: {', '.join(usb_candidates)}." if usb_candidates else ""
        console_text = f"Видно COM: {ports}.{candidate_note}{usb_note}".strip()

    if not isinstance(network, dict) or not network.get("available", False):
        ethernet_text = (
            f"Состояние адаптеров недоступно: {network.get('error', 'неизвестно')}"
            if isinstance(network, dict)
            else "Состояние адаптеров недоступно."
        )
    elif not network.get("ethernet_present", False):
        ethernet_text = "Ethernet-адаптеры не обнаружены."
    else:
        up = network.get("ethernet_up", [])
        down = network.get("ethernet_disconnected", [])
        ethernet_text = (
            f"Ethernet up: {', '.join(up)}. "
            f"Disconnected: {', '.join(down) if down else 'нет'}."
        )

    if not isinstance(ssh_probe, dict) or not ssh_probe.get("host"):
        ssh_text = "Host не задан; ping и hidden SSH probe не выполнялись."
    elif ssh_probe.get("attempted"):
        status_detail = (
            ssh_probe.get("status_message")
            or ssh_probe.get("connection_state")
            or "нет деталей"
        )
        ssh_text = (
            f"SSH probe: {'готов' if ssh_probe.get('available') else 'не готов'}; "
            f"{status_detail}."
        )
    elif isinstance(ping, dict) and ping.get("attempted"):
        ssh_text = (
            f"Ping {'ok' if ping.get('ok') else 'failed'} для {ping.get('host')}. "
            "SSH probe пропущен: нет credentials."
        )
    else:
        ssh_text = "Host задан, но сетевые проверки не выполнялись."

    return {
        "console": console_text,
        "ethernet": ethernet_text,
        "ssh": ssh_text,
        "live_run_path": "console -> scan -> stage1 -> stage2 -> stage3 -> bundle",
        "return_path": "session bundle -> session folder -> triage_session_return.py",
    }


def load_latest_preflight_summary(build_root: Path) -> dict[str, Any] | None:
    if not build_root.exists():
        return None
    candidates = sorted(build_root.rglob("preflight_summary.json"))
    if not candidates:
        return None
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    return json.loads(latest.read_text(encoding="utf-8"))


def load_operator_preflight_summary(
    *,
    runtime_root: Path | None = None,
    project_root: Path | None = None,
) -> dict[str, Any] | None:
    runtime_paths = resolve_runtime_preflight_paths(
        "latest",
        runtime_root=runtime_root,
    )
    latest_runtime_summary = runtime_paths["latest_summary_json"]
    if latest_runtime_summary.exists():
        return json.loads(latest_runtime_summary.read_text(encoding="utf-8"))
    runtime_summary = load_latest_preflight_summary(runtime_paths["preflight_root"])
    if runtime_summary is not None:
        return runtime_summary
    if project_root is None:
        return None
    return load_latest_preflight_summary(Path(project_root) / "build" / "preflight")


def format_latest_preflight_status(summary: dict[str, Any] | None) -> str:
    if not summary:
        return "Локальный preflight ещё не запускался."
    status = str(summary.get("status", "UNKNOWN"))
    completed_at = str(summary.get("completed_at", "") or "").replace("T", " ")
    hardware_day_status = str(summary.get("hardware_day_status", "") or "")
    if hardware_day_status:
        return (
            f"{status}; hardware-day: {hardware_day_status}"
            f"{f' ({completed_at})' if completed_at else ''}"
        )
    return f"{status}{f' ({completed_at})' if completed_at else ''}"


def assess_hardware_day_readiness(
    *,
    preflight_status: str,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    console = snapshot.get("console", {})
    network = snapshot.get("network", {})
    ping = snapshot.get("ping", {})
    ssh_probe = snapshot.get("ssh_probe", {})
    base_ready = preflight_status == "READY"
    console_ready = bool(
        isinstance(console, dict) and console.get("ready", False)
    )
    status = "READY_FOR_HARDWARE" if base_ready and console_ready else "NOT_READY"
    next_steps: list[str] = []
    if not base_ready:
        next_steps.append(
            "Сначала прогоните scripts/pre_hardware_preflight.py до статуса READY."
        )
    if not console_ready:
        next_steps.append(
            "Подключите один основной console path и убедитесь, что Windows видит его как COM-порт."
        )
    else:
        recommended = str(console.get("recommended_primary", "") or "")
        if recommended:
            next_steps.append(
                "Основной console path: "
                f"{recommended}. Второй console path держите только резервным."
            )
    ethernet_up = (
        list(network.get("ethernet_up", []))
        if isinstance(network, dict)
        else []
    )
    if not ethernet_up:
        next_steps.append(
            "RJ45 management link пока не поднят; это не блокер для "
            "serial-first, но понадобится для optional SSH."
        )
    if isinstance(ping, dict) and ping.get("attempted") and not ping.get("ok"):
        next_steps.append(
            "Host не пингуется; для optional SSH сначала настройте management IP через console."
        )
    if (
        isinstance(ssh_probe, dict)
        and ssh_probe.get("attempted")
        and not ssh_probe.get("available")
    ):
        next_steps.append(
            "Hidden SSH probe не готов; optional SSH pass отложите до стабильного serial smoke."
        )
    if not next_steps:
        next_steps.append(
            "Можно идти в serial-first live run: scan -> stage1 -> stage2 -> stage3 -> bundle."
        )
    return {
        "status": status,
        "next_steps": next_steps,
    }


def render_connection_snapshot_markdown(snapshot: dict[str, Any]) -> str:
    described = describe_connection_snapshot(snapshot)
    lines = [
        "# CiscoAutoFlash Connection Snapshot",
        "",
        f"- Captured at: {snapshot.get('generated_at', '')}",
        f"- Console: {described['console']}",
        f"- Ethernet: {described['ethernet']}",
        f"- Optional SSH: {described['ssh']}",
        "",
        "## Flow",
        f"- Live run: {described['live_run_path']}",
        f"- Return path: {described['return_path']}",
        "",
    ]
    return "\n".join(lines)
