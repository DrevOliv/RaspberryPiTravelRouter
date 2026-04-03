from pydantic import BaseModel


class SettingsConfigResponse(BaseModel):
    ap_ssid: str
    ap_password: str
    exit_node: str
