import os
import shlex
from pathlib import Path

from fastapi import APIRouter

from TravelRouter.components.settings.data_models import (
    SetRsyncDestinationRequest,
    SettingsConfigResponse,
    SettingsImport,
    SshKeyResponse,
)
from TravelRouter.config_file import DataManager
from TravelRouter.config_file.data_models import DataModels
from TravelRouter.helpers.api_response import ApiResponse
from TravelRouter.helpers.run_command import CmdStatus, run_command, run_in_thread

router = APIRouter()

data_manager = DataManager()

# SSH identity this device uses for rsync-over-SSH backups. The remote server
# must hold the matching PUBLIC key in its authorized_keys. ssh/rsync pick up
# these default key names automatically (no -i needed).
_SSH_DIR = Path(os.getenv("TRAVELROUTER_SSH_DIR", str(Path.home() / ".ssh")))
_DEFAULT_KEY_NAMES = ("id_ed25519", "id_ecdsa", "id_rsa")
_MANAGED_KEY = _SSH_DIR / "id_ed25519"  # created by generate when none exists


def _existing_public_key() -> Path | None:
    for name in _DEFAULT_KEY_NAMES:
        private = _SSH_DIR / name
        public = _SSH_DIR / f"{name}.pub"
        if private.exists() and public.exists():
            return public
    return None


def _read_ssh_key() -> SshKeyResponse:
    public = _existing_public_key()
    if public is None:
        return SshKeyResponse(exists=False)
    fingerprint = run_command(["ssh-keygen", "-lf", str(public)])
    return SshKeyResponse(
        exists=True,
        public_key=public.read_text(encoding="utf-8").strip(),
        fingerprint=fingerprint.stdout if fingerprint.success else "",
    )


def _generate_ssh_key() -> CmdStatus:
    _SSH_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(_SSH_DIR, 0o700)
    return run_command([
        "ssh-keygen", "-t", "ed25519", "-q",
        "-N", "",                # no passphrase — unattended backups
        "-C", "travelrouter",
        "-f", str(_MANAGED_KEY),
    ])


@router.get(
    "/settings/config",
    response_model=ApiResponse,
    tags=["settings"],
    summary="Get current settings",
    description="Returns the current AP SSID, AP password, saved Tailscale exit node, and rsync destination.",
)
async def api_settings_config() -> ApiResponse:
    settings = data_manager.get_data()
    return ApiResponse(
        success=True,
        msg=SettingsConfigResponse(
            ap_ssid=settings.wifi.ap_ssid,
            ap_password=settings.wifi.ap_password,
            exit_node=settings.tailscale.exit_node,
            rsync_host=settings.rsync.rsync_host,
            rsync_destination=settings.rsync.rsync_destination,
        ),
        msg_type="json",
    )


@router.post(
    "/settings/rsync/destination",
    response_model=ApiResponse,
    tags=["settings"],
    summary="Set and verify rsync backup destination",
    description=(
        "Saves the remote host (user@hostname) and destination path, then verifies "
        "reachability and directory existence via SSH before saving. "
        "Requires SSH key authentication to be configured on the Pi."
    ),
)
async def api_set_rsync_destination(body: SetRsyncDestinationRequest) -> ApiResponse:
    if not body.rsync_host.strip() or not body.rsync_destination.strip():
        return ApiResponse(success=False, msg="Host and destination path are required")

    result = await run_in_thread(
        run_command,
        [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            body.rsync_host,
            f"test -d {shlex.quote(body.rsync_destination)} && echo ok",
        ],
        15,
    )

    # Check stdout for "ok" — don't rely on result.success since SSH may
    # write host-key warnings to stderr even when the command succeeds.
    if "ok" not in result.stdout:
        detail = (result.stderr.splitlines()[0] if result.stderr else "").strip()
        msg = detail or "SSH connection failed or directory not found"
        return ApiResponse(success=False, msg=msg)

    data = data_manager.get_data()
    data.rsync.rsync_host = body.rsync_host.strip()
    data.rsync.rsync_destination = body.rsync_destination.strip()
    data_manager.set_data(data)

    return ApiResponse(success=True, msg="Destination verified and saved")


@router.get(
    "/settings/ssh-key",
    response_model=ApiResponse,
    tags=["settings"],
    summary="Get this device's backup SSH public key",
    description=(
        "Returns whether this device has an SSH key for backups and, if so, the "
        "public key to copy into the remote server's authorized_keys."
    ),
)
async def api_get_ssh_key() -> ApiResponse:
    return ApiResponse(success=True, msg=await run_in_thread(_read_ssh_key), msg_type="json")


@router.post(
    "/settings/ssh-key/generate",
    response_model=ApiResponse,
    tags=["settings"],
    summary="Create this device's backup SSH key",
    description=(
        "Generates an ed25519 SSH key if this device doesn't already have one, "
        "then returns the public key. An existing key is left untouched."
    ),
)
async def api_generate_ssh_key() -> ApiResponse:
    existing = await run_in_thread(_read_ssh_key)
    if existing.exists:
        return ApiResponse(success=True, msg=existing, msg_type="json")

    result = await run_in_thread(_generate_ssh_key)
    if not result.success:
        return ApiResponse(success=False, msg=result.stderr or "Could not generate SSH key")

    return ApiResponse(success=True, msg=await run_in_thread(_read_ssh_key), msg_type="json")


@router.get(
    "/settings/export",
    response_model=ApiResponse,
    tags=["settings"],
    summary="Export settings",
    description="Returns the current settings (Wi-Fi/AP, Tailscale, backup destination). The login password is never included.",
)
async def api_export_settings() -> ApiResponse:
    data = data_manager.get_data()
    return ApiResponse(success=True, msg=data.model_dump(exclude={"auth"}), msg_type="json")


@router.post(
    "/settings/import",
    response_model=ApiResponse,
    tags=["settings"],
    summary="Import settings",
    description="Replaces the provided settings sections. The login password is preserved.",
)
async def api_import_settings(body: SettingsImport) -> ApiResponse:
    data = data_manager.get_data()
    if body.wifi is not None:
        data.wifi = body.wifi
    if body.tailscale is not None:
        data.tailscale = body.tailscale
    if body.rsync is not None:
        data.rsync = body.rsync
    data_manager.set_data(data)  # auth is untouched
    return ApiResponse(success=True, msg="Settings imported — restart the service to apply AP/interface changes.")


@router.post(
    "/settings/reset",
    response_model=ApiResponse,
    tags=["settings"],
    summary="Reset settings",
    description="Resets settings to defaults. The login password is kept.",
)
async def api_reset_settings() -> ApiResponse:
    defaults = DataModels()
    data = data_manager.get_data()
    data.wifi = defaults.wifi
    data.tailscale = defaults.tailscale
    data.rsync = defaults.rsync
    data_manager.set_data(data)  # auth is untouched
    return ApiResponse(success=True, msg="Settings reset to defaults (login password unchanged).")
