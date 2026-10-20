"""
utils/network_utils.py

Phase 1 module: System Setup and Network Information.

Responsible for discovering the CURRENT, ACTUAL network configuration of the
machine. Nothing here is hardcoded -- the active interface, gateway, DNS
servers, etc. are all detected at run time, because a laptop's Wi-Fi
adapter name, IP address and gateway change from network to network.

Primary target platform is Windows 10/11 (per project spec), using
`ipconfig` output parsing. A Linux/macOS fallback path is also implemented
so the module (and therefore the whole app) can be developed and unit
tested on non-Windows machines; on those platforms it parses `ip route`
and `/etc/resolv.conf` instead of `ipconfig`.

Every public function is defensive: if a piece of information cannot be
determined (adapter down, no gateway, permission denied, command not
found, etc.) the function returns None / an empty structure instead of
raising, and the caller (interface_monitor.py / the GUI) decides how to
display "Unknown" or "Disconnected".
"""

from __future__ import annotations

import platform
import re
import socket
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

import psutil

from utils.logger import get_logger

logger = get_logger(__name__)

_IS_WINDOWS = platform.system().lower() == "windows"

# Subprocess calls must never hang the whole application if a network
# command misbehaves (e.g. a broken driver). Every subprocess call below
# uses this timeout.
_COMMAND_TIMEOUT_SECONDS = 5


@dataclass
class NetworkInfo:
    """Snapshot of the machine's current network configuration."""

    interface: Optional[str] = None
    connection_type: Optional[str] = None
    status: str = "Disconnected"
    ipv4: Optional[str] = None
    netmask: Optional[str] = None
    mac_address: Optional[str] = None
    gateway: Optional[str] = None
    dns_servers: List[str] = field(default_factory=list)

    @property
    def dns_display(self) -> str:
        return ", ".join(self.dns_servers) if self.dns_servers else "Unknown"


def _run_command(command: List[str]) -> Optional[str]:
    """
    Run a system command safely and return its stdout, or None on any
    failure (missing binary, timeout, non-zero exit, permission error).
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode != 0:
            logger.debug("Command %s exited with code %s: %s", command, result.returncode, result.stderr)
            return None
        return result.stdout
    except FileNotFoundError:
        logger.debug("Command not found: %s", command)
        return None
    except subprocess.TimeoutExpired:
        logger.warning("Command timed out: %s", command)
        return None
    except OSError as exc:
        logger.warning("OS error running command %s: %s", command, exc)
        return None


# --------------------------------------------------------------------------
# Gateway + interface-name detection (the piece that differs most by OS)
# --------------------------------------------------------------------------

def _detect_gateway_windows() -> tuple[Optional[str], Optional[str]]:
    """
    Parse `ipconfig /all` and return (gateway_ip, adapter_name) for the
    first adapter block that reports a non-empty Default Gateway.
    """
    output = _run_command(["ipconfig", "/all"])
    if not output:
        return None, None

    current_adapter = None
    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue

        # Adapter header lines look like: "Wireless LAN adapter Wi-Fi:"
        # or "Ethernet adapter Ethernet:" and are not indented.
        if not raw_line.startswith(" ") and line.endswith(":"):
            current_adapter = line[:-1]
            # Strip the generic "Wireless LAN adapter " / "Ethernet adapter "
            # prefix so we keep just the friendly name, e.g. "Wi-Fi".
            for prefix in ("Wireless LAN adapter ", "Ethernet adapter ", "Tunnel adapter "):
                if current_adapter.startswith(prefix):
                    current_adapter = current_adapter[len(prefix):]
            continue

        match = re.search(r"Default Gateway[ .]*:\s*(.+)", line)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                return candidate, current_adapter

    return None, None


def _detect_gateway_linux() -> tuple[Optional[str], Optional[str]]:
    """
    Parse `ip route show default` -> "default via 192.168.1.1 dev wlan0 ..."
    Used as the fallback on Linux/macOS development/test environments.

    If the `ip` binary is not installed (some minimal/container Linux
    images), fall back to reading /proc/net/route directly, which the
    kernel always exposes on Linux.
    """
    output = _run_command(["ip", "route", "show", "default"])
    if output:
        match = re.search(r"default via (\S+) dev (\S+)", output)
        if match:
            return match.group(1), match.group(2)

    return _detect_gateway_proc_net_route()


def _detect_gateway_proc_net_route() -> tuple[Optional[str], Optional[str]]:
    """
    Fallback gateway detection by reading /proc/net/route directly.

    Each row's "Gateway" column is a 4-byte IPv4 address stored as
    little-endian hex (e.g. "010200C0" -> bytes 01 02 00 C0, reversed ->
    192.0.2.1). The default route is the row whose Destination is 0
    and whose Flags bit 0x2 (RTF_GATEWAY) is set.
    """
    try:
        with open("/proc/net/route", "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError as exc:
        logger.debug("Could not read /proc/net/route: %s", exc)
        return None, None

    if len(lines) < 2:
        return None, None

    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 4:
            continue
        iface, destination, gateway_hex, flags_hex = fields[0], fields[1], fields[2], fields[3]
        try:
            flags = int(flags_hex, 16)
        except ValueError:
            continue

        is_default_destination = destination == "00000000"
        is_gateway_route = bool(flags & 0x2)
        if is_default_destination and is_gateway_route:
            gateway_ip = _hex_to_ipv4(gateway_hex)
            if gateway_ip:
                return gateway_ip, iface

    return None, None


def _hex_to_ipv4(hex_value: str) -> Optional[str]:
    """Convert a little-endian 4-byte hex string (as used in /proc/net/route)
    into a dotted-decimal IPv4 address string."""
    try:
        raw = int(hex_value, 16)
        return ".".join(str((raw >> (8 * i)) & 0xFF) for i in range(4))
    except ValueError:
        return None


def _detect_gateway() -> tuple[Optional[str], Optional[str]]:
    """Return (gateway_ip, interface_name) using the correct OS strategy."""
    if _IS_WINDOWS:
        return _detect_gateway_windows()
    return _detect_gateway_linux()


# --------------------------------------------------------------------------
# DNS server detection
# --------------------------------------------------------------------------

def _detect_dns_windows() -> List[str]:
    output = _run_command(["ipconfig", "/all"])
    if not output:
        return []

    servers: List[str] = []
    lines = output.splitlines()
    capturing = False
    for raw_line in lines:
        line = raw_line.strip()
        if re.search(r"DNS Servers[ .]*:\s*(.+)", raw_line):
            match = re.search(r"DNS Servers[ .]*:\s*(.+)", raw_line)
            first_value = match.group(1).strip()
            if first_value:
                servers.append(first_value)
            capturing = True
            continue
        if capturing:
            # Continuation lines for a second/third DNS server are
            # indented and contain only an IP address.
            if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", line) or ":" in line and re.match(r"^[0-9a-fA-F:]+$", line):
                servers.append(line)
            else:
                capturing = False

    # De-duplicate while preserving order.
    seen = set()
    unique_servers = []
    for server in servers:
        if server not in seen:
            seen.add(server)
            unique_servers.append(server)
    return unique_servers


def _detect_dns_linux() -> List[str]:
    servers: List[str] = []
    try:
        with open("/etc/resolv.conf", "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line.startswith("nameserver"):
                    parts = line.split()
                    if len(parts) >= 2:
                        servers.append(parts[1])
    except OSError as exc:
        logger.debug("Could not read /etc/resolv.conf: %s", exc)
    return servers


def _detect_dns_servers() -> List[str]:
    if _IS_WINDOWS:
        return _detect_dns_windows()
    return _detect_dns_linux()


# --------------------------------------------------------------------------
# psutil-based lookups (interface addresses, MAC, up/down status)
# --------------------------------------------------------------------------

def _get_ipv4_for_interface(interface: str) -> Optional[str]:
    try:
        addrs = psutil.net_if_addrs().get(interface, [])
    except (psutil.Error, OSError) as exc:
        logger.warning("psutil.net_if_addrs failed: %s", exc)
        return None

    for addr in addrs:
        if addr.family == socket.AF_INET:
            return addr.address
    return None


def _get_netmask_for_interface(interface: str) -> Optional[str]:
    """Return the IPv4 subnet mask for `interface` (e.g. '255.255.255.0'),
    or None if unavailable."""
    try:
        addrs = psutil.net_if_addrs().get(interface, [])
    except (psutil.Error, OSError) as exc:
        logger.warning("psutil.net_if_addrs failed while reading netmask: %s", exc)
        return None

    for addr in addrs:
        if addr.family == socket.AF_INET:
            return addr.netmask
    return None


def _get_mac_for_interface(interface: str) -> Optional[str]:
    try:
        addrs = psutil.net_if_addrs().get(interface, [])
    except (psutil.Error, OSError) as exc:
        logger.warning("psutil.net_if_addrs failed: %s", exc)
        return None

    mac_family = getattr(psutil, "AF_LINK", None)
    for addr in addrs:
        if mac_family is not None and addr.family == mac_family:
            return addr.address
        # Fallback: some platforms report MAC under a family enum psutil
        # does not expose a constant for; a MAC looks like six hex pairs.
        if re.match(r"^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}$", addr.address or ""):
            return addr.address
    return None


def _get_interface_status(interface: str) -> str:
    try:
        stats = psutil.net_if_stats().get(interface)
    except (psutil.Error, OSError) as exc:
        logger.warning("psutil.net_if_stats failed: %s", exc)
        return "Unknown"

    if stats is None:
        return "Unknown"
    return "Connected" if stats.isup else "Disconnected"


def _guess_connection_type(interface: str) -> str:
    """
    Best-effort classification of the connection type from the interface
    name. Windows friendly names are typically "Wi-Fi" or "Ethernet";
    Linux/macOS device names follow patterns like wlan0/eth0/en0.
    """
    if not interface:
        return "Unknown"

    name = interface.lower()
    if "wi-fi" in name or "wifi" in name or name.startswith("wlan") or name.startswith("wl"):
        return "Wi-Fi"
    if "ethernet" in name or name.startswith("eth") or name.startswith("en"):
        return "Ethernet"
    if "loopback" in name or name.startswith("lo"):
        return "Loopback"
    if "tunnel" in name or "vpn" in name or name.startswith("tun") or name.startswith("tap"):
        return "VPN/Tunnel"
    return "Unknown"


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def get_network_info() -> NetworkInfo:
    """
    Collect a full snapshot of the current network configuration.

    This is the single function the rest of the application (GUI,
    monitoring controller) should call. It never raises; on any failure
    the corresponding field is left as None/"Unknown" so the GUI can show
    a clear, non-crashing message instead.
    """
    info = NetworkInfo()

    try:
        gateway, interface = _detect_gateway()
        info.gateway = gateway
        info.interface = interface

        if interface:
            info.ipv4 = _get_ipv4_for_interface(interface)
            info.netmask = _get_netmask_for_interface(interface)
            info.mac_address = _get_mac_for_interface(interface)
            info.status = _get_interface_status(interface)
            info.connection_type = _guess_connection_type(interface)
        else:
            info.status = "Disconnected"

        info.dns_servers = _detect_dns_servers()

    except Exception as exc:  # noqa: BLE001 - last-resort safety net for the GUI
        logger.exception("Unexpected error while collecting network info: %s", exc)

    return info


if __name__ == "__main__":
    # Quick manual check: `python -m utils.network_utils`
    snapshot = get_network_info()
    print("Interface:      ", snapshot.interface or "Unknown")
    print("Connection type:", snapshot.connection_type or "Unknown")
    print("Status:         ", snapshot.status)
    print("IPv4:           ", snapshot.ipv4 or "Unknown")
    print("Netmask:        ", snapshot.netmask or "Unknown")
    print("MAC Address:    ", snapshot.mac_address or "Unknown")
    print("Gateway:        ", snapshot.gateway or "Unknown")
    print("DNS Servers:    ", snapshot.dns_display)
