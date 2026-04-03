from TravelRouter.helpers.run_command import run_command, CmdStatus

def get_connected_drives()->CmdStatus:
    return run_command(["lsblk", "-J", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,FSTYPE,LABEL"])


def mount_drive(device, mount_point):
    return run_command(["mount", device, mount_point])

def unmount_drive(mount_point):
    return run_command(["umount", mount_point])
