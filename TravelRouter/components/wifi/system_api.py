from pathlib import Path

from TravelRouter.helpers.run_command import run_command, CmdStatus

# __________________________ WiFi connection __________________________

def connect_wifi(interface: str, ssid: str, password: str | None) -> CmdStatus:
    command = ["sudo", "nmcli", "dev", "wifi", "connect", ssid, "ifname", interface]
    if password:
        command.extend(["password", password])
    return run_command(command)


def disconnect_wifi(interface: str) -> CmdStatus:
    return run_command(["sudo", "nmcli", "device", "disconnect", interface])


def scan_for_wifi_networks(upstream_interface: str) -> CmdStatus:
    return run_command([
        "sudo", "nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY",
        "device", "wifi", "list", "ifname", upstream_interface,
        "--rescan", "yes",
    ])


def _read_operstate(interface: str) -> str:
    try:
        return open(f"/sys/class/net/{interface}/operstate").read().strip()
    except OSError:
        return "unknown"


_SEP = "\x00"  # null byte — never appears in nmcli or sysfs output

def get_connected_network(interface: str, eth_interface: str = "eth0") -> CmdStatus:
    result = run_command(["nmcli", "-t", "-g", "GENERAL.STATE,GENERAL.CONNECTION", "device", "show", interface])
    result.stdout = f"{result.stdout}{_SEP}{_read_operstate(interface)}{_SEP}{_read_operstate(eth_interface)}"
    return result


def list_wifi_interfaces() -> list[str]:
    """Wireless interface names from sysfs (those backed by a phy80211 device)."""
    net = Path("/sys/class/net")
    if not net.exists():
        return []
    return sorted(p.name for p in net.iterdir() if (p / "phy80211").exists())
