import shlex

from fastapi import APIRouter, HTTPException

from TravelRouter.config_file import DataManager
from TravelRouter.helpers.api_response import ApiResponse
from TravelRouter.helpers.run_command import run_command, run_in_thread

from TravelRouter.components.rsync.api_stream import stream_all_jobs
from TravelRouter.components.rsync.data_models import CreateRemoteFolderRequest, StartJobRequest
from TravelRouter.components.rsync.system_api import job_manager

router = APIRouter()

data_manager = DataManager()


def _ssh_command(host: str, remote_cmd: str) -> list[str]:
    """Build a non-interactive ssh invocation that runs `remote_cmd` on `host`."""
    return [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        host,
        remote_cmd,
    ]


def _configured_destination() -> tuple[str, str]:
    """Return the saved (host, destination), raising 400 if not configured yet."""
    data = data_manager.get_data()
    host = data.rsync.rsync_host.strip()
    destination = data.rsync.rsync_destination.strip()
    if not host or not destination:
        raise HTTPException(
            status_code=400,
            detail="No backup destination configured. Set it in Settings first.",
        )
    return host, destination


@router.post(
    "/rsync/jobs",
    response_model=ApiResponse,
    tags=["rsync"],
    summary="Start an rsync job",
    description="Launch an rsync transfer in the background. Returns immediately.",
)
async def api_start_job(body: StartJobRequest):
    if not body.source.strip() or not body.destination.strip():
        raise HTTPException(status_code=400, detail="Source and destination are required")
    job = job_manager.start(body)
    return ApiResponse(success=True, msg=job.to_info(), msg_type="json")


@router.get(
    "/rsync/jobs",
    response_model=ApiResponse,
    tags=["rsync"],
    summary="List all rsync jobs",
    description="Returns all jobs — running and finished — since the server started.",
)
async def api_list_jobs():
    jobs = [j.to_info() for j in job_manager.list_jobs()]
    return ApiResponse(success=True, msg=jobs, msg_type="json")


@router.delete(
    "/rsync/jobs/{job_id}",
    response_model=ApiResponse,
    tags=["rsync"],
    summary="Remove an rsync job",
    description="Stops the job if still running, then removes it from the registry.",
)
async def api_remove_job(job_id: str):
    job = await job_manager.remove(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return ApiResponse(success=True, msg=job.to_info(), msg_type="json")


@router.get(
    "/rsync/stream",
    tags=["rsync"],
    summary="Stream output from all active jobs (SSE)",
    description=(
        "Single Server-Sent Events connection that covers every job. "
        "Emits 'job_start' when a new job is detected, 'progress' and 'line' "
        "events tagged with job_id while jobs run, and 'job_done' when each "
        "job finishes. The stream stays open indefinitely."
    ),
)
async def api_stream_all_jobs():
    return stream_all_jobs(job_manager)


@router.post(
    "/rsync/remote/test",
    response_model=ApiResponse,
    tags=["rsync"],
    summary="Test the backup destination connection",
    description=(
        "Connects to the configured backup host over SSH and verifies the "
        "destination directory exists. Use this to check the remote before "
        "starting a transfer."
    ),
)
async def api_test_remote() -> ApiResponse:
    host, destination = _configured_destination()

    result = await run_in_thread(
        run_command,
        _ssh_command(host, f"test -d {shlex.quote(destination)} && echo ok"),
        15,
    )

    # Check stdout for "ok" rather than result.success: ssh may print host-key
    # notices to stderr even when the remote command succeeds.
    if "ok" in result.stdout:
        return ApiResponse(success=True, msg=f"Connected to {host} — {destination} is reachable")

    detail = (result.stderr.splitlines()[0] if result.stderr else "").strip()
    return ApiResponse(success=False, msg=detail or "Could not reach the destination directory")


@router.post(
    "/rsync/remote/folder",
    response_model=ApiResponse,
    tags=["rsync"],
    summary="Create a folder on the backup destination",
    description="Creates a new folder under the configured backup destination on the remote host.",
)
async def api_create_remote_folder(body: CreateRemoteFolderRequest) -> ApiResponse:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Folder name is required")
    if "/" in name or "\x00" in name or name in (".", ".."):
        raise HTTPException(status_code=400, detail="Folder name cannot contain slashes")

    host, destination = _configured_destination()
    remote_path = f"{destination.rstrip('/')}/{name}"

    result = await run_in_thread(
        run_command,
        _ssh_command(host, f"mkdir -p {shlex.quote(remote_path)}"),
        15,
    )
    if not result.success:
        detail = (result.stderr.splitlines()[0] if result.stderr else "").strip()
        return ApiResponse(success=False, msg=detail or "Could not create the folder")

    return ApiResponse(success=True, msg={"name": name, "path": remote_path}, msg_type="json")
