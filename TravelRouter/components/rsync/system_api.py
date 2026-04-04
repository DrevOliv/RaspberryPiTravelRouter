import os
import shlex
import signal
import subprocess
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone

from TravelRouter.components.rsync.data_models import JobInfo, JobStatus, StartJobRequest
from TravelRouter.components.rsync.functions import parse_progress


class Job:
    def __init__(self, job_id: str, req: StartJobRequest, on_update: threading.Event | None = None):
        self.id          = job_id
        self.label       = req.label
        self.source      = req.source
        self.destination = req.destination
        self.retries     = req.retries
        self.retry_delay = req.retry_delay
        self.attempt     = 1
        self.status      = JobStatus.RUNNING
        self.started_at  = datetime.now(timezone.utc).isoformat()
        self.ended_at:   str | None = None
        self.exit_code:  int | None = None
        self.pid:        int | None = None
        self._proc:      subprocess.Popen | None = None
        self._output:    deque[str] = deque(maxlen=2000)
        self._output_offset = 0
        self._log:       deque[str] = deque(maxlen=200)  # non-progress lines only
        self._lock       = threading.Lock()
        self._on_update  = on_update   # global event shared across all jobs

    def append(self, line: str, important: bool = False) -> None:
        with self._lock:
            if self._output.maxlen and len(self._output) == self._output.maxlen:
                self._output_offset += 1
            self._output.append(line)
            if important:
                self._log.append(line)
        if self._on_update is not None:
            self._on_update.set()

    def get_log(self) -> list[str]:
        with self._lock:
            return list(self._log)

    def get_output(self) -> list[str]:
        with self._lock:
            return list(self._output)

    def get_output_from(self, offset: int) -> tuple[int, list[str]]:
        with self._lock:
            if offset < self._output_offset:
                offset = self._output_offset

            start_index = offset - self._output_offset
            next_offset = self._output_offset + len(self._output)
            return next_offset, list(self._output)[start_index:]

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
            attempt     = self.attempt,
            retries     = self.retries,
            log_lines   = self.get_log(),
        )


class JobManager:
    def __init__(self):
        self._jobs:       dict[str, Job] = {}
        self._lock        = threading.Lock()
        self.any_update   = threading.Event()   # set whenever any job appends a line

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
        job_id = str(uuid.uuid4())
        job    = Job(job_id, req, on_update=self.any_update)
        with self._lock:
            self._jobs[job_id] = job
        threading.Thread(
            target=self._run,
            args=(job, self._build_cmd(req)),
            daemon=True,
        ).start()
        return job

    def _run(self, job: Job, cmd: list[str]) -> None:
        try:
            while True:
                # --- run one attempt ---
                try:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                        start_new_session=True,
                    )
                    job._proc = proc
                    job.pid   = proc.pid

                    for raw in proc.stdout:
                        line = raw.rstrip()
                        job.append(line, important=not parse_progress(line))
                    proc.stdout.close()

                    proc.wait()
                    job.exit_code = proc.returncode

                except Exception as exc:
                    job.exit_code = -1
                    job.append(f"[error] {exc}", important=True)

                # --- decide what to do next ---
                if job.status == JobStatus.STOPPED:
                    # user cancelled — honour it regardless of exit code
                    break

                if job.exit_code == 0:
                    job.status = JobStatus.COMPLETED
                    break

                # failure path
                if job.attempt <= job.retries:
                    job.append(
                        f"[retry] attempt {job.attempt} failed"
                        f" (exit {job.exit_code}), "
                        f"retrying in {job.retry_delay}s …",
                        important=True,
                    )
                    job.status = JobStatus.WAITING
                    if self.any_update:
                        self.any_update.set()

                    # sleep in small increments so a stop() call is noticed quickly
                    deadline = time.monotonic() + job.retry_delay
                    while time.monotonic() < deadline:
                        if job.status == JobStatus.STOPPED:
                            break
                        time.sleep(1)

                    if job.status == JobStatus.STOPPED:
                        break

                    job.attempt += 1
                    job.status   = JobStatus.RUNNING
                    if self.any_update:
                        self.any_update.set()
                    continue

                # no retries left
                job.status = JobStatus.FAILED
                break

        finally:
            job.ended_at = datetime.now(timezone.utc).isoformat()
            if self.any_update:
                self.any_update.set()

    def stop(self, job_id: str) -> Job | None:
        job = self._get(job_id)
        if job is None:
            return None
        with job._lock:
            if job.status not in (JobStatus.RUNNING, JobStatus.WAITING):
                return None
            job.status = JobStatus.STOPPED
        proc = job._proc
        if proc and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            else:
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    proc.wait()
        if self.any_update:
            self.any_update.set()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._get(job_id)

    def list_jobs(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def _get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)


# Module-level singleton — shared across all requests
job_manager = JobManager()
