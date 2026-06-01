import json
import os

from fastapi import APIRouter

from TravelRouter.helpers.api_response import ApiResponse
from TravelRouter.helpers.run_command import run_in_thread

from TravelRouter.components.drive.data_models import FolderRequest, MountPoint, MountRequest
from TravelRouter.components.drive.functions import (
    delete_dir,
    find_device_mount_point,
    list_mounted_drives,
    make_dirs,
    parse_lsblk,
    resolve_folder_path,
    resolve_mount_path,
    scan_dir,
)
from TravelRouter.components.drive.system_api import (
    get_connected_drives,
    mount_drive,
    unmount_drive,
)

router = APIRouter()


@router.get(
    "/drive/available_drives",
    response_model=ApiResponse,
    tags=["drive"],
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


@router.get(
    "/drive/mounted_drives",
    response_model=ApiResponse,
    tags=["drive"],
    summary="List mounted drives",
    description="Returns drives currently mounted under the travel-router mount base.",
)
async def api_get_mounted_drives():
    drives = await run_in_thread(list_mounted_drives)
    return ApiResponse(success=True, msg={"drives": drives}, msg_type="json")


@router.post(
    "/drive/mount",
    response_model=ApiResponse,
    tags=["drive"],
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

    if os.path.ismount(mount_point):
        return ApiResponse(
            success=True,
            msg={"drive": label, "mount_point": mount_point},
            msg_type="json",
        )

    existing_mount_point = await run_in_thread(find_device_mount_point, device)
    if existing_mount_point:
        return ApiResponse(
            success=True,
            msg={"drive": label, "mount_point": existing_mount_point},
            msg_type="json",
        )

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
    tags=["drive"],
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
    tags=["drive"],
    summary="Get folders on a mounted drive",
    description="List child folders under a mounted drive path",
)
async def api_get_folders_struct(body: FolderRequest):
    mount_point = body.mount_point.strip()
    if not mount_point:
        return ApiResponse(msg="Missing mount point")

    try:
        mount_point = resolve_mount_path(mount_point)
        abs_path = resolve_folder_path(mount_point, body.sub_path)
    except ValueError as error:
        return ApiResponse(msg=str(error))

    if not os.path.ismount(mount_point):
        return ApiResponse(msg="Mount point does not exist")

    if not os.path.isdir(abs_path):
        return ApiResponse(msg="Path not found")

    dirs = await run_in_thread(scan_dir, abs_path)

    return ApiResponse(success=True, msg=dirs, msg_type="json")
