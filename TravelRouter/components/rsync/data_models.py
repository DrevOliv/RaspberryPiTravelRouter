from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    RUNNING   = "running"
    WAITING   = "waiting"   # between retry attempts
    COMPLETED = "completed"
    FAILED    = "failed"
    STOPPED   = "stopped"


class StartJobRequest(BaseModel):
    source:      str        = Field(...,  description="e.g. /mnt/drives/media/")
    destination: str        = Field(...,  description="e.g. user@homeserver:/backup/")
    ssh_key:     str | None = Field(None, description="Path to SSH private key")
    label:       str | None = Field(None, description="Human-readable job name")
    retries:     int        = Field(0,    ge=0, le=20,  description="Max automatic retries on failure")
    retry_delay: int        = Field(30,   ge=5, le=600, description="Seconds to wait between retries")


class JobInfo(BaseModel):
    id:          str
    label:       str | None
    source:      str
    destination: str
    status:      JobStatus
    started_at:  str
    ended_at:    str | None
    exit_code:   int | None
    pid:         int | None
    attempt:     int
    retries:     int
    log_lines:   list[str] = []
