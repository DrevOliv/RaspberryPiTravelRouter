from fastapi import APIRouter, HTTPException

from TravelRouter.helpers.api_response import ApiResponse

from TravelRouter.components.rsync.api_stream import stream_all_jobs
from TravelRouter.components.rsync.data_models import StartJobRequest
from TravelRouter.components.rsync.system_api import job_manager

router = APIRouter()


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
