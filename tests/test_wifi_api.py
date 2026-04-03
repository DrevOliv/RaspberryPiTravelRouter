import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
import uvicorn


class WifiApiServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._previous_data_file_path = os.environ.get("TRAVELROUTER_DATA_FILE_PATH")
        cls._temp_dir = tempfile.TemporaryDirectory()
        os.environ["TRAVELROUTER_DATA_FILE_PATH"] = str(Path(cls._temp_dir.name) / "data.json")

        from TravelRouter import create_app
        from TravelRouter.components.auth.functions import require_api_auth
        from TravelRouter.components.wifi import api_routes as wifi_api_routes
        from TravelRouter.config_file import DataManager
        from TravelRouter.helpers.run_command import CmdStatus

        DataManager.reset_instance()
        wifi_api_routes.data_manager = DataManager()

        def ok(stdout: str = "") -> CmdStatus:
            return CmdStatus(success=True, stdout=stdout, stderr="", command="mocked")

        def scan_networks(interface: str) -> CmdStatus:
            return ok(f"{interface}-cafe:91:WPA2\n{interface}-guest:55:--\n")

        def connected_network(interface: str) -> CmdStatus:
            return ok(f"100 (connected)\n{interface}-network\n")

        def connected_devices(interface: str) -> list[dict[str, str]]:
            return [
                {
                    "name": f"{interface}-client",
                    "ip": "192.168.50.10",
                    "mac": "AA:BB:CC:DD:EE:FF",
                    "state": "reachable",
                }
            ]

        cls._patchers = [
            patch.object(wifi_api_routes, "connect_wifi", side_effect=lambda *_: ok()),
            patch.object(wifi_api_routes, "disconnect_wifi", side_effect=lambda *_: ok()),
            patch.object(wifi_api_routes, "scan_for_wifi_networks", side_effect=scan_networks),
            patch.object(wifi_api_routes, "get_connected_network", side_effect=connected_network),
            patch.object(wifi_api_routes, "apply_ap_ssid", side_effect=lambda *_: ok()),
            patch.object(wifi_api_routes, "apply_ap_password", side_effect=lambda *_: ok()),
            patch.object(wifi_api_routes, "ap_connected_devices", side_effect=connected_devices),
            patch.object(
                wifi_api_routes,
                "wifi_qr_svg",
                side_effect=lambda ssid, password: f"<svg><text>{ssid}:{password}</text></svg>",
            ),
        ]

        for patcher in cls._patchers:
            patcher.start()

        cls.port = cls._get_free_port()
        cls.base_url = f"http://127.0.0.1:{cls.port}"

        app = create_app()
        app.dependency_overrides[require_api_auth] = lambda: None

        cls.server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=cls.port,
                log_level="error",
                access_log=False,
            )
        )
        cls.server_thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.server_thread.start()
        cls._wait_for_server_start()

    @classmethod
    def tearDownClass(cls) -> None:
        server = getattr(cls, "server", None)
        if server is not None:
            server.should_exit = True

        server_thread = getattr(cls, "server_thread", None)
        if server_thread is not None:
            server_thread.join(timeout=5)

        for patcher in reversed(getattr(cls, "_patchers", [])):
            patcher.stop()

        from TravelRouter.config_file import DataManager

        DataManager.reset_instance()

        if cls._previous_data_file_path is None:
            os.environ.pop("TRAVELROUTER_DATA_FILE_PATH", None)
        else:
            os.environ["TRAVELROUTER_DATA_FILE_PATH"] = cls._previous_data_file_path

        cls._temp_dir.cleanup()

    @classmethod
    def _get_free_port(cls) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    @classmethod
    def _wait_for_server_start(cls) -> None:
        deadline = time.time() + 10
        while time.time() < deadline:
            if cls.server.started:
                return
            if not cls.server_thread.is_alive():
                raise RuntimeError("FastAPI test server exited before startup completed.")
            time.sleep(0.05)
        raise RuntimeError("FastAPI test server did not start within 10 seconds.")

    def setUp(self) -> None:
        self._request(
            "POST",
            "/settings/wifi",
            json={"upstream_interface": "wlan0", "ap_interface": "wlan1"},
        )
        self._request(
            "POST",
            "/settings/wifi/ap-ssid",
            json={"ap_ssid": "PiTravelHub"},
        )
        self._request(
            "POST",
            "/settings/wifi/ap-password",
            json={"ap_password": "ChangeThisPassword"},
        )

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        response = requests.request(method, f"{self.base_url}{path}", timeout=5, **kwargs)
        self.assertEqual(
            200,
            response.status_code,
            msg=f"{method} {path} returned {response.status_code}: {response.text}",
        )
        return response

    def test_wifi_connect_api(self) -> None:
        response = self._request(
            "POST",
            "/wifi/connect",
            json={"ssid": "CoffeeShop", "password": "secret-pass"},
        )
        self.assertEqual(
            {"success": True, "msg": "Connection to CoffeeShop successful", "msg_type": "string"},
            response.json(),
        )

    def test_wifi_disconnect_api(self) -> None:
        response = self._request("POST", "/wifi/disconnect")
        self.assertEqual(
            {"success": True, "msg": "Wi-Fi disconnected", "msg_type": "string"},
            response.json(),
        )

    def test_wifi_settings_api(self) -> None:
        response = self._request(
            "POST",
            "/settings/wifi",
            json={"upstream_interface": "wlan-up", "ap_interface": "wlan-ap"},
        )
        self.assertEqual(
            {"success": True, "msg": "Wi-Fi settings saved", "msg_type": "string"},
            response.json(),
        )

        wifi_live = self._request("GET", "/wifi/wifi-live").json()["msg"]
        self.assertEqual("wlan-up-network", wifi_live["wifi_current"]["ssid"])
        self.assertEqual("wlan-up-cafe", wifi_live["wifi_networks"][0]["ssid"])
        self.assertEqual("wlan-ap-client", wifi_live["connected_devices"][0]["name"])

    def test_wifi_live_api(self) -> None:
        response = self._request("GET", "/wifi/wifi-live")
        payload = response.json()

        self.assertTrue(payload["success"])
        self.assertEqual("json", payload["msg_type"])
        self.assertEqual(
            {
                "state": "100 (connected)",
                "ssid": "wlan0-network",
            },
            payload["msg"]["wifi_current"],
        )
        self.assertEqual(
            [
                {
                    "ssid": "wlan0-cafe",
                    "security": "WPA2",
                    "is_open": False,
                    "signal": 91,
                },
                {
                    "ssid": "wlan0-guest",
                    "security": "--",
                    "is_open": True,
                    "signal": 55,
                },
            ],
            payload["msg"]["wifi_networks"],
        )
        self.assertEqual(
            [
                {
                    "name": "wlan1-client",
                    "ip": "192.168.50.10",
                    "mac": "AA:BB:CC:DD:EE:FF",
                    "state": "reachable",
                }
            ],
            payload["msg"]["connected_devices"],
        )

    def test_wifi_ap_qr_api(self) -> None:
        response = self._request("GET", "/wifi/ap-qr")
        self.assertTrue(response.headers["content-type"].startswith("image/svg+xml"))
        self.assertEqual("<svg><text>PiTravelHub:ChangeThisPassword</text></svg>", response.text)

    def test_wifi_ap_ssid_api(self) -> None:
        response = self._request(
            "POST",
            "/settings/wifi/ap-ssid",
            json={"ap_ssid": "RoadTripRouter"},
        )
        self.assertEqual(
            {"success": True, "msg": "AP SSID saved", "msg_type": "string"},
            response.json(),
        )

        qr_response = self._request("GET", "/wifi/ap-qr")
        self.assertEqual("<svg><text>RoadTripRouter:ChangeThisPassword</text></svg>", qr_response.text)

    def test_wifi_ap_password_api(self) -> None:
        response = self._request(
            "POST",
            "/settings/wifi/ap-password",
            json={"ap_password": "StrongerPassword123"},
        )
        self.assertEqual(
            {"success": True, "msg": "AP password saved", "msg_type": "string"},
            response.json(),
        )

        qr_response = self._request("GET", "/wifi/ap-qr")
        self.assertEqual("<svg><text>PiTravelHub:StrongerPassword123</text></svg>", qr_response.text)


if __name__ == "__main__":
    unittest.main()
