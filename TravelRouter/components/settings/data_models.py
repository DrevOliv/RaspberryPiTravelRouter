from pydantic import BaseModel


class SettingsConfigResponse(BaseModel):
    ap_ssid: str
    ap_password: str
    exit_node: str
    rsync_host: str = ""
    rsync_destination: str = ""


class SetRsyncDestinationRequest(BaseModel):
    rsync_host: str
    rsync_destination: str
