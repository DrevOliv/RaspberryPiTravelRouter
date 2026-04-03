from TravelRouter.components.tailscale.data_models import TailscaleStatus, ExitNodeServer
import json
from ipaddress import ip_address, ip_network

def parse_tailscale_status(stdout:str)->TailscaleStatus:
    json_data = json.loads(stdout)

    # Finding if tailscale is connected to an exit-node
    if "ExitNodeStatus" in json_data:
        exit_node = True
        exit_node_server = json_data["ExitNodeStatus"]["TailscaleIPs"][0]
        exit_node_network = ip_network(exit_node_server)
    else:
        exit_node = False
        exit_node_server = None

    # Finding the server that advertise exit-node
    exit_node_servers = []

    for peer in json_data['Peer']:
        peer_values = json_data['Peer'][peer]

        if peer_values['ExitNodeOption'] == True:
            exit_node_servers.append(
                ExitNodeServer(hostname=peer_values["HostName"],
                               ip_address=peer_values["TailscaleIPs"][0],
                               dns_name=peer_values["DNSName"],
                               )
            )
            # Finding the hostname of the exit-node
            ip_address_exit_node = ip_address(peer_values["TailscaleIPs"][0])

            if ip_address_exit_node in exit_node_network:
                exit_node_server = peer_values["HostName"]

    return TailscaleStatus(
        online=json_data['Self']['online'],
        exit_node=exit_node,
        exit_node_server=exit_node_server,
        exit_node_servers=exit_node_servers
    )
