from TravelRouter.helpers.run_command import run_command, CmdStatus

def tailscale_status()->CmdStatus:
    return run_command(["tailscale", "status", "--json"])

def tailscale_up()->CmdStatus:
    return run_command(["sudo","tailscale", "up", "--accept-routes"])

def tailscale_down()->CmdStatus:
    return run_command(["sudo","tailscale", "down"])

def tailscale_set_exit_node(ip_address: str)->CmdStatus:
    return run_command(["sudo", "tailscale", "set",
                        f"--exit-node={ip_address}",
                        "--exit-node-allow-lan-access=true"])

def tailscale_disable_exit_node()->CmdStatus:
    return run_command(["sudo", "tailscale", "set", "--exit-node="])

