import json
import os

from fastapi import APIRouter

from TravelRouter.helpers.api_response import ApiResponse
from TravelRouter.helpers.run_command import run_in_thread

from TravelRouter.components.rsync.data_models import MountPoint, MountRequest
from TravelRouter.components.rsync.functions import (
    delete_dir,
    make_dirs,
    parse_lsblk,
    resolve_mount_path,
    scan_dir,
)
from TravelRouter.components.rsync.system_api import (
    get_connected_drives,
    mount_drive,
    unmount_drive,
)

router = APIRouter()


@router.get(
    "/drive/available_drives",
    response_model=ApiResponse,
    tags=["rsync"],
    summary="Get the connected drives",
    description="Get all the connected and available drives",
)
async def api_get_available_drives():
    result = await run_in_thread(get_connected_drives)
    if not result.success:
        return ApiResponse(msg=f"error getting connected drives {result.stderr}")

    try:
        drives = parse_lsblk(json.loads(result.stdout or "{}"))
    except json.JSONDecodeError:
        return ApiResponse(msg="error parsing connected drives output")

    return ApiResponse(success=True, msg=drives, msg_type="json")


@router.post(
    "/drive/mount",
    response_model=ApiResponse,
    tags=["rsync"],
    summary="Mount the drives",
    description="Mount the drive",
)
async def api_mount_drive(body: MountRequest):
    device = body.device.strip()
    label = body.label.strip()
    if not device or not label:
        return ApiResponse(msg="Missing data in post request")

    try:
        mount_point = await run_in_thread(make_dirs, label)
    except ValueError as error:
        return ApiResponse(msg=str(error))
    except OSError as error:
        return ApiResponse(msg=f"error creating mount point {error}")

    result = await run_in_thread(mount_drive, device, mount_point)
    if not result.success:
        try:
            await run_in_thread(delete_dir, mount_point)
        except (OSError, ValueError):
            pass
        return ApiResponse(msg=f"error mounting drive {result.stderr}")

    return ApiResponse(success=True, msg={"drive": label, "mount_point": mount_point}, msg_type="json")


@router.post(
    "/drive/unmount",
    response_model=ApiResponse,
    tags=["rsync"],
    summary="Unmount a drive",
    description="Unmount a drive and remove its mount directory",
)
async def api_unmount_drive(body: MountPoint):
    mount_point = body.mount_point.strip()
    if not mount_point:
        return ApiResponse(msg="Missing mount point")

    try:
        mount_point = resolve_mount_path(mount_point)
    except ValueError as error:
        return ApiResponse(msg=str(error))

    if not os.path.ismount(mount_point):
        return ApiResponse(msg="Mount point does not exist")

    result = await run_in_thread(unmount_drive, mount_point)
    if not result.success:
        return ApiResponse(msg=f"error unmounting drive {result.stderr}")

    try:
        await run_in_thread(delete_dir, mount_point)
    except (OSError, ValueError) as error:
        return ApiResponse(msg=f"Drive unmounted, but cleanup failed {error}")

    return ApiResponse(success=True, msg="Drive unmounted")


@router.post(
    "/drive/folders",
    response_model=ApiResponse,
    tags=["rsync"],
    summary="Get folders on a mounted drive",
    description="List child folders under a mounted drive path",
)
async def api_get_folders_struct(body: MountPoint):
    mount_point = body.mount_point.strip()
    if not mount_point:
        return ApiResponse(msg="Missing mount point")

    try:
        abs_path = resolve_mount_path(mount_point)
    except ValueError as error:
        return ApiResponse(msg=str(error))

    if not os.path.isdir(abs_path):
        return ApiResponse(msg="Path not found")

    dirs = await run_in_thread(scan_dir, abs_path)

    return ApiResponse(success=True, msg=dirs, msg_type="json")
