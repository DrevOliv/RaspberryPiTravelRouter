"""
rsync-manager — FastAPI rsync job manager (API only)

POST   /jobs             – start a job
GET    /jobs             – list all jobs
GET    /jobs/{id}        – job detail + buffered output
DELETE /jobs/{id}        – stop a running job
GET    /jobs/{id}/stream – SSE live output stream
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import signal
import subprocess
import threading
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# ─── Config ──────────────────────────────────────────────────────────────────

STATE_FILE          = Path("jobs_state.json")
OUTPUT_BUFFER_LINES = 2000


# ─── Models ──────────────────────────────────────────────────────────────────

class JobStatus(str, Enum):
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    STOPPED   = "stopped"


class StartJobRequest(BaseModel):
    source:           str            = Field(...,  example="/path/to/media/")
    destination:      str            = Field(...,  example="user@homeserver:/backup/")
    ssh_key:          Optional[str]  = Field(None, example="/home/user/.ssh/id_rsa")
    extra_rsync_args: list[str]      = Field(default_factory=list)
    label:            Optional[str]  = Field(None)


class JobInfo(BaseModel):
    id:           str
    label:        Optional[str]
    source:       str
    destination:  str
    status:       JobStatus
    started_at:   str
    ended_at:     Optional[str]
    exit_code:    Optional[int]
    pid:          Optional[int]
    output_lines: list[str] = []


# ─── Job ─────────────────────────────────────────────────────────────────────

class Job:
    def __init__(self, job_id: str, req: StartJobRequest):
        self.id          = job_id
        self.label       = req.label
        self.source      = req.source
        self.destination = req.destination
        self.status      = JobStatus.RUNNING
        self.started_at  = datetime.now(timezone.utc).isoformat()
        self.ended_at:   Optional[str] = None
        self.exit_code:  Optional[int] = None
        self.pid:        Optional[int] = None
        self._output:    deque[str]    = deque(maxlen=OUTPUT_BUFFER_LINES)
        self._lock       = threading.Lock()
        self._proc:      Optional[subprocess.Popen] = None
        self._new_line   = asyncio.Event()

    def append(self, line: str, loop: asyncio.AbstractEventLoop):
        with self._lock:
            self._output.append(line)
        loop.call_soon_threadsafe(self._new_line.set)

    def get_output(self) -> list[str]:
        with self._lock:
            return list(self._output)

    def to_info(self, include_output: bool = False) -> JobInfo:
        return JobInfo(
            id           = self.id,
            label        = self.label,
            source       = self.source,
            destination  = self.destination,
            status       = self.status,
            started_at   = self.started_at,
            ended_at     = self.ended_at,
            exit_code    = self.exit_code,
            pid          = self.pid,
            output_lines = self.get_output() if include_output else [],
        )

    def to_dict(self) -> dict:
        d = self.to_info(include_output=True).model_dump()
        d["output"] = d.pop("output_lines")
        return d


# ─── Job manager ─────────────────────────────────────────────────────────────

class JobManager:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock  = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

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
            *req.extra_rsync_args,
            req.source,
            req.destination,
        ]

    def start(self, req: StartJobRequest) -> Job:
        job_id = str(uuid.uuid4())
        job    = Job(job_id, req)
        with self._lock:
            self._jobs[job_id] = job
        threading.Thread(target=self._run, args=(job, self._build_cmd(req)), daemon=True).start()
        return job

    def _run(self, job: Job, cmd: list[str]):
        loop = self._loop
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                preexec_fn=os.setsid,  # own process group for clean kill
            )
            job._proc = proc
            job.pid   = proc.pid
            job.append(f"[manager] pid={proc.pid}  cmd={shlex.join(cmd)}", loop)

            for line in proc.stdout:
                job.append(line.rstrip(), loop)

            proc.wait()
            job.exit_code = proc.returncode
            if job.status == JobStatus.RUNNING:
                job.status = JobStatus.COMPLETED if proc.returncode == 0 else JobStatus.FAILED
            job.ended_at = datetime.now(timezone.utc).isoformat()
            job.append(f"[manager] done  exit_code={proc.returncode}  status={job.status.value}", loop)

        except Exception as exc:
            job.status   = JobStatus.FAILED
            job.ended_at = datetime.now(timezone.utc).isoformat()
            job.append(f"[manager] exception: {exc}", loop)
        finally:
            self._persist()

    def stop(self, job_id: str) -> Job:
        job = self._get(job_id)
        if job.status != JobStatus.RUNNING:
            raise HTTPException(400, f"Job is not running (status={job.status.value})")
        job.status = JobStatus.STOPPED
        if job._proc and job._proc.poll() is None:
            try:
                os.killpg(os.getpgid(job._proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
        return job

    def list_jobs(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def _get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            raise HTTPException(404, f"Job {job_id} not found")
        return job

    def get(self, job_id: str) -> Job:
        return self._get(job_id)

    def _persist(self):
        try:
            with self._lock:
                data = [j.to_dict() for j in self._jobs.values()]
            STATE_FILE.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def load_state(self):
        if not STATE_FILE.exists():
            return
        try:
            for d in json.loads(STATE_FILE.read_text()):
                if d["status"] == JobStatus.RUNNING.value:
                    d["status"] = JobStatus.FAILED.value  # was mid-run when server died
                req         = StartJobRequest(source=d["source"], destination=d["destination"], label=d.get("label"))
                job         = Job(d["id"], req)
                job.status  = JobStatus(d["status"])
                job.started_at = d["started_at"]
                job.ended_at   = d.get("ended_at")
                job.exit_code  = d.get("exit_code")
                job.pid        = d.get("pid")
                for line in d.get("output", []):
                    job._output.append(line)
                self._jobs[job.id] = job
        except Exception:
            pass


# ─── App ─────────────────────────────────────────────────────────────────────

manager = JobManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager.set_loop(asyncio.get_running_loop())
    manager.load_state()
    yield


app = FastAPI(title="rsync-manager", version="1.0.0", lifespan=lifespan)


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.post("/jobs", response_model=JobInfo, status_code=201)
def start_job(req: StartJobRequest):
    """Start a new rsync job. Returns immediately; rsync runs in the background."""
    return manager.start(req).to_info()


@app.get("/jobs", response_model=list[JobInfo])
def list_jobs():
    """List every job — running and finished."""
    return [j.to_info() for j in manager.list_jobs()]


@app.get("/jobs/{job_id}", response_model=JobInfo)
def get_job(job_id: str):
    """Job detail + last 2000 lines of output."""
    return manager.get(job_id).to_info(include_output=True)


@app.delete("/jobs/{job_id}", response_model=JobInfo)
def stop_job(job_id: str):
    """Send SIGTERM to a running job."""
    return manager.stop(job_id).to_info()


@app.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    """
    Server-Sent Events stream.
    Replays the buffered output then follows new lines live until the job ends.
    """
    job = manager.get(job_id)

    async def generator() -> AsyncGenerator[str, None]:
        sent = 0

        # replay buffer
        for line in job.get_output():
            yield f"data: {json.dumps(line)}\n\n"
            sent += 1

        # follow live output
        while job.status == JobStatus.RUNNING:
            job._new_line.clear()
            current = job.get_output()
            for line in current[sent:]:
                yield f"data: {json.dumps(line)}\n\n"
            sent = len(current)
            try:
                await asyncio.wait_for(job._new_line.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass
            yield ": heartbeat\n\n"  # keeps proxies from timing out

        # flush anything written after status changed
        for line in job.get_output()[sent:]:
            yield f"data: {json.dumps(line)}\n\n"

        yield f"event: done\ndata: {json.dumps({'status': job.status.value, 'exit_code': job.exit_code})}\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )