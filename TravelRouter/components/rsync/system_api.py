import asyncio
import logging
import os
import shlex
import signal
import uuid
from collections import deque
from datetime import datetime, timezone

from TravelRouter.components.rsync.data_models import JobInfo, JobStatus, RsyncProgress, StartJobRequest
from TravelRouter.components.rsync.functions import parse_progress


logger = logging.getLogger("uvicorn.error")

LOG_BUFFER_LINES = 2000
HEARTBEAT_SECONDS = 15.0
# A connected SSE client that stops reading is dropped once this many live
# events have queued up for it, so one stuck client can't grow memory forever.
SUBSCRIBER_QUEUE_MAXSIZE = 1000

_RSYNC_ERROR_MARKERS = (
    "[error]",
    "broken pipe",
    "client_loop: send disconnect",
    "failed",
    "rsync error:",
    "write error:",
)

# SSE event tuples broadcast to subscribers; `None` is the shutdown sentinel.
Event = tuple[str, dict]


def _signal_group(pid: int, sig: int) -> None:
    """Signal a child's whole process group (rsync + the ssh it spawns).

    Jobs are started with process_group=0, so the child's PGID equals its PID.
    """
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass


class Job:
    """In-memory state for a single rsync transfer. Mutated only on the event loop."""

    def __init__(self, req: StartJobRequest):
        self.id          = str(uuid.uuid4())
        self.req         = req
        self.label       = req.label
        self.source      = req.source
        self.destination = req.destination
        self.status      = JobStatus.RUNNING
        self.started_at  = datetime.now().isoformat()
        self.ended_at:   str | None = None
        self.exit_code:  int | None = None
        self.pid:        int | None = None
        self.progress:   RsyncProgress | None = None
        self._log:       deque[str] = deque(maxlen=LOG_BUFFER_LINES)
        self._proc:      asyncio.subprocess.Process | None = None
        self._task:      asyncio.Task | None = None

    def to_info(self) -> JobInfo:
        return JobInfo(
            id          = self.id,
            label       = self.label,
            source      = self.source,
            destination = self.destination,
            status      = self.status,
            started_at  = self.started_at,
            ended_at    = self.ended_at,
            exit_code   = self.exit_code,
            pid         = self.pid,
            log_lines   = list(self._log),
        )

    def record_output(self, line: str) -> Event:
        """Fold one line of rsync output into job state and return the SSE event to emit."""
        progress = parse_progress(line)
        if progress is not None:
            self.progress = progress
            return ("progress", {"job_id": self.id, **progress.model_dump()})

        self._log.append(line)
        if any(marker in line.lower() for marker in _RSYNC_ERROR_MARKERS):
            logger.error("[rsync] job_id=%s %s", self.id, line)
        return ("line", {"job_id": self.id, "text": line})


class JobManager:
    """Runs rsync jobs as asyncio tasks and fans their output out to SSE subscribers."""

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._subscribers: set[asyncio.Queue] = set()

    # ── subscriptions (SSE) ───────────────────────────────────────────────

    def subscribe(self) -> tuple[asyncio.Queue, list[Event]]:
        """Register an SSE listener.

        Returns the listener's queue plus the replay events (job_start + current
        progress) for every job that already exists. Await-free, so no live event
        can slip in between taking the snapshot and registering the queue.
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAXSIZE)
        replay: list[Event] = []
        for job in self._jobs.values():
            replay.append(("job_start", job.to_info().model_dump()))
            if job.progress is not None:
                replay.append(("progress", {"job_id": job.id, **job.progress.model_dump()}))
        self._subscribers.add(queue)
        return queue, replay

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    @staticmethod
    def _send_close(queue: asyncio.Queue) -> None:
        """Wake a stream and tell it to exit (None sentinel), even if its queue is full."""
        try:
            queue.put_nowait(None)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            queue.put_nowait(None)

    def _broadcast(self, event: Event) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("[rsync] SSE subscriber fell behind; dropping it")
                self._subscribers.discard(queue)
                self._send_close(queue)  # client will reconnect and re-sync from replay

    def _emit_status(self, name: str, job: Job, **extra) -> None:
        self._broadcast((
            name,
            {
                "job_id":    job.id,
                "status":    job.status.value,
                "exit_code": job.exit_code,
                **extra,
            },
        ))

    # ── job lifecycle ─────────────────────────────────────────────────────

    @staticmethod
    def _build_cmd(req: StartJobRequest) -> list[str]:
        ssh = (
            "ssh"
            " -o Compression=no"
            " -o ServerAliveInterval=5"
            " -o ServerAliveCountMax=3"
            " -o ConnectTimeout=15"
            " -o TCPKeepAlive=yes"
        )
        if req.ssh_key:
            ssh += f" -i {shlex.quote(req.ssh_key)}"

        return [
            "rsync", "-a",
            "--info=progress2,name0,stats2",
            "--outbuf=L",
            "--no-inc-recursive",
            "--partial-dir=.rsync-partial",
            "--mkpath",
            "--timeout=30",
            "-e", ssh,
            req.source,
            req.destination,
        ]

    def start(self, req: StartJobRequest) -> Job:
        job = Job(req)
        self._jobs[job.id] = job
        logger.info("[rsync] job_id=%s [start] %s -> %s", job.id, job.source, job.destination)
        self._broadcast(("job_start", job.to_info().model_dump()))
        job._task = asyncio.create_task(self._run(job))
        return job

    async def _run(self, job: Job) -> None:
        cmd = self._build_cmd(job.req)
        self._broadcast(job.record_output(
            f"[start] job '{job.label or job.id}' {job.source} -> {job.destination}"
        ))
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                process_group=0,  # own group so we can signal rsync + its ssh child together
            )
            job._proc = proc
            job.pid = proc.pid
            self._emit_status("job_update", job, pid=job.pid)

            assert proc.stdout is not None
            # rsync's --info=progress2 rewrites one line in place using carriage
            # returns ('\r'), emitting a real '\n' only when a file/the transfer
            # finishes. readline() (async for) splits on '\n' only, so live
            # progress would buffer until the end. Read in chunks and treat both
            # '\r' and '\n' as line terminators so each update is emitted live.
            buf = b""
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                buf = (buf + chunk).replace(b"\r", b"\n")
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = line.decode(errors="replace").rstrip()
                    if text:
                        self._broadcast(job.record_output(text))
            text = buf.decode(errors="replace").rstrip()
            if text:
                self._broadcast(job.record_output(text))

            job.exit_code = await proc.wait()

        except asyncio.CancelledError:
            await self._terminate(job)
            raise
        except Exception as exc:
            logger.exception("[rsync] job_id=%s unexpected error", job.id)
            job.exit_code = -1
            self._broadcast(job.record_output(f"[error] {exc}"))
        finally:
            job._proc = None
            job.ended_at = datetime.now(timezone.utc).isoformat()
            if job.status == JobStatus.RUNNING:  # not already STOPPED by stop()/shutdown()
                job.status = JobStatus.COMPLETED if job.exit_code == 0 else JobStatus.FAILED
            if job.status == JobStatus.FAILED:
                logger.error("[rsync] job_id=%s failed exit_code=%s", job.id, job.exit_code)
            self._emit_status("job_done", job, ended_at=job.ended_at)

    @staticmethod
    async def _terminate(job: Job, timeout: float = 5.0) -> None:
        """SIGTERM the job's process group, escalating to SIGKILL if it lingers."""
        proc = job._proc
        if proc is None or proc.returncode is not None:
            return

        _signal_group(proc.pid, signal.SIGTERM)
        try:
            async with asyncio.timeout(timeout):
                await proc.wait()
        except TimeoutError:
            _signal_group(proc.pid, signal.SIGKILL)
            try:
                await proc.wait()
            except ProcessLookupError:
                pass

    async def stop(self, job_id: str) -> Job | None:
        job = self._jobs.get(job_id)
        if job is None or job.status != JobStatus.RUNNING:
            return None
        job.status = JobStatus.STOPPED
        await self._terminate(job)
        self._emit_status("job_update", job, pid=job.pid)
        return job

    async def remove(self, job_id: str) -> Job | None:
        """Stop the job if still active, wait for its task to finish, then drop it."""
        job = self._jobs.get(job_id)
        if job is None:
            return None

        await self.stop(job_id)  # no-op if already finished
        if job._task and not job._task.done():
            try:
                await asyncio.wait_for(asyncio.shield(job._task), timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                pass

        return self._jobs.pop(job_id, None)

    async def shutdown(self) -> None:
        """Terminate every running job and close all open SSE streams (app shutdown)."""
        for job in list(self._jobs.values()):
            if job.status == JobStatus.RUNNING:
                job.status = JobStatus.STOPPED
                await self._terminate(job)

        tasks = [job._task for job in self._jobs.values() if job._task and not job._task.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        for queue in list(self._subscribers):
            self._send_close(queue)  # sentinel: tells each stream generator to exit

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        return list(self._jobs.values())


# Module-level singleton — shared across all requests
job_manager = JobManager()
