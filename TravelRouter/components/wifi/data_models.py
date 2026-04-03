from pydantic import BaseModel, Field
from TravelRouter.components.wifi.functions import WifiNetwork


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

class WifiCurrent(BaseModel):
    state: str = Field(False, description="Whether the Pi is currently connected to an upstream Wi-Fi network and the state of the connected Wi-Fi network.")
    ssid: str = Field("", description="Current upstream SSID.")

class ConnectedDevice(BaseModel):
    name: str = Field("", description="Best available device label, usually a hostname or a friendly fallback.")
    ip: str = Field("", description="IPv4 or IPv6 address seen on the private AP.")
    mac: str = Field("", description="MAC address if available.")
    state: str = Field("", description="Neighbor or lease state for the connected device.")


class WifiLiveResponse(BaseModel):
    wifi_networks: list[WifiNetwork] = Field(..., description="List of Wi-Fi networks.")
    wifi_current: WifiCurrent
    connected_devices: list[ConnectedDevice]
