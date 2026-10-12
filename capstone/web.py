"""aiohttp interfaces; hardware belongs exclusively to the ROS owner node."""

import asyncio
import html
import inspect
import json
import logging
import math
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from aiohttp import web

from .auth import COOKIE_NAME, SessionAuth


LOGGER = logging.getLogger(__name__)
STATIC = Path(__file__).with_name("static")
COMMANDS = frozenset(("on", "off", "open", "close", "left", "right", "stop", "reconnect"))


def unavailable_status(message="ROS controller unavailable"):
    """No previous state is presented as a current physical observation."""
    return {
        "relay": "UNKNOWN", "door_status": "UNKNOWN", "direction_status": "UNKNOWN",
        "door_ble": "UNKNOWN", "direction_ble": "UNKNOWN",
        "last_command": "NONE", "last_result": message, "last_time": "-",
        "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "door_confirmed": False, "door_command": "NONE",
        "ros_available": False, "status_stale": True,
    }


def _timeout(config, key, default):
    result = float(config.get("web", {}).get(key, default))
    if not math.isfinite(result) or result <= 0:
        raise ValueError("web.{} must be finite and positive".format(key))
    return result


def _service_url(request, config, service, path=""):
    settings = config.get("web", {})
    override = settings.get(service + "_base_url")
    if override:
        parsed = urlsplit(override)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username:
            raise ValueError("Invalid web.{}_base_url".format(service))
        return override.rstrip("/") + path
    # urlsplit preserves IPv6; the legacy host.split(':') did not.
    host = urlsplit("//" + request.host).hostname
    if not host:
        raise web.HTTPBadRequest(text="Invalid Host header")
    if ":" in host:
        host = "[{}]".format(host)
    port = int(settings.get(service + "_port", 5000 if service == "control" else 8080))
    scheme = settings.get("public_scheme") or request.scheme
    if scheme not in ("http", "https"):
        raise ValueError("web.public_scheme must be http or https")
    return urlunsplit((scheme, "{}:{}".format(host, port), path, "", ""))


def _page(name, request, config):
    settings = config.get("web", {})
    browser_config = {
        "controlBaseUrl": _service_url(request, config, "control"),
        "monitorBaseUrl": _service_url(request, config, "monitor"),
        "pollIntervalMs": max(100, int(float(settings.get("poll_interval", 1.0)) * 1000)),
        "fetchTimeoutMs": int(max(
            _timeout(config, "command_timeout", 30), _timeout(config, "status_timeout", 3)
        ) * 1000) + 1000,
    }
    # Embedded JSON must not be able to terminate the script element.
    encoded = json.dumps(browser_config).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    page = (STATIC / name).read_text(encoding="utf-8").replace("__CAPSTONE_CONFIG__", encoded)
    return web.Response(text=page, content_type="text/html", headers={"Cache-Control": "no-store"})


def create_control_app(config, bridge):
    """Create port-5000-compatible routes using an injected async ROS bridge.

    bridge.command(cmd) returns {ok, message, status}; bridge.status() returns a
    dict. A command timeout means its physical outcome is unknown, not failure
    to actuate. bridge.close(), when present, is called on application cleanup.
    """
    auth = SessionAuth(config)
    command_timeout = _timeout(config, "command_timeout", 30)
    status_timeout = _timeout(config, "status_timeout", 3)
    app = web.Application(client_max_size=4096)

    async def status_snapshot(logged_in):
        try:
            result = await asyncio.wait_for(bridge.status(), timeout=status_timeout)
            if not isinstance(result, dict):
                raise ValueError("Invalid ROS status response")
            snapshot = dict(result)
        except Exception:
            LOGGER.warning("ROS status unavailable", exc_info=True)
            snapshot = unavailable_status()
        snapshot["logged_in"] = logged_in
        return snapshot

    async def run_command(cmd):
        try:
            result = await asyncio.wait_for(bridge.command(cmd), timeout=command_timeout)
            if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
                raise ValueError("Invalid ROS command response")
            snapshot = result.get("status")
            if not isinstance(snapshot, dict):
                snapshot = await status_snapshot(True)
            else:
                snapshot = dict(snapshot)
            snapshot["logged_in"] = True
            return {
                "ok": result["ok"], "cmd": cmd,
                "message": str(result.get("message", "")), "status": snapshot,
            }, 200
        except asyncio.TimeoutError:
            message = "Command timed out; outcome unknown. Check status before retrying."
            return {"ok": False, "cmd": cmd, "message": message,
                    "status": unavailable_status(message)}, 504
        except Exception:
            LOGGER.warning("ROS command failed", exc_info=True)
            message = "ROS command unavailable; command outcome may be unknown."
            return {"ok": False, "cmd": cmd, "message": message,
                    "status": unavailable_status(message)}, 503

    def cross_site(request):
        # Keep the legacy GET route but refuse browser cross-site navigations.
        return request.headers.get("Sec-Fetch-Site") == "cross-site"

    async def control_page(request):
        if not auth.logged_in(request):
            raise web.HTTPFound(_service_url(request, config, "monitor", "/login"))
        return _page("control.html", request, config)

    async def api_status(request):
        snapshot = await status_snapshot(auth.logged_in(request))
        return web.json_response(snapshot, headers={
            "Access-Control-Allow-Origin": "*", "Cache-Control": "no-store",
        })

    async def api_cmd(request):
        if not auth.logged_in(request):
            return web.json_response({"ok": False, "message": "Login required"}, status=401)
        if cross_site(request):
            return web.json_response({"ok": False, "message": "Cross-site command rejected"}, status=403)
        try:
            data = await request.json()
        except (ValueError, UnicodeDecodeError):
            return web.json_response({"ok": False, "message": "Invalid JSON"}, status=400)
        if not isinstance(data, dict) or not isinstance(data.get("cmd"), str):
            return web.json_response({"ok": False, "message": "cmd must be a string"}, status=400)
        original_cmd = data["cmd"]
        cmd = original_cmd.strip().lower()
        if cmd not in COMMANDS:
            return web.json_response({"ok": False, "cmd": original_cmd,
                                      "message": "Unknown command",
                                      "status": await status_snapshot(True)})
        payload, code = await run_command(cmd)
        payload["cmd"] = original_cmd  # Existing clients see their original command.
        payload["status"]["logged_in"] = True
        return web.json_response(payload, status=code, headers={"Cache-Control": "no-store"})

    async def direct_cmd(request):
        if not auth.logged_in(request):
            raise web.HTTPFound(_service_url(request, config, "monitor", "/login"))
        if cross_site(request):
            raise web.HTTPForbidden(text="Cross-site command rejected")
        cmd = request.match_info["cmd"].strip().lower()
        if cmd in COMMANDS:
            payload, code = await run_command(cmd)
        else:
            payload, code = {"ok": False, "message": "Unknown command"}, 200
        return web.Response(text=("<pre>cmd = {}\nok = {}\nmessage = {}</pre>"
                                  '<p><a href="/">Back</a></p>').format(
            html.escape(cmd), payload["ok"], html.escape(payload["message"])),
            status=code, content_type="text/html", headers={"Cache-Control": "no-store"})

    async def logout(request):
        response = web.HTTPFound(_service_url(request, config, "monitor"))
        response.del_cookie(COOKIE_NAME, path="/")
        return response

    async def startup(_app):
        start = getattr(bridge, "start", None)
        if start:
            result = start()
            if inspect.isawaitable(result):
                await result

    async def cleanup(_app):
        close = getattr(bridge, "close", None)
        if close:
            result = close()
            if inspect.isawaitable(result):
                await result

    app.router.add_get("/", control_page)
    app.router.add_get("/api/status", api_status)
    app.router.add_post("/api/cmd", api_cmd)
    # aiohttp normally adds HEAD implicitly to GET; health probes must not
    # actuate hardware through the legacy command URL.
    app.router.add_get("/cmd/{cmd}", direct_cmd, allow_head=False)
    app.router.add_get("/logout", logout)
    app.router.add_static("/static/", STATIC, show_index=False)
    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    return app


def create_monitor_app(config):
    """Public monitoring and shared-cookie login; no hardware or ROS ownership."""
    auth = SessionAuth(config)
    app = web.Application(client_max_size=4096)

    async def monitor_page(request):
        return _page("monitor.html", request, config)

    async def login_page(request):
        return _page("login.html", request, config)

    async def login_post(request):
        data = await request.post()
        if auth.check_password(data.get("username", ""), data.get("password", "")):
            response = web.HTTPFound(_service_url(request, config, "control"))
            response.set_cookie(COOKIE_NAME, auth.make_token(), max_age=auth.max_age,
                                httponly=True, secure=auth.cookie_secure, samesite="Lax", path="/")
            response.headers["Cache-Control"] = "no-store"
            return response
        # The original login failure was HTML with HTTP 200; retain that contract.
        return web.Response(text="<h2>Login failed</h2><a href='/login'>Try again</a>",
                            content_type="text/html", headers={"Cache-Control": "no-store"})

    app.router.add_get("/", monitor_page)
    app.router.add_get("/login", login_page)
    app.router.add_post("/login", login_post)
    app.router.add_static("/static/", STATIC, show_index=False)
    return app
