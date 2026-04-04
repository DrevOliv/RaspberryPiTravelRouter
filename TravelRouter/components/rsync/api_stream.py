import asyncio
import json
import logging

from fastapi.responses import StreamingResponse


logger = logging.getLogger("uvicorn.error")

_ACTIVE_STATUSES = {"running", "waiting"}


def _sse_event(event_name: str, payload: dict) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"


def _stream_job_updates(job, sent_progress: dict[str, int], sent_logs: dict[str, int]):
    sent_progress[job.id], progress_items = job.get_progress_from(sent_progress[job.id])
    for progress in progress_items:
        yield _sse_event(
            "progress",
            {"job_id": job.id, **progress.model_dump()},
        )

    sent_logs[job.id], log_lines = job.get_log_from(sent_logs[job.id])
    for line in log_lines:
        yield _sse_event("line", {"job_id": job.id, "text": line})


async def _job_stream_generator(job_manager):
    sent_progress: dict[str, int] = {}
    sent_logs: dict[str, int] = {}
    finished: set[str] = set()

    while True:
        # Clear before scanning so any update that arrives mid-loop wakes the next wait immediately.
        job_manager.any_update.clear()
        try:
            for job in job_manager.list_jobs():
                if job.id not in sent_logs:
                    # Atomic snapshot: job_start log and the offsets are consistent.
                    info, log_offset, progress_version = job.snapshot()
                    sent_logs[job.id]     = log_offset
                    sent_progress[job.id] = progress_version
                    yield _sse_event("job_start", info.model_dump())

                for event_chunk in _stream_job_updates(job, sent_progress, sent_logs):
                    yield event_chunk

                if job.id in finished or job.status.value in _ACTIVE_STATUSES:
                    continue

                # Final flush before marking done.
                for event_chunk in _stream_job_updates(job, sent_progress, sent_logs):
                    yield event_chunk

                finished.add(job.id)
                yield _sse_event(
                    "job_done",
                    {
                        "job_id":   job.id,
                        "status":   job.status.value,
                        "exit_code": job.exit_code,
                        "ended_at": job.ended_at,
                    },
                )

            yield ": heartbeat\n\n"

        except Exception:
            logger.exception("[rsync] Error in SSE generator")
            yield _sse_event("error", {"detail": "internal stream error"})

        # Block until a job signals an update, or 500 ms elapse.
        await asyncio.to_thread(job_manager.any_update.wait, 0.5)


def stream_all_jobs(job_manager) -> StreamingResponse:
    return StreamingResponse(
        _job_stream_generator(job_manager),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
