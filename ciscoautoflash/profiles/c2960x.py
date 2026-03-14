from __future__ import annotations

import re
from dataclasses import dataclass

from ..core.models import AuditCommand, StorageInfo, VersionInfo


@dataclass(slots=True)
class DeviceProfile:
    id: str
    display_name: str
    prompts: tuple[str, ...]
    default_firmware: str
    usb_paths: tuple[str, ...]
    install_strategy: str
    verify_commands: tuple[AuditCommand, ...]

    def parse_version(self, output: str) -> VersionInfo:
        raise NotImplementedError

    def parse_storage(self, output: str) -> StorageInfo:
        raise NotImplementedError


@dataclass(slots=True)
class Cisco2960XProfile(DeviceProfile):
    privileged_prompt: str = "Switch#"
    user_prompt: str = "Switch>"
    reduced_prompt: str = "switch:"

    def parse_version(self, output: str) -> VersionInfo:
        version = ""
        image = ""
        model = ""
        uptime = ""

        match = re.search(r"Version\s+([\w()./-]+)", output)
        if match:
            version = match.group(1)

        match = re.search(r'System\s+image\s+file\s+is\s+"([^"]+)"', output)
        if match:
            image = match.group(1)

        for pattern in (
            r"Model\s+[Nn]umber\s*:\s*([\w-]+)",
            r"PID:\s*([\w-]+)",
            r"(WS-C\d+[\w-]+)",
        ):
            match = re.search(pattern, output)
            if match:
                model = match.group(1)
                break

        match = re.search(r"uptime is\s+([^\n,]+)", output, re.IGNORECASE)
        if match:
            uptime = match.group(1).strip()

        return VersionInfo(version=version, image=image, model=model, uptime=uptime)

    def parse_storage(self, output: str) -> StorageInfo:
        match = re.search(r"(\d+)\s+bytes\s+total\s+\((\d+)\s+bytes\s+free\)", output)
        if not match:
            return StorageInfo()
        total_bytes = int(match.group(1))
        free_bytes = int(match.group(2))
        return StorageInfo(total_bytes=total_bytes, free_bytes=free_bytes)


def build_c2960x_profile() -> Cisco2960XProfile:
    return Cisco2960XProfile(
        id="c2960x",
        display_name="Cisco Catalyst 2960-X",
        prompts=("Switch#", "Switch>", "switch:"),
        default_firmware="c2960x-universalk9-tar.152-7.E13.tar",
        usb_paths=("usbflash0:", "usbflash1:"),
        install_strategy="archive_download_sw",
        verify_commands=(
            AuditCommand("show inventory", "SHOW INVENTORY", 2.0),
            AuditCommand("show license", "SHOW LICENSE", 2.0),
            AuditCommand("show system mtu", "SHOW SYSTEM MTU", 1.5),
            AuditCommand("show switch", "SHOW SWITCH", 1.5),
            AuditCommand("show switch detail", "SHOW SWITCH DETAIL", 2.5),
            AuditCommand("show power inline", "SHOW POWER INLINE", 2.0),
            AuditCommand("show interfaces status", "SHOW INTERFACES STATUS", 3.0),
            AuditCommand("show ip interface brief", "SHOW IP INTERFACE BRIEF", 2.5),
            AuditCommand("show interfaces trunk", "SHOW INTERFACES TRUNK", 2.0),
            AuditCommand("show vlan brief", "SHOW VLAN BRIEF", 2.0),
            AuditCommand("show spanning-tree summary", "SHOW SPANNING-TREE SUMMARY", 2.5),
            AuditCommand("show ip default-gateway", "SHOW IP DEFAULT-GATEWAY", 1.5),
            AuditCommand("show mac address-table", "SHOW MAC ADDRESS-TABLE", 3.0),
            AuditCommand("show mac address-table secure", "SHOW MAC ADDRESS-TABLE SECURE", 2.5),
            AuditCommand("show arp", "SHOW ARP", 2.0),
            AuditCommand("show ip route", "SHOW IP ROUTE", 2.5),
            AuditCommand("show port-security", "SHOW PORT-SECURITY", 2.0),
            AuditCommand("show ip dhcp binding", "SHOW IP DHCP BINDING", 2.0),
            AuditCommand("show ip dhcp snooping", "SHOW IP DHCP SNOOPING", 2.5),
            AuditCommand("show ntp status", "SHOW NTP STATUS", 2.0),
            AuditCommand("show running-config", "SHOW RUNNING-CONFIG", 5.0),
            AuditCommand("show startup-config", "SHOW STARTUP-CONFIG", 4.0),
            AuditCommand("show clock", "SHOW CLOCK", 1.0),
            AuditCommand("show logging", "SHOW LOGGING", 4.0),
            AuditCommand("show cdp neighbors", "SHOW CDP NEIGHBORS", 2.0),
            AuditCommand("show cdp neighbors detail", "SHOW CDP NEIGHBORS DETAIL", 3.0),
            AuditCommand("show lldp neighbors", "SHOW LLDP NEIGHBORS", 2.0),
            AuditCommand("show lldp neighbors detail", "SHOW LLDP NEIGHBORS DETAIL", 3.0),
            AuditCommand("show etherchannel summary", "SHOW ETHERCHANNEL SUMMARY", 2.0),
        ),
    )
