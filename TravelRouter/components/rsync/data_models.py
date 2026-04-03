from pydantic import BaseModel, Field


class MountRequest(BaseModel):
    device: str = Field(..., description="e.g. /dev/sdb1")
    label: str = Field(
        ...,
        description="e.g. my_drive  -> mounted at /mnt/drives/my_drive",
    )


class MountPoint(BaseModel):
    mount_point: str = Field(..., description="e.g. /mnt/drives/my_drive")


class AvailableDevice(BaseModel):
    device: str = Field(..., description="e.g. /dev/sdb1")
    name: str = Field(..., description="e.g. sdb1")
    size: str = Field(..., description="e.g. 10G")
    fstype: str = Field(..., description="e.g. ext4")
    label: str | None = Field(None, description="e.g. my_drive")
    parent: str = Field(..., description="e.g. sdb")


class AvailableDevices(BaseModel):
    devices: list[AvailableDevice] = Field(..., description="e.g. /dev/sdb1")


class Dir(BaseModel):
    name: str = Field(..., description="e.g. my_drive")
    size: int = Field(..., description="e.g. 10")
    path: str = Field(..., description="e.g. /mnt/drives/my_drive")


class Dirs(BaseModel):
    dirs: list[Dir] = Field(..., description="e.g. list of directories")
