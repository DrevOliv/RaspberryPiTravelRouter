import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TravelRouter.components.rsync.data_models import JobStatus, StartJobRequest
from TravelRouter.components.rsync.system_api import JobManager


SOURCE_DIR = Path("/home/server/workspace/Bilder")
DEST_DIR = Path("server@192.168.0.53:TESTING")
STOP_AFTER_SECONDS = 1000.0


def main() -> None:

    manager = JobManager()
    job = manager.start(
        StartJobRequest(
            source=f"{SOURCE_DIR}/",
            destination=f"{DEST_DIR}/",
            label="jobmanager-test",
            retries=5,
            retry_delay=5,
        )
    )

    print(f"started job: {job.id}")

    progress_offset = 0
    log_offset = 0
    stop_sent = False
    started_at = time.monotonic()

    while True:
        job = manager.get(job.id)
        if job is None:
            print("job not found")
            return

        progress_offset, progress_items = job.get_progress_from(progress_offset)
        for progress in progress_items:
            print(
                f"progress: {progress.percent}% "
                f"{progress.bytes} bytes "
                f"{progress.speed} "
                f"eta={progress.eta}"
            )

        log_offset, lines = job.get_log_from(log_offset)
        for line in lines:
            print(line)

        print(
            f"status={job.status.value} pid={job.pid} "
            f"attempt={job.attempt} exit_code={job.exit_code}"
        )

        if (
            not stop_sent
            and STOP_AFTER_SECONDS is not None
            and job.status == JobStatus.RUNNING
            and time.monotonic() - started_at >= STOP_AFTER_SECONDS
        ):
            print("calling manager.stop(...)")
            manager.stop(job.id)
            stop_sent = True

        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.STOPPED):
            print("job finished")
            break

        time.sleep(0.5)


if __name__ == "__main__":
    main()
