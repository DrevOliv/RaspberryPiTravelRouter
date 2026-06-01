import asyncio
import json
import logging

from fastapi.responses import StreamingResponse

from TravelRouter.components.rsync.system_api import HEARTBEAT_SECONDS


logger = logging.getLogger("uvicorn.error")


def _sse_event(event_name: str, payload: dict) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"


def _format_event(event) -> str | None:
    """Render one (name, payload) event, returning None if it can't be serialized."""
    try:
        name, payload = event
        return _sse_event(name, payload)
    except Exception:
        logger.exception("[rsync] skipping malformed SSE event")
        return None


async def _job_stream_generator(job_manager):
    """One SSE connection covering every job.

    Replays the current state of all jobs, then forwards live events from the
    subscriber queue until the client disconnects or the app shuts down.
    """
    queue, replay = job_manager.subscribe()
    try:
        for event in replay:
            chunk = _format_event(event)
            if chunk is not None:
                yield chunk

        while True:
            try:
                async with asyncio.timeout(HEARTBEAT_SECONDS):
                    event = await queue.get()
            except TimeoutError:
                yield ": heartbeat\n\n"  # keeps proxies from closing an idle stream
                continue

            if event is None:  # shutdown / dropped-subscriber sentinel
                return

            # A single malformed event is logged and skipped, not fatal to the stream.
            chunk = _format_event(event)
            if chunk is not None:
                yield chunk

    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("[rsync] Error in SSE generator")
        yield _sse_event("error", {"detail": "internal stream error"})
    finally:
        job_manager.unsubscribe(queue)


def stream_all_jobs(job_manager) -> StreamingResponse:
    return StreamingResponse(
        _job_stream_generator(job_manager),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
