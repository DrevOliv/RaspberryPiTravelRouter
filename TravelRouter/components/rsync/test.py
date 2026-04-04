import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TravelRouter.components.rsync.data_models import JobStatus, StartJobRequest
from TravelRouter.components.rsync.system_api import JobManager


SOURCE_DIR = Path("/home/server/workspace/Bilder")
DEST_DIR = Path("server@192.168.0.53:TEST")
STOP_AFTER_SECONDS = 30.0


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

    output_offset = 0
    stop_sent = False
    started_at = time.monotonic()

    while True:
        job = manager.get(job.id)
        if job is None:
            print("job not found")
            return

        output_offset, lines = job.get_output_from(output_offset)
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
