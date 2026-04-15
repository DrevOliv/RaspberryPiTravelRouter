import os
import socket
import tempfile
from pathlib import Path

from TravelRouter.components.wifi.hostapd_config import HostapdConfig
from TravelRouter.config_file.config_file_funcs import DataManager
from TravelRouter.helpers.api_response import ApiResponse
from TravelRouter.helpers.run_command import run_command


class HostapdController:
    def __init__(
        self,
        config_path: str = "/etc/hostapd/hostapd.conf",
        ctrl_dir: str = "/var/run/hostapd",
    ):
        self.config_path = Path(config_path)
        self.data_manager = DataManager()

        curr_config = self.data_manager.get_data()
        self.hostapd_config = HostapdConfig(
            ssid=curr_config.wifi.ap_ssid,
            wpa_passphrase=curr_config.wifi.ap_password,
            interface=curr_config.wifi.ap_interface,
        )

        self.ctrl_dir = ctrl_dir
        self._update_ctrl_path()

    def _update_ctrl_path(self) -> None:
        self.ctrl_path = f"{self.ctrl_dir}/{self.hostapd_config.interface}"
        self.client_path = f"/tmp/hostapd_ctrl_{self.hostapd_config.interface}"

    # ------------------------------------------------------------------
    # Internal socket helper
    # ------------------------------------------------------------------

    def _send_cmd(self, cmd: str) -> tuple[str, bool]:
        if not os.path.exists(self.ctrl_path):
            return f"hostapd socket not found: {self.ctrl_path}", False

        if os.path.exists(self.client_path):
            os.remove(self.client_path)

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            sock.bind(self.client_path)
            sock.settimeout(5)
            sock.connect(self.ctrl_path)
            sock.send(cmd.encode())
            response = sock.recv(8192).decode()
        except PermissionError:
            return f"permission denied on hostapd socket — is the user in the netdev group?", False
        except TimeoutError:
            return "hostapd socket timed out", False
        except OSError as e:
            return str(e), False
        finally:
            sock.close()
            if os.path.exists(self.client_path):
                os.remove(self.client_path)

        return response.strip(), True

    # ------------------------------------------------------------------
    # Config file
    # ------------------------------------------------------------------

    def write_config(self) -> ApiResponse:
        updates = {
            "interface": self.hostapd_config.interface,
            "ssid": self.hostapd_config.ssid,
            "wpa_passphrase": self.hostapd_config.wpa_passphrase,
        }

        read_result = run_command(["sudo", "cat", str(self.config_path)])
        if read_result.success and read_result.stdout:
            updated_keys: set[str] = set()
            new_lines: list[str] = []
            for line in read_result.stdout.splitlines():
                stripped = line.strip()
                if "=" in stripped and not stripped.startswith("#"):
                    key = stripped.split("=", 1)[0]
                    if key in updates:
                        new_lines.append(f"{key}={updates[key]}")
                        updated_keys.add(key)
                        continue
                new_lines.append(line)
            for key, value in updates.items():
                if key not in updated_keys:
                    new_lines.append(f"{key}={value}")
            content = "\n".join(new_lines) + "\n"
        else:
            content = str(self.hostapd_config)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
            f.write(content)
            tmp_path = f.name
        result = run_command(["sudo", "cp", tmp_path, str(self.config_path)])
        os.unlink(tmp_path)
        if not result.success:
            return ApiResponse(success=False, msg={"error": result.stderr}, msg_type="json")
        return ApiResponse(success=True, msg={"written": str(self.config_path)}, msg_type="json")

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------

    def change_ap_creds(self, ssid: str = None, wpa_passphrase: str = None) -> ApiResponse:
        curr_config = self.data_manager.get_data()

        if ssid is not None:
            self.hostapd_config.ssid = ssid
            curr_config.wifi.ap_ssid = ssid

        if wpa_passphrase is not None:
            if not self.hostapd_config.set_password(wpa_passphrase):
                return ApiResponse(
                    success=False,
                    msg={"error": "Password must be 8–63 characters"},
                    msg_type="json",
                )
            curr_config.wifi.ap_password = wpa_passphrase

        self.data_manager.set_data(curr_config)

        write_result = self.write_config()
        if not write_result.success:
            return write_result

        return self.reload()

    # ------------------------------------------------------------------
    # Status & clients
    # ------------------------------------------------------------------

    def get_status(self) -> ApiResponse:
        raw, success = self._send_cmd("STATUS")
        data = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
        return ApiResponse(success=success, msg=data, msg_type="json")

    def list_clients(self) -> ApiResponse:
        clients = []

        raw, success = self._send_cmd("STA-FIRST")
        if not success:
            return ApiResponse(success=False, msg={"error": raw}, msg_type="json")
        if not raw or "FAIL" in raw:
            return ApiResponse(success=True, msg=clients, msg_type="json")

        mac = raw.splitlines()[0].strip()
        clients.append(mac)

        while True:
            raw, success = self._send_cmd(f"STA-NEXT {mac}")
            if not success or not raw or "FAIL" in raw:
                break
            mac = raw.splitlines()[0].strip()
            clients.append(mac)

        return ApiResponse(success=True, msg=clients, msg_type="json")

    def get_client_info(self, mac: str) -> ApiResponse:
        raw, success = self._send_cmd(f"STA {mac}")
        data = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
        return ApiResponse(success=success, msg=data, msg_type="json")

    def _read_leases(self) -> dict[str, dict]:
        leases: dict[str, dict] = {}
        try:
            with open("/var/lib/misc/dnsmasq.leases", "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) < 4:
                        continue
                    _expires, mac, ip, hostname = parts[:4]
                    leases[mac.upper()] = {
                        "ip": ip,
                        "name": "" if hostname == "*" else hostname,
                    }
        except OSError:
            pass
        return leases

    def get_connected_devices(self) -> list[dict]:
        result = self.list_clients()
        if not result.success:
            return []

        macs: list[str] = result.msg if isinstance(result.msg, list) else []
        leases = self._read_leases()

        devices = []
        for mac in macs:
            info_result = self.get_client_info(mac)
            info: dict = info_result.msg if isinstance(info_result.msg, dict) else {}

            # Skip stations that are not fully authorized — they are stale entries
            # from devices that recently disconnected but haven't been evicted yet
            if "AUTHORIZED" not in info.get("flags", ""):
                continue

            mac_upper = mac.upper()
            lease = leases.get(mac_upper, {})
            devices.append({
                "mac": mac_upper,
                "ip": lease.get("ip", ""),
                "name": lease.get("name") or mac_upper,
                "state": "connected",
                "signal_dbm": info.get("signal_dbm", ""),
                "connected_time": info.get("connected_time", ""),
            })

        return sorted(devices, key=lambda d: d.get("name", "").lower())

    def disconnect_client(self, mac: str) -> ApiResponse:
        raw, success = self._send_cmd(f"DEAUTHENTICATE {mac}")
        return ApiResponse(success=success, msg={"response": raw}, msg_type="json")

    # ------------------------------------------------------------------
    # Service control
    # ------------------------------------------------------------------

    def reload(self) -> ApiResponse:
        raw, success = self._send_cmd("RELOAD")
        return ApiResponse(success=success, msg={"response": raw}, msg_type="json")

    def start(self) -> ApiResponse:
        result = run_command(["sudo", "systemctl", "start", "hostapd"])
        return ApiResponse(
            success=result.success,
            msg={"stdout": result.stdout, "stderr": result.stderr},
            msg_type="json",
        )

    def stop(self) -> ApiResponse:
        result = run_command(["sudo", "systemctl", "stop", "hostapd"])
        return ApiResponse(
            success=result.success,
            msg={"stdout": result.stdout, "stderr": result.stderr},
            msg_type="json",
        )

    def restart(self) -> ApiResponse:
        result = run_command(["sudo", "systemctl", "restart", "hostapd"])
        return ApiResponse(
            success=result.success,
            msg={"stdout": result.stdout, "stderr": result.stderr},
            msg_type="json",
        )


hostapd_controller = HostapdController()
