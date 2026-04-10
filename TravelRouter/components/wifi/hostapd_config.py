from pydantic import BaseModel

class HostapdConfig(BaseModel):
    interface: str
    ssid: str
    wpa_passphrase: str


    def __str__(self) -> str:
        return (
            f"interface={self.interface}\n"
            f"driver=nl80211\n"
            f"\n"
            f"ssid={self.ssid}\n"
            f"\n"
            f"country_code=SE\n"
            f"\n"
            f"hw_mode=g\n"
            f"channel=6\n"
            f"ieee80211n=1\n"
            f"wmm_enabled=1\n"
            f"\n"
            f"wpa=2\n"
            f"wpa_key_mgmt=WPA-PSK SAE\n"
            f"rsn_pairwise=CCMP\n"
            f"wpa_passphrase={self.wpa_passphrase}\n"
            f"\n"
            f"ieee80211w=1\n"
            f"sae_require_mfp=1\n"
            f"\n"
            f"auth_algs=1\n"
            f"ignore_broadcast_ssid=0\n"
            f"ctrl_interface=/var/run/hostapd\n"
        )

    def set_password(self, password: str) -> bool:
        if len(password) < 8 or len(password) > 64:
            return False
        self.wpa_passphrase = password
        return True


