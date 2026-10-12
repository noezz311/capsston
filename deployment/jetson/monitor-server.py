from jetson_runtime import web_auth
ADMIN_USER, ADMIN_PASS, SESSION_SECRET = web_auth(require_password=True)
from aiohttp import web
import time
import hmac
import hashlib


SESSION_MAX_AGE = 12 * 60 * 60

MONITOR_PORT = 8080
CONTROL_PORT = 5000


def make_session_token(username):
    ts = str(int(time.time()))
    raw = f"{username}:{ts}"
    sig = hmac.new(SESSION_SECRET, raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}:{sig}"


async def monitor_page(request):
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>MAP Monitoring</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            background: #101010;
            color: white;
            text-align: center;
            padding: 25px;
        }}
        .box {{
            max-width: 760px;
            margin: auto;
            background: #1e1e1e;
            padding: 25px;
            border-radius: 16px;
        }}
        h1 {{
            font-size: 40px;
            margin-bottom: 10px;
        }}
        .status-main {{
            font-size: 28px;
            font-weight: bold;
            margin: 15px;
        }}
        .grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 14px;
            margin-top: 25px;
        }}
        .card {{
            background: #000;
            border: 1px solid #333;
            padding: 18px;
            border-radius: 14px;
        }}
        .label {{
            color: #aaa;
            font-size: 15px;
        }}
        .value {{
            font-size: 26px;
            font-weight: bold;
            margin-top: 6px;
        }}
        .ok {{
            color: #2ecc71;
        }}
        .bad {{
            color: #e74c3c;
        }}
        .warn {{
            color: #f1c40f;
        }}
        button {{
            margin-top: 25px;
            padding: 14px 28px;
            border: none;
            border-radius: 12px;
            background: #00bcd4;
            color: white;
            font-size: 22px;
            cursor: pointer;
        }}
        pre {{
            text-align: left;
            background: #000;
            color: #0f0;
            padding: 15px;
            border-radius: 12px;
            overflow-x: auto;
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <div class="box">
        <h1>MAP Monitoring</h1>

        <p>Control service status:</p>
        <div id="control_status" class="status-main warn">Checking...</div>

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

        <a href="/login">
            <button>Login хийж remote control руу орох</button>
        </a>
    </div>

<script>
const CONTROL_PORT = {CONTROL_PORT};

function setText(id, value) {{
    document.getElementById(id).textContent = value;
}}

function setClassByConnection(id, value) {{
    const el = document.getElementById(id);
    el.textContent = value;

    el.classList.remove("ok", "bad", "warn");

    if (value === "CONNECTED" || value === "ON" || value === "OPEN") {{
        el.classList.add("ok");
    }} else if (value === "DISCONNECTED" || value === "OFF") {{
        el.classList.add("bad");
    }} else {{
        el.classList.add("warn");
    }}
}}

async function loadStatus() {{
    const url = "http://" + location.hostname + ":" + CONTROL_PORT + "/api/status";

    try {{
        const res = await fetch(url);
        const data = await res.json();

        const control = document.getElementById("control_status");
        control.textContent = "Control service running";
        control.classList.remove("bad", "warn");
        control.classList.add("ok");

        setClassByConnection("relay", data.relay);
        setClassByConnection("door_status", data.door_status);
        setClassByConnection("direction_status", data.direction_status);
        setClassByConnection("door_ble", data.door_ble);
        setClassByConnection("direction_ble", data.direction_ble);
        setText("last_command", data.last_command);

        document.getElementById("detail").textContent =
            "Last Result : " + data.last_result + "\\n" +
            "Last Time   : " + data.last_time + "\\n" +
            "Server Time : " + data.server_time + "\\n" +
            "Logged In   : " + data.logged_in;

    }} catch (e) {{
        const control = document.getElementById("control_status");
        control.textContent = "Control service not reachable";
        control.classList.remove("ok", "warn");
        control.classList.add("bad");

        setText("relay", "-");
        setText("door_status", "-");
        setText("direction_status", "-");
        setText("door_ble", "-");
        setText("direction_ble", "-");
        setText("last_command", "-");

        document.getElementById("detail").textContent =
            "Cannot connect to control service on port " + CONTROL_PORT;
    }}
}}

loadStatus();
setInterval(loadStatus, 1000);
</script>
</body>
</html>
"""
    return web.Response(text=html, content_type="text/html")


async def login_page(request):
    html = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Login</title>
    <style>
        body {
            font-family: Arial;
            background: #101010;
            color: white;
            text-align: center;
            padding: 30px;
        }
        .box {
            background: #1e1e1e;
            padding: 25px;
            border-radius: 15px;
            max-width: 400px;
            margin: auto;
        }
        input {
            width: 85%;
            height: 40px;
            margin: 8px;
            font-size: 18px;
            border-radius: 8px;
            border: none;
            padding-left: 10px;
        }
        button {
            width: 150px;
            height: 45px;
            margin-top: 15px;
            border: none;
            border-radius: 10px;
            background: #00bcd4;
            color: white;
            font-size: 18px;
        }
        a {
            color: #00d5ff;
        }
    </style>
</head>
<body>
    <div class="box">
        <h1>Remote Login</h1>

        <form method="POST" action="/login">
            <input name="username" placeholder="Username"><br>
            <input name="password" type="password" placeholder="Password"><br>
            <button type="submit">Login</button>
        </form>

        <p><a href="/">Back to monitor</a></p>
    </div>
</body>
</html>
"""
    return web.Response(text=html, content_type="text/html")


async def login_post(request):
    data = await request.post()

    username = data.get("username", "")
    password = data.get("password", "")

    if username == ADMIN_USER and password == ADMIN_PASS:
        host = request.host.split(":")[0]
        resp = web.HTTPFound(f"http://{host}:{CONTROL_PORT}")
        resp.set_cookie(
            "map_session",
            make_session_token(username),
            max_age=SESSION_MAX_AGE,
            httponly=True,
            samesite="Lax"
        )
        return resp

    return web.Response(
        text="<h2>Login failed</h2><a href='/login'>Try again</a>",
        content_type="text/html"
    )


app = web.Application()
app.router.add_get("/", monitor_page)
app.router.add_get("/login", login_page)
app.router.add_post("/login", login_post)

web.run_app(app, host="0.0.0.0", port=MONITOR_PORT)