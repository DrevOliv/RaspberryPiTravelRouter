import os
from TravelRouter.components.rsync.data_models import (
    AvailableDevice,
    AvailableDevices,
    Dirs,
    Dir
)

MOUNT_BASE = "/mnt/drives"  # base dir where drives get mounted

def make_dirs(path:str)->str:
    mount_point = os.path.join(MOUNT_BASE, path)
    os.makedirs(mount_point, exist_ok=True)
    return mount_point

def delete_dir(path:str):
    mount_point = os.path.join(MOUNT_BASE, path)
    os.rmdir(mount_point)

def parse_lsblk(json_data: dict)->AvailableDevices:
    available = []

    for dev in json_data["blockdevices"]:
        # Skip loop, zram, etc.
        if dev["type"] != "disk":
            continue

        children = dev.get("children", [])

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
            ):
                available.append( AvailableDevice(
                    device=f"/dev/{child['name']}",
                    name=child["name"],
                    size=child["size"],
                    fstype=child["fstype"],
                    label=child.get("label"),
                    parent=dev["name"]
                ))

    return AvailableDevices(devices=available)

def scan_dir(abs_path:str)->Dirs:
    entries = []
    with os.scandir(abs_path) as it:
        for entry in it:
            stat = entry.stat()
            if entry.is_dir():
                entries.append(Dir(
                    name=entry.name,
                    size=stat.st_size,
                    path=os.path.join("/", entry.name)
                ))

    entries.sort(key=lambda x:  x.name.lower())
    return Dirs(dirs=entries)


