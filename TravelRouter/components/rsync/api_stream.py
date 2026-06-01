import asyncio
import json
import logging

from fastapi.responses import StreamingResponse


logger = logging.getLogger("uvicorn.error")

_ACTIVE_STATUSES = {"running", "waiting"}

# Set by the app lifespan on shutdown so every active SSE generator exits cleanly.
_shutdown_event = asyncio.Event()


def signal_shutdown() -> None:
    """Call this from the app lifespan finalizer to close all SSE streams."""
    _shutdown_event.set()


def _sse_event(event_name: str, payload: dict) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"


def _stream_job_updates(job, sent_logs: dict[str, int]):
    progress = job.get_progress()
    if progress is not None:
        yield _sse_event("progress", {"job_id": job.id, **progress.model_dump()})

    sent_logs[job.id], log_lines = job.get_log_from(sent_logs[job.id])
    for line in log_lines:
        yield _sse_event("line", {"job_id": job.id, "text": line})


async def _job_stream_generator(job_manager):
    sent_logs: dict[str, int] = {}
    sent_meta: dict[str, tuple] = {}   # job_id -> (status, exit_code)
    finished: set[str] = set()

    while True:
        if _shutdown_event.is_set():
            return

        # Clear before scanning so any update that arrives mid-loop wakes the next wait immediately.
        job_manager.any_update.clear()
        try:
            for job in job_manager.list_jobs():
                if job.id not in sent_logs:
                    # Atomic snapshot: job_start log and the offset are consistent.
                    info, log_offset = job.snapshot()
                    sent_logs[job.id] = log_offset
                    sent_meta[job.id] = (info.status.value, info.exit_code)
                    yield _sse_event("job_start", info.model_dump())

                for event_chunk in _stream_job_updates(job, sent_logs):
                    yield event_chunk

                if job.id in finished or job.status.value in _ACTIVE_STATUSES:
                    # Emit job_update when status/exit_code changes mid-run.
                    current_meta = (job.status.value, job.exit_code)
                    if sent_meta.get(job.id) != current_meta:
                        sent_meta[job.id] = current_meta
                        yield _sse_event("job_update", {
                            "job_id":    job.id,
                            "status":    job.status.value,
                            "exit_code": job.exit_code,
                            "pid":       job.pid,
                        })
                    continue

                # Final flush before marking done.
                for event_chunk in _stream_job_updates(job, sent_logs):
                    yield event_chunk

                finished.add(job.id)
                yield _sse_event(
                    "job_done",
                    {
                        "job_id":    job.id,
                        "status":    job.status.value,
                        "exit_code": job.exit_code,
                        "ended_at":  job.ended_at,
                    },
                )

            yield ": heartbeat\n\n"

        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("[rsync] Error in SSE generator")
            yield _sse_event("error", {"detail": "internal stream error"})

        # Wait for a job update, shutdown signal, or 500 ms timeout — whichever comes first.
        try:
            update_task   = asyncio.ensure_future(asyncio.to_thread(job_manager.any_update.wait, 0.5))
            shutdown_task = asyncio.ensure_future(_shutdown_event.wait())
            try:
                await asyncio.wait(
                    [update_task, shutdown_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                for t in (update_task, shutdown_task):
                    if not t.done():
                        t.cancel()
        except asyncio.CancelledError:
            return

        if _shutdown_event.is_set():
            return


def stream_all_jobs(job_manager) -> StreamingResponse:
    return StreamingResponse(
        _job_stream_generator(job_manager),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
