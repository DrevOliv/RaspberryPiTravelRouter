from fastapi import APIRouter, Depends

from TravelRouter.components.auth.functions import require_api_auth
from TravelRouter.components.settings.data_models import SettingsConfigResponse
from TravelRouter.config_file import DataManager
from TravelRouter.helpers.api_response import ApiResponse

router = APIRouter()

data_manager = DataManager()


@router.get(
    "/settings/config",
    response_model=ApiResponse,
    tags=["settings"],
    summary="Get current settings",
    description="Returns the current AP SSID, AP password, and saved Tailscale exit node.",
    dependencies=[Depends(require_api_auth)],
)
async def api_settings_config() -> ApiResponse:
    settings = data_manager.get_data()
    return ApiResponse(
        success=True,
        msg=SettingsConfigResponse(
            ap_ssid=settings.wifi.ap_ssid,
            ap_password=settings.wifi.ap_password,
            exit_node=settings.tailscale.exit_node,
        ),
        msg_type="json",
    )
