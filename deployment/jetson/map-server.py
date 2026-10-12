from jetson_runtime import web_auth
ADMIN_USER, ADMIN_PASS, SESSION_SECRET = web_auth(require_password=False)
import asyncio
import sys
import time
import hmac
import hashlib
import html
from jetson_runtime import HardwareOwner, RelayGPIO, find_device, run
from aiohttp import web
from bleak import BleakClient, BleakScanner

# ── PORT тохиргоо ─────────────────────────────────────────
MONITOR_PORT = 8080
CONTROL_PORT = 5000

SESSION_MAX_AGE = 12 * 60 * 60  # 12 цаг

# ── BLE төхөөрөмжүүд ───────────────────────────────────────
# Хэрвээ OPEN/CLOSE, LEFT/RIGHT буруу төхөөрөмж рүү явбал энэ 2 хаягийг солиорой.
DOOR_ADDR = "50:8C:B1:69:D4:46"   # OPEN / CLOSE
DIR_ADDR  = "D8:A9:8B:AE:AE:86"   # LEFT / RIGHT / STOP

CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"

# ── GPIO тохиргоо ─────────────────────────────────────────

door_client = None
dir_client = None
ble_lock = None

# ── STATUS хадгалах ───────────────────────────────────────
door_status = "UNKNOWN"
dir_status = "UNKNOWN"
last_command = "NONE"
last_result = "Ready"
last_time = "-"


# ── LOGIN SESSION CHECK ───────────────────────────────────
def check_session_token(token):
    if not token:
        return False

    try:
        username, ts, sig = token.split(":", 2)
        raw = f"{username}:{ts}"

        expected = hmac.new(
            SESSION_SECRET,
            raw.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(sig, expected):
            return False

        if username != ADMIN_USER:
            return False

        if not 0 <= time.time() - int(ts) <= SESSION_MAX_AGE:
            return False

        return True

    except Exception:
        return False


def is_logged_in(request):
    token = request.cookies.get("map_session", "")
    return check_session_token(token)


def get_host_only(request):
    return request.host.split(":")[0]


def redirect_to_login(request):
    host = get_host_only(request)
    return web.HTTPFound(f"http://{host}:{MONITOR_PORT}/login")


# ── GPIO ──────────────────────────────────────────────────
relay = RelayGPIO()
owner = HardwareOwner()


def setup_gpio():
    relay.setup()


def set_on():
    ok, message = relay.set_state(True)
    print('[GPIO] ' + message)
    return ok, message


def set_off():
    ok, message = relay.set_state(False)
    print('[GPIO] ' + message)
    return ok, message


async def find_and_connect(addr, label):
    print(f"[BLE:{label}] {addr} хайж байна...")

    try:
        device = await find_device(BleakScanner, addr, timeout=15.0)
    except Exception as e:
        print(f"[BLE:{label}] scanner алдаа: {e}", file=sys.stderr)
        return None

    if device is None:
        print(f"[BLE:{label}] олдсонгүй")
        return None

    client = BleakClient(device)

    try:
        await client.connect()
        print(f"[BLE:{label}] холбогдсон ✓ ({device.name})")
        return client
    except Exception as e:
        print(f"[BLE:{label}] холбогдох алдаа: {e}", file=sys.stderr)
        return None


async def connect_all():
    global door_client, dir_client

    if door_client is None or not door_client.is_connected:
        door_client = await find_and_connect(DOOR_ADDR, "DOOR")

    if dir_client is None or not dir_client.is_connected:
        dir_client = await find_and_connect(DIR_ADDR, "DIR")


async def reconnect_if_needed(target):
    global door_client, dir_client

    if target == "DOOR":
        if door_client is None or not door_client.is_connected:
            door_client = await find_and_connect(DOOR_ADDR, "DOOR")
        return door_client

    if target == "DIR":
        if dir_client is None or not dir_client.is_connected:
            dir_client = await find_and_connect(DIR_ADDR, "DIR")
        return dir_client

    return None


async def ble_send(target, payload, tag):
    async with ble_lock:
        client = await reconnect_if_needed(target)

        if client is None or not client.is_connected:
            msg = f"{target} not connected"
            print(f"[BLE:{target}] {msg}")
            return False, msg

        try:
            await client.write_gatt_char(CHAR_UUID, payload, response=False)
            msg = f"{tag} sent"
            print(f"[BLE:{target}] → {tag} илгээв")
            return True, msg
        except Exception as e:
            print(f"[BLE:{target}] илгээх алдаа: {e}", file=sys.stderr)
            return False, str(e)


# ── COMMAND LOGIC ─────────────────────────────────────────
def update_last(cmd, result):
    global last_command, last_result, last_time
    last_command = cmd.upper()
    last_result = result
    last_time = time.strftime("%Y-%m-%d %H:%M:%S")


async def run_command(cmd):
    global door_status, dir_status

    cmd = cmd.strip().lower()

    if cmd == "on":
        ok, msg = set_on()
        update_last(cmd, msg)
        return ok, msg

    if cmd == "off":
        ok, msg = set_off()
        update_last(cmd, msg)
        return ok, msg

    if cmd == "open":
        ok, msg = await ble_send("DOOR", b"OPEN\n", "OPEN")
        if ok:
            msg += "; physical door position unverified"
        update_last(cmd, msg)
        return ok, msg

    if cmd == "close":
        ok, msg = await ble_send("DOOR", b"CLOSE\n", "CLOSE")
        if ok:
            msg += "; physical door position unverified"
        update_last(cmd, msg)
        return ok, msg

    if cmd == "left":
        ok, msg = await ble_send("DIR", b"L", "LEFT")
        if ok:
            dir_status = "LEFT"
        update_last(cmd, msg)
        return ok, msg

    if cmd == "right":
        ok, msg = await ble_send("DIR", b"R", "RIGHT")
        if ok:
            dir_status = "RIGHT"
        update_last(cmd, msg)
        return ok, msg

    if cmd == "stop":
        ok, msg = await ble_send("DIR", b"S", "STOP")
        if ok:
            dir_status = "UNKNOWN"
        update_last(cmd, msg)
        return ok, msg

    if cmd == "reconnect":
        async with ble_lock:
            await connect_all()
        update_last(cmd, "Reconnect tried")
        return True, "Reconnect tried"

    update_last(cmd, "Unknown command")
    return False, "Unknown command"


def get_status(logged_in=False):
    door_connected = door_client.is_connected if door_client else False
    dir_connected = dir_client.is_connected if dir_client else False

    return {
        "logged_in": logged_in,
        "relay": relay.status,
        "gpio_enabled": relay.enabled,
        "physical_door_position_verified": False,
        "door_status": door_status,
        "direction_status": dir_status,
        "door_ble": "CONNECTED" if door_connected else "DISCONNECTED",
        "direction_ble": "CONNECTED" if dir_connected else "DISCONNECTED",
        "last_command": last_command,
        "last_result": last_result,
        "last_time": last_time,
        "server_time": time.strftime("%Y-%m-%d %H:%M:%S")
    }


# ── CONTROL PAGE ──────────────────────────────────────────
async def control_page(request):
    if not is_logged_in(request):
        return redirect_to_login(request)

    page = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>MAP Remote Control</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: #101010;
            color: white;
            text-align: center;
            padding: 25px;
        }
        .box {
            max-width: 760px;
            margin: auto;
            background: #1d1d1d;
            padding: 22px;
            border-radius: 16px;
        }
        button {
            width: 145px;
            height: 55px;
            margin: 8px;
            font-size: 18px;
            border: none;
            border-radius: 10px;
            cursor: pointer;
        }
        .on { background: #2ecc71; }
        .off { background: #e74c3c; color: white; }
        .door { background: #3498db; color: white; }
        .dir { background: #f1c40f; }
        .stop { background: #e67e22; color: white; }
        .etc { background: #9b59b6; color: white; }
        a {
            color: #00d5ff;
            text-decoration: none;
        }
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 14px;
            margin-top: 20px;
        }
        .card {
            background: #000;
            padding: 16px;
            border-radius: 12px;
            border: 1px solid #333;
        }
        .label {
            color: #aaa;
            font-size: 14px;
        }
        .value {
            font-size: 24px;
            font-weight: bold;
            margin-top: 6px;
        }
        .ok { color: #2ecc71; }
        .bad { color: #e74c3c; }
        .warn { color: #f1c40f; }
        pre {
            text-align: left;
            background: #000;
            color: #0f0;
            padding: 15px;
            border-radius: 10px;
            overflow-x: auto;
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <div class="box">
        <h1>MAP Remote Control</h1>

        <p>
            <a id="monitorLink" href="#">Monitor</a> |
            <a href="/logout">Logout</a>
        </p>

        <h2>Relay</h2>
        <button class="on" onclick="sendCmd('on')">ON</button>
        <button class="off" onclick="sendCmd('off')">OFF</button>

        <h2>Door</h2>
        <button class="door" onclick="sendCmd('open')">OPEN</button>
        <button class="door" onclick="sendCmd('close')">CLOSE</button>

        <h2>Direction</h2>
        <button class="dir" onclick="sendCmd('left')">LEFT</button>
        <button class="stop" onclick="sendCmd('stop')">STOP</button>
        <button class="dir" onclick="sendCmd('right')">RIGHT</button>

        <h2>System</h2>
        <button class="etc" onclick="sendCmd('reconnect')">RECONNECT</button>

        <h2>Status</h2>
        <div class="grid">
            <div class="card">
                <div class="label">Relay</div>
                <div id="relay" class="value">-</div>
            </div>
            <div class="card">
                <div class="label">Door</div>
                <div id="door_status" class="value">-</div>
            </div>
            <div class="card">
                <div class="label">Direction</div>
                <div id="direction_status" class="value">-</div>
            </div>
            <div class="card">
                <div class="label">BLE Door</div>
                <div id="door_ble" class="value">-</div>
            </div>
            <div class="card">
                <div class="label">BLE Direction</div>
                <div id="direction_ble" class="value">-</div>
            </div>
            <div class="card">
                <div class="label">Last Command</div>
                <div id="last_command" class="value">-</div>
            </div>
        </div>

        <pre id="detail">Loading...</pre>
    </div>

<script>
document.getElementById("monitorLink").href =
    "http://" + location.hostname + ":8080";

function setText(id, value) {
    document.getElementById(id).textContent = value;
}

function setStatusClass(id, value) {
    const el = document.getElementById(id);
    el.textContent = value;

    el.classList.remove("ok", "bad", "warn");

    if (value === "CONNECTED" || value === "ON" || value === "OPEN") {
        el.classList.add("ok");
    } else if (value === "DISCONNECTED" || value === "OFF") {
        el.classList.add("bad");
    } else {
        el.classList.add("warn");
    }
}

async function sendCmd(cmd) {
    const res = await fetch('/api/cmd', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({cmd: cmd})
    });

    const data = await res.json();

    if (data.status) {
        showStatus(data.status);
    }

    document.getElementById("detail").textContent =
        JSON.stringify(data, null, 2);
}

async function loadStatus() {
    const res = await fetch('/api/status');
    const data = await res.json();
    showStatus(data);
}

function showStatus(data) {
    setStatusClass("relay", data.relay);
    setStatusClass("door_status", data.door_status);
    setStatusClass("direction_status", data.direction_status);
    setStatusClass("door_ble", data.door_ble);
    setStatusClass("direction_ble", data.direction_ble);
    setText("last_command", data.last_command);

    document.getElementById("detail").textContent =
        "Last Result : " + data.last_result + "\\n" +
        "Last Time   : " + data.last_time + "\\n" +
        "Server Time : " + data.server_time + "\\n" +
        "Logged In   : " + data.logged_in;
}

document.addEventListener("keydown", function(e) {
    if (e.key === "ArrowLeft") sendCmd("left");
    if (e.key === "ArrowRight") sendCmd("right");
    if (e.key === " ") sendCmd("stop");
});

loadStatus();
setInterval(loadStatus, 1000);
</script>
</body>
</html>
"""
    return web.Response(text=page, content_type="text/html")


# ── API ───────────────────────────────────────────────────
async def api_status(request):
    # Monitor service :8080 энэ endpoint-оос status авна.
    resp = web.json_response(get_status(logged_in=is_logged_in(request)))
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


async def api_cmd(request):
    # Command ажиллуулахад login шаардлагатай.
    if not is_logged_in(request):
        return web.json_response({
            "ok": False,
            "message": "Login required"
        }, status=401)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({
            "ok": False,
            "message": "Invalid JSON"
        }, status=400)

    if not isinstance(data, dict) or not isinstance(data.get("cmd"), str):
        return web.json_response({
            "ok": False,
            "message": "Expected a JSON object with a string cmd"
        }, status=400)
    cmd = data["cmd"]
    ok, message = await run_command(cmd)

    return web.json_response({
        "ok": ok,
        "cmd": cmd,
        "message": message,
        "status": get_status(logged_in=True)
    })


async def direct_cmd(request):
    if not is_logged_in(request):
        return redirect_to_login(request)

    cmd = request.match_info.get("cmd", "")
    ok, message = await run_command(cmd)

    safe_cmd = html.escape(cmd)
    safe_message = html.escape(message)

    return web.Response(
        text=f"""
        <pre>
cmd = {safe_cmd}
ok = {ok}
message = {safe_message}
        </pre>
        <p><a href="/">Back</a></p>
        """,
        content_type="text/html"
    )


async def logout(request):
    host = get_host_only(request)
    resp = web.HTTPFound(f"http://{host}:{MONITOR_PORT}")
    resp.del_cookie("map_session")
    return resp


# ── STARTUP / CLEANUP ─────────────────────────────────────
async def on_startup(app):
    global ble_lock
    owner.acquire()
    try:
        ble_lock = asyncio.Lock()
        print("[SYSTEM] GPIO setup...")
        setup_gpio()
        print("[SYSTEM] BLE connect...")
        await connect_all()
    except BaseException:
        relay.cleanup()
        owner.release()
        raise

    print(f"[SYSTEM] Control server ready on port {CONTROL_PORT}")


async def on_cleanup(app):
    print("[SYSTEM] cleanup...")

    for client, label in ((door_client, "DOOR"), (dir_client, "DIR")):
        if client and client.is_connected:
            try:
                await client.disconnect()
                print(f"[BLE:{label}] салгав")
            except Exception:
                pass

    try:
        relay.cleanup()
    finally:
        owner.release()
    print("[SYSTEM] GPIO cleanup done")


app = web.Application()

app.router.add_get("/", control_page)
app.router.add_get("/api/status", api_status)
app.router.add_post("/api/cmd", api_cmd)
app.router.add_get("/cmd/{cmd}", direct_cmd)
app.router.add_get("/logout", logout)

app.on_startup.append(on_startup)
app.on_cleanup.append(on_cleanup)


if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=CONTROL_PORT)
