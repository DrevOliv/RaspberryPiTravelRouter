from pydantic import BaseModel, Field


class AuthData(BaseModel):
    password_salt: str = ""
    password_hash: str = ""
    password_updated_at: float | None = None


class WifiData(BaseModel):
    wifi_ssid: str = "ChangeMe"
    wifi_password: str = "ChangeMe"
    upstream_interface: str = "wlan0"
    ap_interface: str = "wlan1"
    ap_password: str = "Password123"
    ap_ssid: str = "RouterPi"

class TailscaleData(BaseModel):
    exit_node: str = ""

class DataModels(BaseModel):
    auth: AuthData = Field(default_factory=AuthData)
    wifi: WifiData = Field(default_factory=WifiData)
    tailscale: TailscaleData = Field(default_factory=TailscaleData)
