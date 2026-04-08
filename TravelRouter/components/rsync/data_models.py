from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    STOPPED   = "stopped"


class StartJobRequest(BaseModel):
    source:      str        = Field(...,  description="e.g. /mnt/drives/media/")
    destination: str        = Field(...,  description="e.g. user@homeserver:/backup/")
    ssh_key:     str | None = Field(None, description="Path to SSH private key")
    label:       str | None = Field(None, description="Human-readable job name")


class RsyncProgress(BaseModel):
    bytes:   int
    percent: int
    speed:   str
    eta:     str


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
    log_lines:   list[str] = []
