from pydantic import BaseModel

from TravelRouter.config_file.data_models import RsyncData, TailscaleData, WifiData


class SettingsConfigResponse(BaseModel):
    ap_ssid: str
    ap_password: str
    exit_node: str
    rsync_host: str = ""
    rsync_destination: str = ""


class SetRsyncDestinationRequest(BaseModel):
    rsync_host: str
    rsync_destination: str


class SshKeyResponse(BaseModel):
    exists: bool
    public_key: str = ""
    fingerprint: str = ""


class SettingsImport(BaseModel):
    # Settings only — never auth. Sections are optional so partial imports work.
    wifi: WifiData | None = None
    tailscale: TailscaleData | None = None
    rsync: RsyncData | None = None
