"""Non-actuating verification; source runtime.env before running on the Jetson."""
import asyncio
import json
import os
import subprocess

# aiohttp.web supplies the SameSite cookie compatibility patch for Python 3.6.
# Without it, the old stdlib mistakes SameSite=Lax for a second cookie.
from aiohttp import ClientSession, CookieJar, web


async def verify():
    base = "http://127.0.0.1"
    async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as session:
        for path in (":8080/", ":8080/login"):
            async with session.get(base + path) as response:
                assert response.status == 200, (path, response.status)
        async with session.get(base + ":5000/", allow_redirects=False) as response:
            assert response.status == 302
        async with session.get(base + ":5000/api/status") as response:
            state = await response.json()
            assert state["logged_in"] is False
            assert state["relay"] == "DISABLED"
        async with session.post(base + ":5000/api/cmd",
                                json={"cmd": "__healthcheck__"}) as response:
            assert response.status == 401
        async with session.post(base + ":8080/login", data={
            "username": os.environ["CAPSTONE_ADMIN_USER"],
            "password": os.environ["CAPSTONE_ADMIN_PASSWORD"],
        }, allow_redirects=False) as response:
            assert response.status == 302, response.status
        async with session.get(base + ":5000/") as response:
            assert response.status == 200
            assert "MAP Remote Control" in await response.text()
        async with session.get(base + ":5000/api/status") as response:
            state = await response.json()
            assert state["logged_in"] is True
            assert state["relay"] == "DISABLED"
        async with session.post(base + ":5000/api/cmd", data="{",
                                headers={"Content-Type": "application/json"}) as response:
            assert response.status == 400, response.status
        print(json.dumps({"http_and_login_checks": "PASS", "status": state}))


if __name__ == "__main__":
    assert os.environ.get("CAPSTONE_GPIO_ENABLED") == "0"
    asyncio.get_event_loop().run_until_complete(verify())
    result = subprocess.run(
        [os.path.join(os.path.dirname(__file__), ".venv/bin/python"),
         os.path.join(os.path.dirname(__file__), "main1.py")],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=8, universal_newlines=True)
    assert result.returncode != 0 and "already owned" in result.stdout, result.stdout
    print("main1 concurrent owner rejection: PASS")
