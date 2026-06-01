import shlex

from fastapi import APIRouter

from TravelRouter.components.settings.data_models import (
    SetRsyncDestinationRequest,
    SettingsConfigResponse,
)
from TravelRouter.config_file import DataManager
from TravelRouter.helpers.api_response import ApiResponse
from TravelRouter.helpers.run_command import run_command, run_in_thread

router = APIRouter()

data_manager = DataManager()


@router.get(
    "/settings/config",
    response_model=ApiResponse,
    tags=["settings"],
    summary="Get current settings",
    description="Returns the current AP SSID, AP password, saved Tailscale exit node, and rsync destination.",
)
async def api_settings_config() -> ApiResponse:
    settings = data_manager.get_data()
    return ApiResponse(
        success=True,
        msg=SettingsConfigResponse(
            ap_ssid=settings.wifi.ap_ssid,
            ap_password=settings.wifi.ap_password,
            exit_node=settings.tailscale.exit_node,
            rsync_host=settings.rsync.rsync_host,
            rsync_destination=settings.rsync.rsync_destination,
        ),
        msg_type="json",
    )


@router.post(
    "/settings/rsync/destination",
    response_model=ApiResponse,
    tags=["settings"],
    summary="Set and verify rsync backup destination",
    description=(
        "Saves the remote host (user@hostname) and destination path, then verifies "
        "reachability and directory existence via SSH before saving. "
        "Requires SSH key authentication to be configured on the Pi."
    ),
)
async def api_set_rsync_destination(body: SetRsyncDestinationRequest) -> ApiResponse:
    if not body.rsync_host.strip() or not body.rsync_destination.strip():
        return ApiResponse(success=False, msg="Host and destination path are required")

    result = await run_in_thread(
        run_command,
        [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            body.rsync_host,
            f"test -d {shlex.quote(body.rsync_destination)} && echo ok",
        ],
        15,
    )

    # Check stdout for "ok" — don't rely on result.success since SSH may
    # write host-key warnings to stderr even when the command succeeds.
    if "ok" not in result.stdout:
        detail = (result.stderr.splitlines()[0] if result.stderr else "").strip()
        msg = detail or "SSH connection failed or directory not found"
        return ApiResponse(success=False, msg=msg)

    data = data_manager.get_data()
    data.rsync.rsync_host = body.rsync_host.strip()
    data.rsync.rsync_destination = body.rsync_destination.strip()
    data_manager.set_data(data)

    return ApiResponse(success=True, msg="Destination verified and saved")
