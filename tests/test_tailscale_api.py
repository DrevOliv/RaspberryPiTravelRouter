import json
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


class TailscaleApiServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._previous_data_file_path = os.environ.get("TRAVELROUTER_DATA_FILE_PATH")
        cls._temp_dir = tempfile.TemporaryDirectory()
        os.environ["TRAVELROUTER_DATA_FILE_PATH"] = str(Path(cls._temp_dir.name) / "data.json")

        from TravelRouter import create_app
        from TravelRouter.components.auth.functions import require_api_auth
        from TravelRouter.components.tailscale import api_routes as tailscale_api_routes
        from TravelRouter.config_file import DataManager
        from TravelRouter.helpers.run_command import CmdStatus

        DataManager.reset_instance()
        tailscale_api_routes.data_manager = DataManager()

        cls._tailscale_state = {
            "online": True,
            "exit_node_ip": None,
            "selected_exit_node": None,
        }

        def ok(stdout: str = "") -> CmdStatus:
            return CmdStatus(success=True, stdout=stdout, stderr="", command="mocked")

        def tailscale_status() -> CmdStatus:
            return ok(cls._build_status_payload())

        def tailscale_set_exit_node(exit_node: str) -> CmdStatus:
            cls._tailscale_state["selected_exit_node"] = exit_node
            cls._tailscale_state["exit_node_ip"] = exit_node
            return ok()

        def tailscale_disable_exit_node() -> CmdStatus:
            cls._tailscale_state["exit_node_ip"] = None
            return ok()

        def tailscale_up() -> CmdStatus:
            cls._tailscale_state["online"] = True
            return ok()

        def tailscale_down() -> CmdStatus:
            cls._tailscale_state["online"] = False
            cls._tailscale_state["exit_node_ip"] = None
            return ok()

        cls._patchers = [
            patch.object(tailscale_api_routes, "tailscale_status", side_effect=tailscale_status),
            patch.object(
                tailscale_api_routes,
                "tailscale_set_exit_node",
                side_effect=tailscale_set_exit_node,
            ),
            patch.object(
                tailscale_api_routes,
                "tailscale_disable_exit_node",
                side_effect=tailscale_disable_exit_node,
            ),
            patch.object(tailscale_api_routes, "tailscale_up", side_effect=tailscale_up),
            patch.object(tailscale_api_routes, "tailscale_down", side_effect=tailscale_down),
        ]

        for patcher in cls._patchers:
            patcher.start()

        app = create_app()
        app.dependency_overrides[require_api_auth] = lambda: None

        cls.port = cls._get_free_port()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
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
    def _build_status_payload(cls) -> str:
        payload = {
            "Self": {
                "Online": cls._tailscale_state["online"],
            },
            "Peer": {
                "nodekey:server": {
                    "HostName": "server",
                    "DNSName": "services.example.ts.net.",
                    "TailscaleIPs": ["100.108.104.64", "fd7a:115c:a1e0::c133:6840"],
                    "ExitNodeOption": True,
                },
                "nodekey:client": {
                    "HostName": "client",
                    "DNSName": "client.example.ts.net.",
                    "TailscaleIPs": ["100.77.165.73", "fd7a:115c:a1e0::5e33:a549"],
                    "ExitNodeOption": False,
                },
            },
        }

        if cls._tailscale_state["exit_node_ip"]:
            payload["ExitNodeStatus"] = {
                "TailscaleIPs": [cls._tailscale_state["exit_node_ip"]],
            }

        return json.dumps(payload)

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
        self._tailscale_state["online"] = True
        self._tailscale_state["exit_node_ip"] = None
        self._tailscale_state["selected_exit_node"] = None

        self._request("POST", "/tailscale/selection", json={"exit_node": "100.108.104.64"})
        self._request("GET", "/tailscale/disable-exit-node")
        self._request("GET", "/tailscale/up")

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        response = requests.request(method, f"{self.base_url}{path}", timeout=5, **kwargs)
        self.assertEqual(
            200,
            response.status_code,
            msg=f"{method} {path} returned {response.status_code}: {response.text}",
        )
        return response

    def test_tailscale_status_api(self) -> None:
        payload = self._request("GET", "/tailscale/status").json()

        self.assertTrue(payload["success"])
        self.assertEqual("json", payload["msg_type"])
        self.assertEqual(
            {
                "online": True,
                "exit_node": False,
                "exit_node_server": None,
                "exit_node_servers": [
                    {
                        "hostname": "server",
                        "ip_address": "100.108.104.64",
                        "dns_name": "services.example.ts.net.",
                    }
                ],
            },
            payload["msg"],
        )

    def test_tailscale_selection_api(self) -> None:
        payload = self._request(
            "POST",
            "/tailscale/selection",
            json={"exit_node": " 100.108.104.64 "},
        ).json()

        self.assertEqual(
            {
                "success": True,
                "msg": "Exit node saved",
                "msg_type": "string",
            },
            payload,
        )

        set_exit_node_payload = self._request("GET", "/tailscale/set-exit-node").json()
        self.assertTrue(set_exit_node_payload["success"])
        self.assertEqual("server", set_exit_node_payload["msg"]["exit_node_server"])

    def test_tailscale_set_exit_node_api(self) -> None:
        payload = self._request("GET", "/tailscale/set-exit-node").json()

        self.assertTrue(payload["success"])
        self.assertTrue(payload["msg"]["exit_node"])
        self.assertEqual("server", payload["msg"]["exit_node_server"])
        self.assertTrue(payload["msg"]["online"])

    def test_tailscale_disable_exit_node_api(self) -> None:
        self._request("GET", "/tailscale/set-exit-node")

        payload = self._request("GET", "/tailscale/disable-exit-node").json()

        self.assertTrue(payload["success"])
        self.assertFalse(payload["msg"]["exit_node"])
        self.assertIsNone(payload["msg"]["exit_node_server"])
        self.assertTrue(payload["msg"]["online"])

    def test_tailscale_up_api(self) -> None:
        self._request("GET", "/tailscale/down")

        payload = self._request("GET", "/tailscale/up").json()

        self.assertTrue(payload["success"])
        self.assertTrue(payload["msg"]["online"])
        self.assertFalse(payload["msg"]["exit_node"])

    def test_tailscale_down_api(self) -> None:
        self._request("GET", "/tailscale/set-exit-node")

        payload = self._request("GET", "/tailscale/down").json()

        self.assertTrue(payload["success"])
        self.assertFalse(payload["msg"]["online"])
        self.assertFalse(payload["msg"]["exit_node"])
        self.assertIsNone(payload["msg"]["exit_node_server"])


if __name__ == "__main__":
    unittest.main()
