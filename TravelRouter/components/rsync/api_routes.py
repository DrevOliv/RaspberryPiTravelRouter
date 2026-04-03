from fastapi import APIRouter
from TravelRouter.config_file import DataManager
import json
import os

from TravelRouter.helpers.api_response import ApiResponse
from TravelRouter.helpers.run_command import run_in_thread

from TravelRouter.components.rsync.data_models import MountRequest, MountPoint

from TravelRouter.components.rsync.system_api import (
    get_connected_drives,
    mount_drive,
    unmount_drive,
)

from TravelRouter.components.rsync.functions import (
    parse_lsblk,
    make_dirs,
    delete_dir,
    scan_dir
)

router = APIRouter()

data_manager = DataManager()


@router.get(
    "/drive/available_drives",
    response_model=ApiResponse,
    tags=["file system"],
    summary="Get the connected drives",
    description="Get all the connected and available drives",
)
async def api_get_available_drives():

    result = run_in_thread(get_connected_drives)
    if not result.success:
        return ApiResponse(msg=f"error getting connected drives {result.stderr}")


    drives = parse_lsblk(json.loads(result.stdout))

    return ApiResponse(success=True, msg=drives, msg_type="json")

@router.post(
    "/drive/mount",
    response_model=ApiResponse,
    tags=["file system"],
    summary="Mount the drives",
    description="Mount the drive",
)
async def api_mount_drive(body: MountRequest):

    device = body.device.strip()
    label = body.label.strip()
    if not device or not label:
        return ApiResponse(msg="Missing data in post request")

    mount_point = make_dirs(label)
    result = run_in_thread(mount_drive, device, mount_point)
    if not result.success:
        return ApiResponse(msg=f"error mounting drive {result.stderr}")

    return ApiResponse(success=True, msg={"drive": label, "mount_point": mount_point}, msg_type="json")

@router.post(
    "/drive/unmount",
    response_model=ApiResponse,
    tags=["file system"],
    summary="Get the connected drives",
    description="Get all the connected and available drives",
)
async def api_mount_drive(body: MountPoint):

    mount_point = body.mount_point.strip()
    if not mount_point:
        return ApiResponse(msg="Missing mount point")

    if not os.path.ismount(mount_point):
        ApiResponse(msg="Mount point does not exist")

    result = run_in_thread(unmount_drive, mount_point)
    if not result.success:
        return ApiResponse(msg=f"error mounting drive {result.stderr}")

    delete_dir(mount_point)

    return ApiResponse(success=True, msg="Drive unmounted")

@router.post(
    "/drive/folders",
    response_model=ApiResponse,
    tags=["file system"],
    summary="Get the connected drives",
    description="Get all the connected and available drives",
)
async def api_get_folders_struct(body: MountPoint):
    mount_point = body.mount_point.strip()

    abs_path = os.path.realpath(os.path.join(mount_point, "/"))
    if not abs_path.startswith(os.path.realpath(mount_point)):
        return ApiResponse(msg="Path traversal not allowed")

    if not os.path.isdir(abs_path):
        return ApiResponse(msg="Path not found")

    dirs = run_in_thread(scan_dir,abs_path)

    return ApiResponse(success=True, msg=dirs, msg_type="json")

