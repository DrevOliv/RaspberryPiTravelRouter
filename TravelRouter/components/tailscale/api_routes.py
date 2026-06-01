from fastapi import APIRouter
from TravelRouter.config_file import DataManager

from TravelRouter.helpers.api_response import ApiResponse
from TravelRouter.helpers.run_command import run_in_thread

from TravelRouter.components.tailscale.data_models import (
    ExitNodeSelectionBody,
    TailscaleStatus,
)

from TravelRouter.components.tailscale.functions import parse_tailscale_status

from TravelRouter.components.tailscale.system_api import (
    tailscale_status,
    tailscale_set_exit_node,
    tailscale_disable_exit_node,
    tailscale_up,
    tailscale_down,
)


router = APIRouter()

data_manager = DataManager()


async def get_tailscale_status() -> ApiResponse:
    status = await run_in_thread(tailscale_status)
    if not status.success:
        # Tailscale is optional: if the CLI is missing or not responding, report it
        # as unavailable so the UI can grey it out instead of showing an error.
        return ApiResponse(
            success=True,
            msg=TailscaleStatus(
                available=False,
                online=False,
                exit_node=False,
                exit_node_server=None,
                exit_node_servers=[],
            ),
            msg_type="json",
        )

    return ApiResponse(success=True, msg=parse_tailscale_status(status.stdout), msg_type="json")


@router.get(
    "/tailscale/status",
    response_model=ApiResponse,
    tags=["tailscale"],
    summary="Gets tailscale status",
    description="Gets the current tailscale status, exit node and if its online and so on",
)
async def api_tailscale_status():
    return await get_tailscale_status()


@router.post(
    "/tailscale/selection",
    response_model=ApiResponse,
    tags=["tailscale"],
    summary="Save preferred exit node to settings",
    description="Saves the preferred Tailscale exit node in app settings without turning it on immediately.",
)
async def api_tailscale_selection(body: ExitNodeSelectionBody):
    settings = data_manager.get_data()

    selected = body.exit_node.strip()
    if not selected:
        return ApiResponse(msg="Choose an exit node first")

    settings.tailscale.exit_node = selected

    data_manager.set_data(settings)

    return ApiResponse(success=True, msg="Exit node saved")


@router.get(
    "/tailscale/set-exit-node",
    response_model=ApiResponse,
    tags=["tailscale"],
    summary="Sets exit node to ip_address",
    description="Sets the exit node to ip_address from the saved exit node in settings",
)
async def api_tailscale_set_exit_node():

    settings = data_manager.get_data()

    exit_node_name = settings.tailscale.exit_node
    if not exit_node_name:
        return ApiResponse(msg="Choose an exit node first")

    result = await run_in_thread(tailscale_set_exit_node, exit_node_name)
    if not result.success:
        return ApiResponse(msg=f"error setting exit node {result.stderr}")

    return await get_tailscale_status()


@router.get(
    "/tailscale/disable-exit-node",
    response_model=ApiResponse,
    tags=["tailscale"],
    summary="Disables the exit node",
    description="Disables the exit node, so that data does not go thought the exit node",
)
async def api_tailscale_disable_exit_node():

    result = await run_in_thread(tailscale_disable_exit_node)
    if not result.success:
        return ApiResponse(msg=f"error disabling exit node {result.stderr}")

    return await get_tailscale_status()


@router.get(
    "/tailscale/up",
    response_model=ApiResponse,
    tags=["tailscale"],
    summary="Set tailscale up",
    description="Sets so tailscale get online onto the tailnet",
)
async def api_tailscale_up():
    status = await run_in_thread(tailscale_up)
    if not status.success:
        return ApiResponse(msg=f"error setting tailscale to up: {status.stderr}")

    return await get_tailscale_status()


@router.get(
    "/tailscale/down",
    response_model=ApiResponse,
    tags=["tailscale"],
    summary="Set tailscale down",
    description="Sets so tailscale goes offline from the tailnet",
)
async def api_tailscale_down():
    status = await run_in_thread(tailscale_down)
    if not status.success:
        return ApiResponse(msg=f"error setting tailscale to down: {status.stderr}")

    return await get_tailscale_status()
