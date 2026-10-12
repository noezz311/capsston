# Jetson 192.168.1.40 deployment

Deployed on 2026-10-08 (Asia/Seoul) to `/home/lisa/capsston` as `lisa`.
Target inventory: NVIDIA Jetson Nano Developer Kit, Ubuntu 18.04.6,
Python 3.6.9, BlueZ 5.48. The original root `.txt` files are preserved.

## Running web services

- Monitor: http://192.168.1.40:8080/
- Login: http://192.168.1.40:8080/login
- Control: http://192.168.1.40:5000/
- Status: http://192.168.1.40:5000/api/status

The web username is `admin`. A new random password and session secret are stored
only on the Jetson in `/home/lisa/capsston/runtime.env` (mode 0600, owner lisa).
The SSH password was not saved in the deployment. Web and SSH accounts are separate.

The web programs run as transient **user** systemd services. No system-wide units,
boot enablement, or linger setting were installed. They survive the SSH disconnect
while lisa's existing desktop session remains active; reboot or ending all user
sessions requires starting them again.

```bash
cd /home/lisa/capsston
bash start-web.sh
systemctl --user status capstone-map capstone-monitor --no-pager
systemctl --user stop capstone-map capstone-monitor
sudo journalctl _SYSTEMD_USER_UNIT=capstone-map.service -n 50 --no-pager
sudo journalctl _SYSTEMD_USER_UNIT=capstone-monitor.service -n 50 --no-pager
```

## Hardware status

GPIO is explicitly disabled because physical BOARD pins and relay polarity were
not supplied. Status is `DISABLED`; relay commands return failure and do not import
or write GPIO. To enable later, confirm the wiring, pinmux, and electrical behavior
before setting `CAPSTONE_GPIO_ENABLED=1`, `CAPSTONE_GPIO_BOARD_PINS`, and
`CAPSTONE_GPIO_ACTIVE_HIGH` in the private environment file and restarting.

Bluetooth adapter is powered. Both configured addresses were absent from the
startup scans, so both connections report `DISCONNECTED`:

- Door: `50:8C:B1:69:D4:46`, commands `OPEN\n` / `CLOSE\n`.
- Direction LED: `D8:A9:8B:AE:AE:86`, commands `L` / `R` / `S`.

No actuator commands were sent during verification. BLE connection and physical
door/LED/relay operation have not been verified. A door write is reported as a
command sent, not confirmed physical position.

## main1 interactive alternative

`main1.py` and `map-server.py` own the same BLE/GPIO devices. A shared process lock
prevents simultaneous startup. The monitor may remain running during either mode.

```bash
cd /home/lisa/capsston
systemctl --user stop capstone-map
bash run-main1.sh
# Enter exit when finished, then restore the web controller:
bash start-web.sh
```

The original main1 behavior is preserved: it exits when neither BLE device is found.
Its actual standalone launch was checked: both scans completed, neither device was
found, and it exited with code 0. The map web service was then restored.

## Verification

Actual Jetson Python compilation, HTTP pages, authenticated login across ports,
unauthenticated command rejection, malformed JSON rejection, and concurrent owner
rejection passed. Deployed application hashes match local copies.

```bash
cd /home/lisa/capsston
set -a
. ./runtime.env
set +a
.venv/bin/python verify-web.py
```

Dependency compatibility was checked against the published package sources:
[aiohttp 3.8.6](https://pypi.org/project/aiohttp/3.8.6/) supports Python 3.6;
[Bleak 0.12.1](https://pypi.org/project/bleak/0.12.1/) supports Python 3.6 and
BlueZ 5.43 or later. These are target compatibility pins, not general upgrade advice.
