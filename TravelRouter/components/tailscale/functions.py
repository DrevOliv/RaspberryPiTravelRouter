import json

from TravelRouter.components.tailscale.data_models import ExitNodeServer, TailscaleStatus


def parse_accept_routes(stdout: str) -> bool:
    """Read the --accept-routes pref (RouteAll) from `tailscale debug prefs` JSON."""
    try:
        return bool(json.loads(stdout or "{}").get("RouteAll", False))
    except json.JSONDecodeError:
        return False


def _self_online(self_data: dict) -> bool:
    return bool(self_data.get("Online", False))


def _active_exit_node_ip(json_data: dict) -> str | None:
    exit_node_status = json_data.get("ExitNodeStatus")
    if not exit_node_status:
        return None

    tailscale_ips = exit_node_status.get("TailscaleIPs") or []
    return tailscale_ips[0] if tailscale_ips else None


def parse_tailscale_status(stdout: str) -> TailscaleStatus:
    json_data = json.loads(stdout or "{}")
    self_data = json_data.get("Self") or {}
    active_exit_node_ip = _active_exit_node_ip(json_data)

    # Finding if tailscale is connected to an exit-node
    exit_node = active_exit_node_ip is not None
    exit_node_server = active_exit_node_ip

    # Finding the server that advertise exit-node
    exit_node_servers = []

    for peer_values in (json_data.get("Peer") or {}).values():
        if not peer_values.get("ExitNodeOption"):
            continue

        peer_ips = peer_values.get("TailscaleIPs") or []
        peer_ip = peer_ips[0] if peer_ips else ""
        hostname = peer_values.get("HostName", "")

        exit_node_servers.append(
            ExitNodeServer(
                hostname=hostname,
                ip_address=peer_ip,
                dns_name=peer_values.get("DNSName", ""),
            )
        )

        if active_exit_node_ip and active_exit_node_ip in peer_ips:
            exit_node_server = hostname

    return TailscaleStatus(
        online=_self_online(self_data),
        exit_node=exit_node,
        exit_node_server=exit_node_server,
        exit_node_servers=exit_node_servers,
    )
