import os
import shlex
import signal
import subprocess
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone

from TravelRouter.components.rsync.data_models import JobInfo, JobStatus, RsyncProgress, StartJobRequest
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
        self._stop_requested = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._progress:  RsyncProgress | None = None
        self._progress_version = 0
        self._log:       deque[str] = deque(maxlen=2000)
        self._log_offset = 0
        self._lock       = threading.Lock()
        self._on_update  = on_update   # global event shared across all jobs

    def _append_with_offset(self, queue: deque, offset_attr: str, item) -> None:
        if queue.maxlen and len(queue) == queue.maxlen:
            setattr(self, offset_attr, getattr(self, offset_attr) + 1)
        queue.append(item)

    def append(self, line: str) -> None:
        if not line:
            return

        progress = parse_progress(line)
        with self._lock:
            if progress:
                self._progress = progress
                self._progress_version += 1
            else:
                self._append_with_offset(
                    self._log,
                    "_log_offset",
                    line,
                )

        if self._on_update is not None:
            self._on_update.set()

    def get_log(self) -> list[str]:
        with self._lock:
            return list(self._log)

    def get_log_from(self, offset: int) -> tuple[int, list[str]]:
        with self._lock:
            if offset < self._log_offset:
                offset = self._log_offset

            start_index = offset - self._log_offset
            next_offset = self._log_offset + len(self._log)
            return next_offset, list(self._log)[start_index:]

    def get_progress(self) -> RsyncProgress | None:
        with self._lock:
            return self._progress

    def get_progress_from(self, offset: int) -> tuple[int, list[RsyncProgress]]:
        with self._lock:
            if offset >= self._progress_version or self._progress is None:
                return self._progress_version, []

            return self._progress_version, [self._progress]

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

    @staticmethod
    def _terminate_process(proc: subprocess.Popen, timeout: int = 5) -> None:
        if proc.poll() is not None:
            return

        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        else:
            try:
                proc.wait(timeout=timeout)
                return
            except subprocess.TimeoutExpired:
                pass

        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()

    def start(self, req: StartJobRequest) -> Job:
        job_id = str(uuid.uuid4())
        job    = Job(job_id, req, on_update=self.any_update)
        with self._lock:
            self._jobs[job_id] = job

        worker_thread = threading.Thread(
            target=self._run,
            args=(job, self._build_cmd(req)),
            daemon=True,
        )
        job._worker_thread = worker_thread
        worker_thread.start()
        return job

    def _run(self, job: Job, cmd: list[str]) -> None:
        try:
            while True:
                if job._stop_requested.is_set():
                    break

                # --- run one attempt ---
                try:
                    with job._lock:
                        job.exit_code = None
                        job._proc = None
                        job.pid = None

                    proc = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                        start_new_session=True,
                    )

                    with job._lock:
                        job._proc = proc
                        job.pid   = proc.pid
                        stop_requested = job._stop_requested.is_set()

                    if stop_requested:
                        self._terminate_process(proc)

                    if proc.stdout is None:
                        proc.wait()
                        with job._lock:
                            job.exit_code = proc.returncode
                            job._proc = None
                        continue

                    for raw in proc.stdout:
                        if job._stop_requested.is_set():
                            self._terminate_process(proc)
                            break

                        job.append(raw.rstrip())

                    proc.stdout.close()

                    proc.wait()
                    with job._lock:
                        job.exit_code = proc.returncode
                        job._proc = None

                except Exception as exc:
                    with job._lock:
                        job.exit_code = -1
                        job._proc = None
                        job.pid = None
                    job.append(f"[error] {exc}")

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
                        f"retrying in {job.retry_delay}s …"
                    )
                    job.status = JobStatus.WAITING
                    if self.any_update:
                        self.any_update.set()

                    # sleep in small increments so a stop() call is noticed quickly
                    deadline = time.monotonic() + job.retry_delay
                    while time.monotonic() < deadline:
                        if job._stop_requested.is_set():
                            break
                        time.sleep(1)

                    if job.status == JobStatus.STOPPED:
                        break

                    job.attempt += 1
                    job.status   = JobStatus.RUNNING
                    job.exit_code = None
                    job.pid = None
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
            job._stop_requested.set()
            proc = job._proc

        if proc:
            self._terminate_process(proc)

        if self.any_update:
            self.any_update.set()
        return job

    def stop_all(self, join_timeout: float = 5.0) -> list[Job]:
        jobs = self.list_jobs()

        for job in jobs:
            self.stop(job.id)

        for job in jobs:
            worker_thread = job._worker_thread
            if worker_thread and worker_thread.is_alive():
                worker_thread.join(timeout=join_timeout)

        return jobs

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
