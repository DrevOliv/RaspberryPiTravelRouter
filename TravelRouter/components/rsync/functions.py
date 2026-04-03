import os

from TravelRouter.components.rsync.data_models import (
    AvailableDevice,
    AvailableDevices,
    Dirs,
    Dir,
)

MOUNT_BASE = "/mnt/drives"  # base dir where drives get mounted


def resolve_mount_path(path: str) -> str:
    requested_path = path.strip()
    if not requested_path:
        raise ValueError("Mount path cannot be empty")

    if not os.path.isabs(requested_path):
        requested_path = os.path.join(MOUNT_BASE, requested_path)

    mount_base = os.path.realpath(MOUNT_BASE)
    mount_point = os.path.realpath(requested_path)
    if os.path.commonpath([mount_base, mount_point]) != mount_base:
        raise ValueError("Path traversal not allowed")

    return mount_point


def make_dirs(path: str) -> str:
    mount_point = resolve_mount_path(path)
    os.makedirs(mount_point, exist_ok=True)
    return mount_point


def delete_dir(path: str) -> None:
    mount_point = resolve_mount_path(path)
    if mount_point == os.path.realpath(MOUNT_BASE):
        raise ValueError("Cannot remove mount root")

    os.rmdir(mount_point)


def parse_lsblk(json_data: dict) -> AvailableDevices:
    available = []

    for dev in json_data.get("blockdevices", []):
        # Skip loop, zram, etc.
        if dev.get("type") != "disk":
            continue

        children = dev.get("children") or []

        # Detect system disk
        is_system_disk = any(
            child.get("mountpoint") in ["/", "/boot", "/boot/firmware"]
            for child in children
        )

        if is_system_disk:
            continue

        for child in children:
            # Only show real partitions with filesystems that are not mounted
            if (
                child.get("type") == "part"
                and not child.get("mountpoint")
                and child.get("fstype")
                and child.get("fstype") != "swap"
                and child.get("name")
                and child.get("size")
                and dev.get("name")
            ):
                available.append(
                    AvailableDevice(
                        device=f"/dev/{child['name']}",
                        name=child["name"],
                        size=child["size"],
                        fstype=child["fstype"],
                        label=child.get("label"),
                        parent=dev["name"],
                    )
                )

    return AvailableDevices(devices=available)


def scan_dir(abs_path: str) -> Dirs:
    safe_path = resolve_mount_path(abs_path)
    entries = []
    with os.scandir(safe_path) as it:
        for entry in it:
            if entry.is_dir(follow_symlinks=False):
                stat = entry.stat(follow_symlinks=False)
                entries.append(
                    Dir(
                        name=entry.name,
                        size=stat.st_size,
                        path=os.path.join(safe_path, entry.name),
                    )
                )

    entries.sort(key=lambda x: x.name.lower())
    return Dirs(dirs=entries)

