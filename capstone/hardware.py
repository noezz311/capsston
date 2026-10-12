"""One ROS node owns all GPIO and BLE through this controller.

Importing this module never opens hardware.  Real mode is deliberately gated on
deployment confirmations; mock mode never imports Jetson.GPIO or Bleak.  GATT
write acceptance is command delivery information, never a door position sensor.
"""

import asyncio
import copy
import math
import os
import platform
import re
import time
import uuid
import warnings
from pathlib import Path


DEFAULTS = {
    "hardware": {
        "mode": "mock", "owner_lock_path": None, "board_model": "",
        "board_model_confirmed": False, "pinmux_confirmed": False,
        "wiring_confirmed": False, "legacy_controllers_disabled": False,
    },
    "gpio": {
        "backend": "jetson", "numbering": "BOARD", "pins": [],
        "active_high": None, "startup_on": False, "shutdown_on": False,
    },
    "ble": {
        "door_address": "50:8C:B1:69:D4:46",
        "direction_address": "D8:A9:8B:AE:AE:86",
        "characteristic_uuid": "0000ffe1-0000-1000-8000-00805f9b34fb",
        "scan_timeout": 5.0, "connect_timeout": 10.0, "write_timeout": 5.0,
        "disconnect_timeout": 3.0, "reconnect_interval": 5.0,
    },
    "timeouts": {"command": 30.0},
}

PAYLOADS = {
    "open": ("door", b"OPEN\n"), "close": ("door", b"CLOSE\n"),
    "left": ("direction", b"L"), "right": ("direction", b"R"),
    # S fills the LED display.  It is NOT a motor emergency stop.
    "stop": ("direction", b"S"),
}


class MockGPIO:
    """In-memory GPIO substitute; symbolic channels avoid implied Jetson pins."""

    BOARD, OUT, HIGH, LOW = "BOARD", "OUT", 1, 0

    def __init__(self):
        self.levels = {}
        self.history = []
        self.cleaned = False

    def setmode(self, mode):
        if mode != self.BOARD:
            raise ValueError("Only BOARD numbering is supported")

    def setup(self, pin, direction, initial):
        self.levels[pin] = initial
        self.history.append(("setup", pin, initial))

    def output(self, pin, level):
        self.levels[pin] = level
        self.history.append(("output", pin, level))

    def cleanup(self, pins):
        self.cleaned = True
        self.history.append(("cleanup", tuple(pins)))


class MockScanner:
    @staticmethod
    async def find_device_by_address(address, timeout):
        return address


class MockBLEClient:
    def __init__(self, device):
        self.device = device
        self.is_connected = False
        self.writes = []

    async def connect(self):
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False

    async def write_gatt_char(self, uuid, payload, response):
        if not self.is_connected:
            raise ConnectionError("Mock device is disconnected")
        self.writes.append((uuid, bytes(payload), response))


class OwnerLock:
    """Advisory Linux lock shared by every deployment of the new hardware node.

    Legacy controllers do not participate.  Deployment MUST stop/mask them first.
    The lock file must live outside release directories, e.g. a systemd runtime
    directory.  Never unlink it: replacing an inode would break flock exclusion.
    """

    def __init__(self, path):
        self.path = path
        self._file = None

    def acquire(self):
        import fcntl
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        self._file = os.fdopen(descriptor, "r+")
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self._file.close()
            self._file = None
            raise RuntimeError("Another hardware node holds the owner lock") from None

    def release(self):
        if self._file is not None:
            self._file.close()
            self._file = None


class HardwareController:
    """Async single-owner controller; use only within one asyncio event loop."""

    def __init__(self, config, *, gpio=None, ble_factory=None, scanner=None):
        self.config = copy.deepcopy(DEFAULTS)
        for section in DEFAULTS:
            self.config[section].update(config.get(section, {}))
        self.hardware = self.config["hardware"]
        self.gpio_config = self.config["gpio"]
        self.ble_config = self.config["ble"]
        self.mode = self.hardware["mode"]
        self.gpio = gpio
        self._ble_factory = ble_factory
        self._scanner = scanner
        self.clients = {"door": None, "direction": None}
        self._last_attempt = {"door": -math.inf, "direction": -math.inf}
        self._lock = asyncio.Lock()
        self._owner = None
        self._configured_pins = []
        self._commands = set()
        self._reconnect_task = None
        self._close_task = None
        self._started = False
        self._closing = False
        self.relay_state = False
        self.relay_known = False
        self.door_command = "NONE"
        self.direction_command = "NONE"
        self.delivery = {"door": "NOT_SENT", "direction": "NOT_SENT"}
        self.last_command = "NONE"
        self.last_result = "Not started"
        self.last_time = "-"
        self.errors = []
        self._validate_common()

    def _validate_common(self):
        if self.mode not in ("mock", "real"):
            raise ValueError("hardware.mode must be mock or real")
        for name in ("scan_timeout", "connect_timeout", "write_timeout",
                     "disconnect_timeout", "reconnect_interval"):
            value = self.ble_config[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("ble.%s must be a finite positive number" % name)
        value = self.config["timeouts"]["command"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("timeouts.command must be a finite positive number")
        for name in ("startup_on", "shutdown_on"):
            if type(self.gpio_config[name]) is not bool:
                raise ValueError("gpio.%s must be a boolean" % name)
        for name in ("door_address", "direction_address"):
            address = self.ble_config[name]
            if not isinstance(address, str) or re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", address) is None:
                raise ValueError("ble.%s must be a Bluetooth MAC address" % name)
        if self.ble_config["door_address"].lower() == self.ble_config["direction_address"].lower():
            raise ValueError("Door and LED devices must have distinct Bluetooth addresses")
        try:
            uuid.UUID(self.ble_config["characteristic_uuid"])
        except (ValueError, TypeError, AttributeError):
            raise ValueError("ble.characteristic_uuid must be a GATT UUID") from None

    def _validate_real(self):
        if platform.system() != "Linux":
            raise RuntimeError("Real hardware requires Linux on the verified Jetson")
        for name in ("board_model_confirmed", "pinmux_confirmed", "wiring_confirmed",
                     "legacy_controllers_disabled"):
            if self.hardware[name] is not True:
                raise ValueError("Real hardware blocked: hardware.%s must be confirmed" % name)
        expected_model = self.hardware["board_model"].strip()
        if not expected_model:
            raise ValueError("Real hardware requires hardware.board_model")
        model_file = Path("/proc/device-tree/model")
        detected_model = model_file.read_text().strip("\x00\n ")
        if expected_model != detected_model or "jetson" not in detected_model.lower():
            raise RuntimeError("Configured model differs from this Jetson device-tree model")
        g = self.gpio_config
        if g["backend"] != "jetson" or g["numbering"] != "BOARD":
            raise ValueError("Real mode requires the verified Jetson.GPIO BOARD backend")
        pins = g["pins"]
        if not isinstance(pins, list) or len(pins) != 2 or any(type(p) is not int or not 1 <= p <= 40 for p in pins) or len(set(pins)) != 2:
            raise ValueError("Configure two distinct confirmed physical BOARD pins")
        if type(g["active_high"]) is not bool:
            raise ValueError("Confirm relay polarity with gpio.active_high true or false")
        lock_path = self.hardware["owner_lock_path"]
        if not isinstance(lock_path, str) or not Path(lock_path).is_absolute():
            raise ValueError("Real hardware requires an absolute owner_lock_path")

    async def start(self):
        if self._started:
            return
        if self._closing:
            raise RuntimeError("Closed hardware controllers cannot be restarted")
        if self.mode == "real":
            self._validate_real()
            self._owner = OwnerLock(self.hardware["owner_lock_path"])
            self._owner.acquire()
        try:
            if self.mode == "real":
                if self.gpio is None:
                    import Jetson.GPIO as GPIO
                    self.gpio = GPIO
                if self._ble_factory is None or self._scanner is None:
                    from bleak import BleakClient, BleakScanner
                    self._ble_factory = self._ble_factory or BleakClient
                    self._scanner = self._scanner or BleakScanner
            else:
                self.gpio = self.gpio or MockGPIO()
                self._ble_factory = self._ble_factory or MockBLEClient
                self._scanner = self._scanner or MockScanner
            self.pins = self.gpio_config["pins"] or ["mock-relay-1", "mock-relay-2"]
            self.active_high = self.gpio_config["active_high"]
            if self.active_high is None:  # simulation only; real validation rejects unknown polarity
                self.active_high = True
            self.gpio.setmode(self.gpio.BOARD)
            self.relay_state = self.gpio_config["startup_on"]
            # Warnings about ownership/pinmux are failures, never suppressed.
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                for pin in self.pins:
                    # Record before setup so partial configuration is also cleaned.
                    self._configured_pins.append(pin)
                    self.gpio.setup(pin, self.gpio.OUT, initial=self._level(self.relay_state))
            self.relay_known = True
            self._started = True
            self.last_result = "Ready (%s)" % self.mode
            async with self._lock:
                await self._connect_all()
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())
        except BaseException:
            await self.close()
            raise

    def _level(self, on):
        return self.gpio.HIGH if on == self.active_high else self.gpio.LOW

    def _set_relays(self, on):
        # Keep logical status unknown if a partial output failure occurs.
        self.relay_known = False
        for pin in self._configured_pins:
            self.gpio.output(pin, self._level(on))
        self.relay_state = on
        self.relay_known = True

    async def _disconnect(self, target):
        client = self.clients[target]
        self.clients[target] = None
        if client is None:
            return
        cleanup = asyncio.create_task(asyncio.wait_for(
            client.disconnect(), self.ble_config["disconnect_timeout"]))
        cancelled = False
        try:
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    # Keep ownership even if another shutdown cancellation arrives.
                    cancelled = True
            cleanup.result()
        except Exception as exc:
            self._record_error("%s disconnect: %s" % (target, exc))
        if cancelled:
            raise asyncio.CancelledError

    async def _ensure_connected(self, target):
        client = self.clients[target]
        if client is not None and client.is_connected:
            return client
        now = time.monotonic()
        if now - self._last_attempt[target] < self.ble_config["reconnect_interval"]:
            return None
        self._last_attempt[target] = now
        try:
            await self._disconnect(target)
            device = await asyncio.wait_for(
                self._scanner.find_device_by_address(
                    self.ble_config[target + "_address"], timeout=self.ble_config["scan_timeout"]),
                self.ble_config["scan_timeout"],
            )
            if device is None:
                raise ConnectionError("device not found")
            client = self._ble_factory(device)
            self.clients[target] = client  # owns partial connections as well
            await asyncio.wait_for(client.connect(), self.ble_config["connect_timeout"])
            if not client.is_connected:
                raise ConnectionError("connect returned without a connection")
            # Preserve response=False; reject a known incompatible GATT property.
            services = getattr(client, "services", None)
            if services is not None:
                characteristic = services.get_characteristic(self.ble_config["characteristic_uuid"])
                if characteristic is None or "write-without-response" not in characteristic.properties:
                    raise ValueError("Configured GATT characteristic lacks write-without-response")
            return client
        except asyncio.CancelledError:
            await self._disconnect(target)
            raise
        except Exception as exc:
            self._record_error("%s connect: %s" % (target, exc))
            await self._disconnect(target)
            return None

    async def _connect_all(self):
        # Serial discovery avoids adapter contention on embedded BlueZ stacks.
        for target in self.clients:
            await self._ensure_connected(target)

    async def _reconnect_loop(self):
        while not self._closing:
            await asyncio.sleep(self.ble_config["reconnect_interval"])
            async with self._lock:
                if not self._closing:
                    await self._connect_all()

    def _record_error(self, message):
        self.errors.append(message)
        del self.errors[:-10]

    async def _send(self, command, deadline):
        target, payload = PAYLOADS[command]
        client = await self._ensure_connected(target)
        if client is None:
            return False, "%s not connected (reconnect interval applies)" % target.upper()
        if self._closing:
            return False, "Hardware is shutting down"
        if time.monotonic() >= deadline:
            return False, "Command deadline expired before BLE write"
        # Track the actual attempted command even if its delivery becomes unknown.
        if target == "door":
            self.door_command = command.upper()
        else:
            self.direction_command = command.upper()
        self.delivery[target] = "IN_FLIGHT"
        try:
            await asyncio.wait_for(
                client.write_gatt_char(self.ble_config["characteristic_uuid"], payload, response=False),
                self.ble_config["write_timeout"],
            )
            self.delivery[target] = "SIMULATED" if self.mode == "mock" else "WRITE_ACCEPTED"
            return True, "%s sent; physical state unverified%s" % (
                command.upper(), " (mock)" if self.mode == "mock" else "")
        except asyncio.CancelledError:
            self.delivery[target] = "UNKNOWN"
            await self._disconnect(target)
            raise
        except Exception as exc:
            # A timed-out write can already have reached the Arduino. Never replay.
            self.delivery[target] = "UNKNOWN"
            self._last_attempt[target] = time.monotonic()
            await self._disconnect(target)
            return False, "%s delivery unknown; not retried (%s)" % (command.upper(), type(exc).__name__)

    async def _dispatch(self, command, deadline):
        async with self._lock:
            if self._closing or not self._started:
                return False, "Hardware is unavailable"
            if time.monotonic() >= deadline:
                return False, "Command deadline expired before execution"
            if command in ("on", "off"):
                self._set_relays(command == "on")
                return True, "Relay %s%s" % (command.upper(), " (mock)" if self.mode == "mock" else "")
            if command in PAYLOADS:
                return await self._send(command, deadline)
            if command == "reconnect":
                await self._connect_all()
                ok = all(c is not None and c.is_connected for c in self.clients.values())
                return ok, "Reconnect tried; %s" % ("both connected" if ok else "device unavailable")
            return False, "Unknown command"

    async def command(self, cmd, deadline_epoch=None):
        if not isinstance(cmd, str):
            return {"ok": False, "message": "Command must be a string", "status": self.status()}
        cmd = cmd.strip().lower()
        budget = self.config["timeouts"]["command"]
        if deadline_epoch is not None:
            if isinstance(deadline_epoch, bool) or not isinstance(deadline_epoch, (int, float)) or not math.isfinite(deadline_epoch):
                return {"ok": False, "message": "Invalid command deadline", "status": self.status()}
            budget = min(budget, deadline_epoch - time.time())
        if budget <= 0:
            return {"ok": False, "message": "Command deadline expired", "status": self.status()}
        task = asyncio.current_task()
        self._commands.add(task)
        try:
            ok, message = await asyncio.wait_for(self._dispatch(cmd, time.monotonic() + budget), budget)
        except asyncio.TimeoutError:
            ok, message = False, "Command timed out; delivery may be unknown; not retried"
        except asyncio.CancelledError:
            self._update_last(cmd, "Command cancelled; delivery may be unknown; not retried")
            raise
        except Exception as exc:
            ok, message = False, "Command failed: %s" % type(exc).__name__
            self._record_error(str(exc))
            # A GPIO output failure may leave mismatched relays; attempt safe state.
            if cmd in ("on", "off"):
                self._safe_gpio_shutdown()
        finally:
            self._commands.discard(task)
        self._update_last(cmd, message)
        return {"ok": ok, "message": message, "status": self.status()}

    def _update_last(self, command, message):
        self.last_command = command.upper()
        self.last_result = message
        self.last_time = time.strftime("%Y-%m-%d %H:%M:%S")

    def status(self):
        connected = {target: client is not None and bool(client.is_connected)
                     for target, client in self.clients.items()}
        return {
            "logged_in": False,
            "relay": ("ON" if self.relay_state else "OFF") if self.relay_known else "UNKNOWN",
            "door_status": "UNKNOWN", "direction_status": self.direction_command,
            "door_ble": "CONNECTED" if connected["door"] else "DISCONNECTED",
            "direction_ble": "CONNECTED" if connected["direction"] else "DISCONNECTED",
            "last_command": self.last_command, "last_result": self.last_result,
            "last_time": self.last_time, "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "hardware_mode": self.mode, "hardware_ready": self._started and not self._closing,
            "door_command": self.door_command, "door_confirmed": False,
            "door_delivery": self.delivery["door"],
            "direction_command": self.direction_command,
            "direction_confirmed": False, "direction_delivery": self.delivery["direction"],
            "relay_feedback_confirmed": False,
            "errors": list(self.errors),
        }

    def _safe_gpio_shutdown(self):
        if not self._configured_pins or self.gpio is None:
            return
        failed = False
        # Try every pin even when one output raises.
        for pin in self._configured_pins:
            try:
                self.gpio.output(pin, self._level(self.gpio_config["shutdown_on"]))
            except Exception as exc:
                failed = True
                self._record_error("GPIO shutdown: %s" % exc)
        self.relay_state = self.gpio_config["shutdown_on"]
        self.relay_known = not failed

    async def _close(self):
        self._closing = True
        # De-energize configured relays before waiting for any BLE cancellation.
        self._safe_gpio_shutdown()
        tasks = list(self._commands)
        if self._reconnect_task is not None:
            tasks.append(self._reconnect_task)
        for task in tasks:
            task.cancel()
        try:
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            for target in self.clients:
                await self._disconnect(target)
        finally:
            if self.gpio is not None and self._configured_pins:
                try:
                    self.gpio.cleanup(self._configured_pins)
                except Exception as exc:
                    self._record_error("GPIO cleanup: %s" % exc)
                self._configured_pins = []
            if self._owner is not None:
                self._owner.release()
            self._started = False

    async def close(self):
        """Cancellation of a caller waits for cleanup before propagating."""
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        cancelled = False
        while not self._close_task.done():
            try:
                await asyncio.shield(self._close_task)
            except asyncio.CancelledError:
                cancelled = True
        self._close_task.result()
        if cancelled:
            raise asyncio.CancelledError
