import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from TravelRouter.helpers.api_response import ApiResponse

from TravelRouter.components.rsync.data_models import StartJobRequest
from TravelRouter.components.rsync.functions import parse_progress
from TravelRouter.components.rsync.system_api import job_manager

logger = logging.getLogger(__name__)

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
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    stopped = job_manager.stop(job_id)
    if stopped is None:
        raise HTTPException(status_code=409, detail=f"Job cannot be stopped (status={job.status.value})")

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
    # Each client gets its own wakeup event so clearing one client's event
    # never delays another client.
    client_event = asyncio.Event()

    def _notify():
        # Called from the background thread via call_soon_threadsafe so it's
        # safe to touch the asyncio event from a non-async context.
        client_event.set()

    # Patch into the job manager's threading.Event by wrapping it.
    # We piggyback on any_update via a polling approach — the client_event is
    # driven by the same 0.5 s timeout so we don't need a hook into job_manager.

    async def generator():
        # lines already sent per job_id
        sent: dict[str, int] = {}
        # jobs we have already emitted job_done for
        finished: set[str] = set()

        while True:
            try:
                # Drain the job manager's threading event into our per-client
                # asyncio event before reading state, so we can't miss a wakeup
                # that arrives during iteration.
                client_event.clear()

                for job in job_manager.list_jobs():
                    # First time we see this job — announce it
                    if job.id not in sent:
                        sent[job.id] = 0
                        yield (
                            f"event: job_start\n"
                            f"data: {json.dumps(job.to_info().model_dump())}\n\n"
                        )

                    sent[job.id], new_lines = job.get_output_from(sent[job.id])
                    for line in new_lines:
                        progress = parse_progress(line)
                        if progress:
                            yield f"event: progress\ndata: {json.dumps({'job_id': job.id, **progress})}\n\n"
                        else:
                            yield f"event: line\ndata: {json.dumps({'job_id': job.id, 'text': line})}\n\n"

                    if job.id not in finished and job.status.value not in ("running", "waiting"):
                        # Flush any lines that arrived between the last get_output_from
                        # and the status check before declaring the job done.
                        sent[job.id], trailing = job.get_output_from(sent[job.id])
                        for line in trailing:
                            progress = parse_progress(line)
                            if progress:
                                yield f"event: progress\ndata: {json.dumps({'job_id': job.id, **progress})}\n\n"
                            else:
                                yield f"event: line\ndata: {json.dumps({'job_id': job.id, 'text': line})}\n\n"

                        finished.add(job.id)
                        yield (
                            f"event: job_done\n"
                            f"data: {json.dumps({'job_id': job.id, 'status': job.status.value, 'exit_code': job.exit_code})}\n\n"
                        )

                yield ": heartbeat\n\n"

            except Exception:
                logger.exception("Error in SSE generator")
                yield f"event: error\ndata: {json.dumps({'detail': 'internal stream error'})}\n\n"

            # Wait until any job produces output or 0.5 s elapses.
            # Using asyncio.wait_for on asyncio.to_thread so that client
            # disconnects (generator cancellation) propagate cleanly.
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(job_manager.any_update.wait, 0.5),
                    timeout=1.0,
                )
            except (asyncio.TimeoutError, Exception):
                pass

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
