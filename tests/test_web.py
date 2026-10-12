"""HTTP/auth contract tests with an injected async ROS test double."""

import asyncio
import hashlib
import hmac
import os
import time
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer

from capstone.auth import SessionAuth
from capstone.web import COMMANDS, create_control_app, create_monitor_app, unavailable_status


ENV = {"CAPSTONE_ADMIN_USER": "test-admin", "CAPSTONE_ADMIN_PASSWORD": "test-only-password",
       "CAPSTONE_SESSION_SECRET": "test-only-session-key-with-32-bytes"}
CONFIG = {"web": {"command_timeout": 0.04, "status_timeout": 0.04,
                  "control_port": 5100, "monitor_port": 8180, "poll_interval": 2},
          "auth": {"session_max_age": 60}}


class FakeBridge:
    def __init__(self):
        self.commands = []
        self.started = False
        self.closed = False
        self.command_delay = 0
        self.status_delay = 0
        self.fail = False

    async def start(self):
        self.started = True

    async def close(self):
        self.closed = True

    async def status(self):
        await asyncio.sleep(self.status_delay)
        if self.fail:
            raise ConnectionError("test controller offline")
        result = unavailable_status("Ready")
        result.update({"ros_available": True, "status_stale": False, "hardware_ready": True,
                       "hardware_mode": "mock", "relay": "OFF"})
        return result

    async def command(self, cmd):
        self.commands.append(cmd)
        await asyncio.sleep(self.command_delay)
        if self.fail:
            raise ConnectionError("test controller offline")
        status = await self.status()
        status.update({"door_command": "OPEN" if cmd == "open" else "NONE"})
        return {"ok": True, "message": "test command accepted", "status": status}


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.auth = SessionAuth(CONFIG)

    def test_cookie_compatible_with_original_hmac_format(self):
        raw = "test-admin:1000"
        expected = raw + ":" + hmac.new(ENV["CAPSTONE_SESSION_SECRET"].encode(), raw.encode(), hashlib.sha256).hexdigest()
        self.assertEqual(self.auth.make_token(now=1000), expected)
        self.assertTrue(self.auth.check_token(expected, now=1020))

    def test_expired_future_tampered_and_malformed_tokens_rejected(self):
        token = self.auth.make_token(now=1000)
        self.assertFalse(self.auth.check_token(token, now=999))
        self.assertFalse(self.auth.check_token(token, now=1061))
        self.assertFalse(self.auth.check_token(token + "x", now=1020))
        for bad in (None, "", "bad", "a:b:c:d", "\N{SNOWMAN}:0:sig", "x" * 1025):
            self.assertFalse(self.auth.check_token(bad))

    def test_no_default_credentials_or_secret(self):
        for variable in ENV:
            with patch.dict(os.environ, {variable: ""}):
                with self.assertRaisesRegex(ValueError, variable):
                    SessionAuth(CONFIG)
        with patch.dict(os.environ, {"CAPSTONE_SESSION_SECRET": "short"}):
            with self.assertRaises(ValueError):
                SessionAuth(CONFIG)

    def test_password_validation(self):
        self.assertTrue(self.auth.check_password(ENV["CAPSTONE_ADMIN_USER"], ENV["CAPSTONE_ADMIN_PASSWORD"]))
        self.assertFalse(self.auth.check_password("wrong", ENV["CAPSTONE_ADMIN_PASSWORD"]))
        self.assertFalse(self.auth.check_password(ENV["CAPSTONE_ADMIN_USER"], "wrong"))
        self.assertFalse(self.auth.check_password([], {}))


class WebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.bridge = FakeBridge()
        self.control = TestClient(TestServer(create_control_app(CONFIG, self.bridge)))
        self.monitor = TestClient(TestServer(create_monitor_app(CONFIG)))
        await self.control.start_server()
        await self.monitor.start_server()
        self.auth = SessionAuth(CONFIG)

    async def asyncTearDown(self):
        await self.control.close()
        await self.monitor.close()
        self.env.stop()

    def headers(self):
        return {"Cookie": "map_session=" + self.auth.make_token()}

    async def test_public_monitor_and_cors_status_preserve_fields(self):
        response = await self.monitor.get("/")
        self.assertEqual(response.status, 200)
        page = await response.text()
        self.assertIn("5100", page)
        self.assertIn("Door physical state", page)
        self.assertIn("motor emergency stop", page)
        response = await self.control.get("/api/status")
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "*")
        payload = await response.json()
        self.assertFalse(payload["logged_in"])
        for key in ("relay", "door_status", "direction_status", "door_ble", "direction_ble",
                    "last_command", "last_result", "last_time", "server_time"):
            self.assertIn(key, payload)

    async def test_control_and_commands_require_login(self):
        response = await self.control.get("/", allow_redirects=False)
        self.assertEqual(response.status, 302)
        self.assertTrue(response.headers["Location"].endswith(":8180/login"))
        response = await self.control.get("/cmd/on", allow_redirects=False)
        self.assertEqual(response.status, 302)
        response = await self.control.post("/api/cmd", json={"cmd": "on"})
        self.assertEqual(response.status, 401)
        self.assertEqual(self.bridge.commands, [])

    async def test_login_cookie_control_and_logout(self):
        response = await self.monitor.post("/login", data={"username": ENV["CAPSTONE_ADMIN_USER"],
                                                            "password": ENV["CAPSTONE_ADMIN_PASSWORD"]},
                                           allow_redirects=False)
        self.assertEqual(response.status, 302)
        self.assertTrue(response.headers["Location"].endswith(":5100"))
        cookie = response.cookies["map_session"]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertTrue(self.auth.check_token(cookie.value))
        headers = {"Cookie": "map_session=" + cookie.value}
        response = await self.control.get("/", headers=headers)
        self.assertEqual(response.status, 200)
        page = await response.text()
        self.assertIn("8180", page)
        self.assertIn("LED S (ALL ON)", page)
        response = await self.control.get("/api/status", headers=headers)
        self.assertTrue((await response.json())["logged_in"])
        response = await self.control.get("/logout", headers=headers, allow_redirects=False)
        self.assertEqual(response.status, 302)
        self.assertEqual(response.cookies["map_session"]["max-age"], "0")

    async def test_failed_login_does_not_issue_cookie(self):
        response = await self.monitor.post("/login", data={"username": "admin", "password": "1234"}, allow_redirects=False)
        self.assertEqual(response.status, 200)
        self.assertIn("Login failed", await response.text())
        self.assertNotIn("map_session", response.cookies)

    async def test_all_commands_route_only_through_bridge(self):
        for cmd in sorted(COMMANDS):
            response = await self.control.post("/api/cmd", json={"cmd": " " + cmd.upper() + " "}, headers=self.headers())
            self.assertEqual(response.status, 200)
            payload = await response.json()
            self.assertEqual(set(payload), {"ok", "cmd", "message", "status"})
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["status"]["logged_in"])
            self.assertEqual(payload["status"]["door_status"], "UNKNOWN")
        self.assertEqual(self.bridge.commands, sorted(COMMANDS))

    async def test_direct_command_contract_and_cross_site_rejection(self):
        response = await self.control.head("/cmd/on", headers=self.headers())
        self.assertEqual(response.status, 405)
        response = await self.control.get("/cmd/open", headers=self.headers())
        self.assertEqual(response.status, 200)
        self.assertIn("cmd = open", await response.text())
        headers = dict(self.headers(), **{"Sec-Fetch-Site": "cross-site"})
        response = await self.control.get("/cmd/off", headers=headers)
        self.assertEqual(response.status, 403)
        response = await self.control.post("/api/cmd", json={"cmd": "off"}, headers=headers)
        self.assertEqual(response.status, 403)
        self.assertEqual(self.bridge.commands, ["open"])

    async def test_bad_json_unknown_commands_and_wrong_types(self):
        response = await self.control.post("/api/cmd", data="{", headers=self.headers())
        self.assertEqual(response.status, 400)
        for data in ([], {"cmd": 10}, {}, None):
            response = await self.control.post("/api/cmd", json=data, headers=self.headers())
            self.assertEqual(response.status, 400)
        response = await self.control.post("/api/cmd", json={"cmd": "invented"}, headers=self.headers())
        payload = await response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["message"], "Unknown command")
        self.assertEqual(self.bridge.commands, [])

    async def test_command_timeout_does_not_claim_no_actuation(self):
        self.bridge.command_delay = 1
        response = await self.control.post("/api/cmd", json={"cmd": "on"}, headers=self.headers())
        self.assertEqual(response.status, 504)
        payload = await response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("outcome unknown", payload["message"])
        self.assertEqual(payload["status"]["relay"], "UNKNOWN")

    async def test_controller_loss_and_status_timeout_mark_unknown_stale(self):
        self.bridge.fail = True
        response = await self.control.post("/api/cmd", json={"cmd": "open"}, headers=self.headers())
        self.assertEqual(response.status, 503)
        payload = await response.json()
        self.assertFalse(payload["status"]["ros_available"])
        response = await self.control.get("/api/status")
        payload = await response.json()
        self.assertTrue(payload["status_stale"])
        self.assertEqual(payload["relay"], "UNKNOWN")
        self.bridge.fail = False
        self.bridge.status_delay = 1
        response = await self.control.get("/api/status")
        self.assertTrue((await response.json())["status_stale"])

    async def test_custom_https_base_urls_and_secure_cookie(self):
        config = {"web": {"control_base_url": "https://control.example.test",
                          "monitor_base_url": "https://monitor.example.test"},
                  "auth": {"cookie_secure": True}}
        client = TestClient(TestServer(create_monitor_app(config)))
        await client.start_server()
        try:
            response = await client.post("/login", data={"username": ENV["CAPSTONE_ADMIN_USER"],
                                                        "password": ENV["CAPSTONE_ADMIN_PASSWORD"]}, allow_redirects=False)
            self.assertEqual(response.headers["Location"], "https://control.example.test")
            self.assertTrue(response.cookies["map_session"]["secure"])
        finally:
            await client.close()

    async def test_startup_and_shutdown_close_bridge(self):
        self.assertTrue(self.bridge.started)
        await self.control.close()
        self.assertTrue(self.bridge.closed)


if __name__ == "__main__":
    unittest.main()
