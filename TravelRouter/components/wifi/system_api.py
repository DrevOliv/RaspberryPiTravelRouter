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


def get_connected_network(interface: str) -> CmdStatus:
    return run_command(["nmcli", "-t", "-g", "GENERAL.STATE,GENERAL.CONNECTION", "device", "show", interface])
