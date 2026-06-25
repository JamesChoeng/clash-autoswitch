"""Integration-style tests with a mock mihomo controller HTTP server."""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from clashpilot import api, proxy_ctrl


class _Handler(BaseHTTPRequestHandler):
    proxies = {
        "AUTO": {"type": "Selector", "now": "node-a", "all": ["node-a", "node-b"]},
        "node-a": {"type": "Shadowsocks", "history": [], "name": "node-a"},
        "node-b": {"type": "Shadowsocks", "history": [], "name": "node-b"},
    }

    def log_message(self, *_args) -> None:
        return

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.startswith("/version"):
            self._json(200, {"version": "test-mihomo"})
        elif self.path.startswith("/proxies"):
            if self.path.rstrip("/") == "/proxies":
                self._json(200, {"proxies": self.proxies})
            elif "/delay" in self.path:
                self._json(200, {"delay": 120})
            else:
                name = self.path.split("/proxies/", 1)[1].split("?", 1)[0]
                from urllib.parse import unquote

                info = self.proxies.get(unquote(name), {})
                self._json(200, info)
        elif self.path.startswith("/connections"):
            self._json(200, {"connections": []})
        elif self.path.startswith("/configs"):
            self._json(200, {"mode": "rule"})
        else:
            self.send_response(404)
            self.end_headers()

    def do_PUT(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        if self.path.startswith("/proxies/"):
            name = self.path.split("/proxies/", 1)[1]
            from urllib.parse import unquote

            group = unquote(name)
            payload = json.loads(raw.decode("utf-8"))
            node = payload.get("name")
            if group in self.proxies and node:
                self.proxies[group]["now"] = node
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()


class MockControllerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls._port = cls._server.server_address[1]
        cls._thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._server.shutdown()
        cls._thread.join(timeout=2)

    def setUp(self) -> None:
        api.CONTROLLER = f"127.0.0.1:{self._port}"
        api.SECRET = "test-secret"

    def test_fetch_proxies_and_set_node(self) -> None:
        proxies = proxy_ctrl.fetch_proxies()
        self.assertEqual(proxies["AUTO"]["now"], "node-a")
        self.assertTrue(proxy_ctrl.set_node("AUTO", "node-b"))
        proxies = proxy_ctrl.fetch_proxies()
        self.assertEqual(proxies["AUTO"]["now"], "node-b")

    def test_has_active_target_connection_detects_host(self) -> None:
        def fake_get(path: str) -> dict:
            if path == "/connections":
                return {
                    "connections": [
                        {"metadata": {"host": "api2.cursor.sh"}, "chains": ["AUTO", "node-a"]},
                    ]
                }
            raise AssertionError(f"unexpected path: {path}")

        with patch.object(proxy_ctrl, "get_json", side_effect=fake_get):
            self.assertTrue(proxy_ctrl.has_active_target_connection())


if __name__ == "__main__":
    unittest.main()
