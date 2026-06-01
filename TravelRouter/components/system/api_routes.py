import json
from pathlib import Path

from fastapi import APIRouter

from TravelRouter.config_file import DataManager
from TravelRouter.helpers.api_response import ApiResponse
from TravelRouter.helpers.run_command import run_command, run_in_thread

router = APIRouter()

data_manager = DataManager()


def _service_active(name: str) -> bool:
    return run_command(["systemctl", "is-active", name]).stdout.strip() == "active"


def _operstate(interface: str) -> str:
    try:
        return Path(f"/sys/class/net/{interface}/operstate").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def _ipv4_addresses(interface: str) -> list[str]:
    result = run_command(["ip", "-j", "-4", "addr", "show", interface])
    if not result.success:
        return []
    try:
        data = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return [info["local"] for entry in data for info in entry.get("addr_info", []) if info.get("local")]


def _ip_forwarding() -> bool:
    try:
        return Path("/proc/sys/net/ipv4/ip_forward").read_text(encoding="utf-8").strip() == "1"
    except OSError:
        return False


def _interface(name: str) -> dict:
    return {"name": name, "state": _operstate(name), "addresses": _ipv4_addresses(name)}


def _diagnostics() -> dict:
    wifi = data_manager.get_data().wifi
    return {
        "services": {"hostapd": _service_active("hostapd"), "dnsmasq": _service_active("dnsmasq")},
        "ip_forwarding": _ip_forwarding(),
        "ap_interface": _interface(wifi.ap_interface),
        "upstream_interface": _interface(wifi.upstream_interface),
    }


@router.get(
    "/system/diagnostics",
    response_model=ApiResponse,
    tags=["system"],
    summary="System health",
    description="Reports hostapd/dnsmasq status, IP forwarding, and the AP/upstream interface states.",
)
async def api_diagnostics() -> ApiResponse:
    return ApiResponse(success=True, msg=await run_in_thread(_diagnostics), msg_type="json")
