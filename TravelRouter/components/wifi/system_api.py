from TravelRouter.helpers.run_command import run_command, CmdStatus


DNSMASQ_LEASES_PATH = "/var/lib/misc/dnsmasq.leases"
NM_DNSMASQ_LEASES_TEMPLATE = "/var/lib/nm-dnsmasq-{interface}.leases"
AP_CONNECTION_NAME = "MyHotspot"

# __________________________ WiFi connection __________________________

def connect_wifi(interface: str, ssid: str, password: str | None) -> CmdStatus:
    command = ["sudo", "nmcli", "dev", "wifi", "connect", ssid, "ifname", interface]
    if password:
        command.extend(["password", password])
    return run_command(command)



def disconnect_wifi(interface: str) -> CmdStatus:
    return run_command(["sudo", "nmcli", "device", "disconnect", interface])

def scan_for_wifi_networks(upstream_interface: str) -> CmdStatus:
    result = run_command(["sudo", "nmcli", "-t", "-f",
                          "SSID,SIGNAL,SECURITY",
                          "device", "wifi",
                          "list", "ifname", upstream_interface,
                          "--rescan", "yes"])

    return result

def get_connected_network(interface: str) -> CmdStatus:
    return run_command(["nmcli", "-t", "-g", "GENERAL.STATE,GENERAL.CONNECTION", "device", "show", interface])


# __________________________ AP _______________________________________


def reload_ap_connection(profile_name: str) -> CmdStatus:
    down_result = run_command(["sudo", "nmcli", "con", "down", profile_name])
    up_result = run_command(["sudo", "nmcli", "con", "up", profile_name])
    if not up_result.success:
        return up_result
    if not down_result.success:
        return up_result
    return up_result


def apply_ap_ssid(ap_ssid: str) -> CmdStatus:

    modify = run_command(["sudo", "nmcli", "con", "modify", AP_CONNECTION_NAME, "802-11-wireless.ssid", ap_ssid])
    if not modify.success:
        return modify

    restart = reload_ap_connection(AP_CONNECTION_NAME)
    if not restart.stderr:
        return restart

    return modify


def apply_ap_password(ap_password: str) -> CmdStatus:
    if len(ap_password) < 8:
        return CmdStatus(success=False, stderr="AP password must be at least 8 characters long", stdout="AP password must be at least 8 characters long")

    modify = run_command(["sudo", "nmcli", "con", "modify", AP_CONNECTION_NAME, "802-11-wireless-security.psk", ap_password])
    if not modify.success:
        return modify

    restart = reload_ap_connection(AP_CONNECTION_NAME)
    if not restart.success:
        return restart

    return modify


def get_ap_connected_devices(interface: str) -> CmdStatus:
    return run_command(["ip", "-j", "neigh", "show", "dev", interface])