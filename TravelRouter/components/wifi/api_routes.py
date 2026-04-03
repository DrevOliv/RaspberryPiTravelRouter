from fastapi import APIRouter, Response
from TravelRouter.config_file import DataManager

from TravelRouter.helpers.api_response import ApiResponse

from TravelRouter.components.wifi.functions import (
    wifi_qr_svg,
    parse_wifi_scan_rows,
    parse_current_network,
    ap_connected_devices,
)

from TravelRouter.components.wifi.system_api import (
    connect_wifi,
    disconnect_wifi,
    apply_ap_ssid,
    apply_ap_password,
    scan_for_wifi_networks,
    get_connected_network,
)

from TravelRouter.components.wifi.data_models import (
    WifiConnectBody,
    WifiSettingsBody,
    ApSsidBody,
    ApPasswordBody,
    WifiLiveResponse,
)

router = APIRouter()

data_manager = DataManager()



@router.post(
    "/wifi/connect",
    response_model=ApiResponse,
    tags=["wifi"],
    summary="Connect to upstream Wi-Fi",
    description="Attempts to connect the upstream Wi-Fi interface to the specified SSID.",
    responses={400: {"model": ApiResponse, "description": "Connection request was rejected or failed validation."}},
)
async def api_wifi_connect(body: WifiConnectBody):
    settings = data_manager.get_data()
    result = connect_wifi(settings.wifi.upstream_interface, body.ssid.strip(), body.password.strip() or None)
    if not result.success:
        return ApiResponse(msg=result)
    clean_ssid = body.ssid.strip()
    return ApiResponse(success=True, msg=f"Connection to {clean_ssid} successful")


@router.post(
    "/wifi/disconnect",
    response_model=ApiResponse,
    tags=["wifi"],
    summary="Disconnect upstream Wi-Fi",
    description="Disconnects the upstream Wi-Fi interface from its current network.",
)
async def api_wifi_disconnect():
    settings = data_manager.get_data()
    result = disconnect_wifi(settings.wifi.upstream_interface)
    if not result.success:
        return ApiResponse(msg=result)
    return ApiResponse(success=True, msg="Wi-Fi disconnected")

@router.post(
    "/settings/wifi",
    response_model=ApiResponse,
    tags=["wifi"],
    summary="Save Wi-Fi interface settings",
    description="Updates which interfaces are used for upstream Wi-Fi and the private access point.",
)
async def api_wifi_settings(body: WifiSettingsBody):

    settings = data_manager.get_data()

    settings.wifi.upstream_interface = body.upstream_interface.strip()
    settings.wifi.ap_interface = body.ap_interface.strip()

    data_manager.set_data(settings)

    return ApiResponse(success=True, msg="Wi-Fi settings saved")

@router.get(
    "/wifi/wifi-live",
    response_model=ApiResponse,
    tags=["wifi"],
    summary="Get live Wi-Fi dashboard data",
    description="Returns only the current upstream Wi-Fi state and nearby scanned networks for lightweight Home screen polling.",
)
async def api_home_wifi_live():
    settings = data_manager.get_data()

    # Scan for other networks
    result = scan_for_wifi_networks(settings.wifi.upstream_interface)
    if not result.success:
        return ApiResponse(msg=result)

    wifi_networks = parse_wifi_scan_rows(result.stdout)

    # Get connected network
    result = get_connected_network(settings.wifi.upstream_interface)
    if not result.success:
        return ApiResponse(msg=result)

    current_network = parse_current_network(result.stdout)

    return ApiResponse(success=True,
                       msg=WifiLiveResponse(
                           wifi_networks=wifi_networks,
                           wifi_current=current_network,
                           connected_devices=ap_connected_devices(settings.wifi.ap_interface),     # Get connected devices to AP
                       ),
                       msg_type="json")


# _____________________________ AP _______________________________

@router.get(
    "/wifi/ap-qr",
    tags=["wifi"],
    summary="Get access-point Wi-Fi QR code",
    description="Returns an SVG QR code for joining the private travel-router Wi-Fi network.",
)
async def api_home_ap_qr():
    settings = data_manager.get_data()
    svg = wifi_qr_svg(settings.wifi.ap_ssid, settings.wifi.ap_password)
    return Response(content=svg, media_type="image/svg+xml")


@router.post(
    "/settings/wifi/ap-ssid",
    response_model=ApiResponse,
    tags=["wifi"],
    summary="Save private Wi-Fi SSID",
    description="Updates the private AP SSID on the existing NetworkManager access-point profile.",
)
async def api_wifi_ap_ssid(body: ApSsidBody):
    ap_ssid = body.ap_ssid.strip()
    if not ap_ssid:
        return ApiResponse(msg=f"SSID cannot be empty")
    result = apply_ap_ssid(ap_ssid)
    if not result.success:
        return ApiResponse(msg=result)

    settings = data_manager.get_data()

    settings.wifi.ap_ssid = ap_ssid
    data_manager.set_data(settings)

    return ApiResponse(success=True, msg="AP SSID saved")


@router.post(
    "/settings/wifi/ap-password",
    response_model=ApiResponse,
    tags=["wifi"],
    summary="Save private Wi-Fi password",
    description="Updates the private AP password on the existing NetworkManager access-point profile.",
)
async def api_wifi_ap_password(body: ApPasswordBody):
    result = apply_ap_password(body.ap_password.strip())
    if not result.success:
        return ApiResponse(msg=result)
    settings = data_manager.get_data()
    settings.wifi.ap_password = body.ap_password.strip()
    data_manager.set_data(settings)

    return ApiResponse(success=True, msg="AP password saved")

