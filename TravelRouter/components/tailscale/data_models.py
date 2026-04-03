from pydantic import BaseModel, Field

class ExitNodeServer(BaseModel):
    hostname: str = Field(..., description="Hostname")
    ip_address: str = Field(..., description="IP address")
    dns_name: str = Field(..., description="DNS name")


class TailscaleStatus(BaseModel):
    online: bool = Field(..., description="If tailscale is online, up or down")
    exit_node: bool = Field(..., description="If tailscale uses exitnode")
    exit_node_server: str | None = Field(..., description="Tailscale exit node server that is used")
    exit_node_servers: list[ExitNodeServer] = Field(..., description="List of server nodes")


class ExitNodeSelectionBody(BaseModel):
    exit_node: str = Field("", description="Preferred Tailscale exit node DNS name or IP to save in settings.")
