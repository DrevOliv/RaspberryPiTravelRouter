import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from TravelRouter.helpers.api_response import ApiResponse

from TravelRouter.components.rsync.data_models import StartJobRequest
from TravelRouter.components.rsync.functions import parse_progress
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
    summary="Stop a running rsync job",
    description="Send SIGTERM to the rsync process.",
)
async def api_stop_job(job_id: str):
    job = job_manager.get(job_id)
    if job is None:
        return ApiResponse(msg=f"Job {job_id} not found")

    stopped = job_manager.stop(job_id)
    if stopped is None:
        return ApiResponse(msg=f"Job cannot be stopped (status={job.status.value})")

    return ApiResponse(success=True, msg=stopped.to_info(), msg_type="json")


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
    async def generator():
        # lines already sent per job_id
        sent: dict[str, int] = {}
        # jobs we have already emitted job_done for
        finished: set[str] = set()

        while True:
            job_manager.any_update.clear()

            for job in job_manager.list_jobs():
                # First time we see this job — announce it and replay buffer
                if job.id not in sent:
                    sent[job.id] = 0
                    yield (
                        f"event: job_start\n"
                        f"data: {json.dumps(job.to_info().model_dump())}\n\n"
                    )

                current = job.get_output()
                for line in current[sent[job.id]:]:
                    progress = parse_progress(line)
                    if progress:
                        yield f"event: progress\ndata: {json.dumps({'job_id': job.id, **progress})}\n\n"
                    else:
                        yield f"event: line\ndata: {json.dumps({'job_id': job.id, 'text': line})}\n\n"
                sent[job.id] = len(current)

                if job.id not in finished and job.status.value not in ("running", "waiting"):
                    finished.add(job.id)
                    yield (
                        f"event: job_done\n"
                        f"data: {json.dumps({'job_id': job.id, 'status': job.status.value, 'exit_code': job.exit_code})}\n\n"
                    )

            yield ": heartbeat\n\n"

            # Block until any job produces output or 0.5 s elapses
            await asyncio.to_thread(job_manager.any_update.wait, 0.5)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
