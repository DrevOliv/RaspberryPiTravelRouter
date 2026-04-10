from pydantic import BaseModel, Field


class WifiConnectBody(BaseModel):
    ssid: str = Field(..., description="SSID of the upstream Wi-Fi network to connect to.")
    password: str = Field("", description="Password for the upstream Wi-Fi network. Leave empty for open networks.")


class WifiSettingsBody(BaseModel):
    upstream_interface: str = Field("wlan0", description="Interface used to join upstream Wi-Fi networks.")
    ap_interface: str = Field("wlan1", description="Interface used for the private access point.")


class ApSsidBody(BaseModel):
    ap_ssid: str = Field("PiTravelHub", description="SSID broadcast by the private travel-router access point.")


class ApPasswordBody(BaseModel):
    ap_password: str = Field("ChangeThisPassword", description="Password used for the private travel-router access point.")

# _________________________ Live update ___________________________


class WifiNetwork(BaseModel):
    ssid: str
    security: str
    is_open: bool
    signal: int


class WifiCurrent(BaseModel):
    state: str = Field("", description="NM connection state of the upstream interface.")
    ssid: str = Field("", description="Current upstream SSID.")
    operstate: str = Field("", description="Kernel operstate of the upstream interface (up, down, dormant, etc).")
    eth_operstate: str = Field("", description="Kernel operstate of the ethernet interface.")

class ConnectedDevice(BaseModel):
    mac: str = Field("", description="MAC address of the connected device.")
    ip: str = Field("", description="IP address from dnsmasq lease, if available.")
    name: str = Field("", description="Hostname from dnsmasq lease, or MAC as fallback.")
    signal_dbm: str = Field("", description="Signal strength in dBm as reported by hostapd.")
    connected_time: str = Field("", description="Seconds the device has been connected.")
    state: str = Field("", description="Connection state reported by hostapd.")


class WifiLiveResponse(BaseModel):
    wifi_networks: list[WifiNetwork] = Field(..., description="List of Wi-Fi networks.")
    wifi_current: WifiCurrent
    connected_devices: list[ConnectedDevice]
