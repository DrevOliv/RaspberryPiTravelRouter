from fastapi import APIRouter, Response
from TravelRouter.config_file import DataManager

from TravelRouter.helpers.api_response import ApiResponse
from TravelRouter.helpers.run_command import run_in_thread

from TravelRouter.components.wifi.functions import (
    wifi_qr_svg,
    parse_wifi_scan_rows,
    parse_current_network,
)

from TravelRouter.components.wifi.system_api import (
    connect_wifi,
    disconnect_wifi,
    scan_for_wifi_networks,
    get_connected_network,
    list_wifi_interfaces,
)
from TravelRouter.components.wifi.hostapd import hostapd_controller, read_directive, set_directive

from TravelRouter.components.wifi.data_models import (
    WifiConnectBody,
    WifiSettingsBody,
    ApSsidBody,
    ApPasswordBody,
    ApConfigBody,
    WifiCurrent,
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
    result = await run_in_thread(
        connect_wifi,
        settings.wifi.upstream_interface,
        body.ssid.strip(),
        body.password.strip() or None,
    )
    if not result.success:
        return ApiResponse(msg=result.stderr or "Failed to connect to Wi-Fi")
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
    result = await run_in_thread(disconnect_wifi, settings.wifi.upstream_interface)
    if not result.success:
        return ApiResponse(msg=result.stderr or "Failed to disconnect Wi-Fi")
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
    result = await run_in_thread(scan_for_wifi_networks, settings.wifi.upstream_interface)
    if not result.success:
        return ApiResponse(msg=result.stderr or "Failed to scan for Wi-Fi networks")

    wifi_networks = parse_wifi_scan_rows(result.stdout)

    # Get connected network — not fatal if wlan0 is disconnected
    result = await run_in_thread(get_connected_network, settings.wifi.upstream_interface)
    current_network = parse_current_network(result.stdout)

    return ApiResponse(success=True,
                       msg=WifiLiveResponse(
                           wifi_networks=wifi_networks,
                           wifi_current=current_network,
                           connected_devices=await run_in_thread(hostapd_controller.get_connected_devices),
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
    description="Updates the private AP SSID in the hostapd config and reloads the access point.",
)
async def api_wifi_ap_ssid(body: ApSsidBody):
    ap_ssid = body.ap_ssid.strip()
    if not ap_ssid:
        return ApiResponse(msg="SSID cannot be empty")
    result = await run_in_thread(hostapd_controller.change_ap_creds, ssid=ap_ssid)
    if not result.success:
        # change_ap_creds returns an ApiResponse (its msg holds the error), not a CmdStatus.
        detail = result.msg.get("error") if isinstance(result.msg, dict) else result.msg
        return ApiResponse(success=False, msg=detail or "Failed to update AP SSID")
    return ApiResponse(success=True, msg="AP SSID saved")


@router.post(
    "/settings/wifi/ap-password",
    response_model=ApiResponse,
    tags=["wifi"],
    summary="Save private Wi-Fi password",
    description="Updates the private AP password in the hostapd config and reloads the access point.",
)
async def api_wifi_ap_password(body: ApPasswordBody):
    result = await run_in_thread(hostapd_controller.change_ap_creds, wpa_passphrase=body.ap_password.strip())
    if not result.success:
        # change_ap_creds returns an ApiResponse (its msg holds the error), not a CmdStatus.
        detail = result.msg.get("error") if isinstance(result.msg, dict) else result.msg
        return ApiResponse(success=False, msg=detail or "Failed to update AP password")
    return ApiResponse(success=True, msg="AP password saved")


@router.get(
    "/wifi/ap/config",
    response_model=ApiResponse,
    tags=["wifi"],
    summary="Get the hostapd config",
    description="Returns the current hostapd.conf for advanced editing.",
)
async def api_get_ap_config() -> ApiResponse:
    config = await run_in_thread(hostapd_controller.read_raw_config)
    if config is None:
        return ApiResponse(success=False, msg="Could not read hostapd config")
    return ApiResponse(
        success=True,
        msg={"config": config, "country_code": read_directive(config, "country_code")},
        msg_type="json",
    )


@router.post(
    "/wifi/ap/config",
    response_model=ApiResponse,
    tags=["wifi"],
    summary="Replace the hostapd config",
    description=(
        "Validates and installs a new hostapd.conf, restarts the access point, "
        "and automatically reverts if hostapd fails to start."
    ),
)
async def api_set_ap_config(body: ApConfigBody) -> ApiResponse:
    config = body.config
    if body.country_code is not None:
        config = set_directive(config, "country_code", body.country_code.strip())
    return await run_in_thread(hostapd_controller.apply_raw_config, config)


@router.post(
    "/wifi/ap/start",
    response_model=ApiResponse,
    tags=["wifi"],
    summary="Start the access point",
    description="Starts the hostapd service.",
)
async def api_ap_start() -> ApiResponse:
    return await run_in_thread(hostapd_controller.start)


@router.post(
    "/wifi/ap/stop",
    response_model=ApiResponse,
    tags=["wifi"],
    summary="Stop the access point",
    description="Stops the hostapd service.",
)
async def api_ap_stop() -> ApiResponse:
    return await run_in_thread(hostapd_controller.stop)


@router.get(
    "/wifi/interfaces",
    response_model=ApiResponse,
    tags=["wifi"],
    summary="List Wi-Fi interfaces",
    description="Returns the available wireless interfaces plus the configured upstream/AP interfaces.",
)
async def api_wifi_interfaces() -> ApiResponse:
    settings = data_manager.get_data()
    return ApiResponse(
        success=True,
        msg={
            "interfaces": await run_in_thread(list_wifi_interfaces),
            "upstream_interface": settings.wifi.upstream_interface,
            "ap_interface": settings.wifi.ap_interface,
        },
        msg_type="json",
    )
