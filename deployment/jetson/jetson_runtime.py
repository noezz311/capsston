"""Small Python 3.6 runtime for the preserved legacy HTTP/control programs."""
import asyncio
import os


def web_auth(require_password=False):
    """Read shared credentials from the service environment, never source defaults."""
    names = ["CAPSTONE_ADMIN_USER", "CAPSTONE_SESSION_SECRET"]
    if require_password:
        names.append("CAPSTONE_ADMIN_PASSWORD")
    values = {}
    for name in names:
        value = os.environ.get(name, "")
        if not value:
            raise RuntimeError("Required environment variable is missing: " + name)
        values[name] = value
    return (values["CAPSTONE_ADMIN_USER"],
            values.get("CAPSTONE_ADMIN_PASSWORD"),
            values["CAPSTONE_SESSION_SECRET"].encode("utf-8"))


class HardwareOwner:
    """Both command-line and HTTP controllers must use this same process lock."""
    def __init__(self):
        self.stream = None

    def acquire(self):
        import fcntl
        path = os.environ.get("CAPSTONE_OWNER_LOCK", "/tmp/capstone-hardware.lock")
        self.stream = open(path, "a+")
        try:
            fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            self.stream = None
            raise RuntimeError("Hardware is already owned by another controller")
        self.stream.seek(0)
        self.stream.truncate()
        self.stream.write(str(os.getpid()) + "\n")
        self.stream.flush()

    def release(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


class RelayGPIO:
    """No Jetson GPIO import or output unless explicit confirmed wiring is supplied."""
    def __init__(self):
        flag = os.environ.get("CAPSTONE_GPIO_ENABLED", "0").lower()
        if flag not in ("0", "1", "false", "true"):
            raise RuntimeError("CAPSTONE_GPIO_ENABLED must be 0 or 1")
        self.enabled = flag in ("1", "true")
        self.driver = None
        self.configured = []
        self.state = False
        self.pins = []
        self.active_high = None
        if self.enabled:
            raw = os.environ.get("CAPSTONE_GPIO_BOARD_PINS", "")
            try:
                self.pins = [int(pin.strip()) for pin in raw.split(",")]
            except ValueError:
                raise RuntimeError("Supply two confirmed BOARD pins in CAPSTONE_GPIO_BOARD_PINS")
            if (len(self.pins) != 2 or len(set(self.pins)) != 2
                    or any(pin < 1 or pin > 40 for pin in self.pins)):
                raise RuntimeError("Supply two distinct confirmed physical BOARD pins")
            polarity = os.environ.get("CAPSTONE_GPIO_ACTIVE_HIGH", "").lower()
            if polarity not in ("0", "1", "false", "true"):
                raise RuntimeError("Explicit CAPSTONE_GPIO_ACTIVE_HIGH=0 or 1 is required")
            self.active_high = polarity in ("1", "true")

    @property
    def status(self):
        if not self.enabled:
            return "DISABLED"
        return "ON" if self.state else "OFF"

    def _level(self, on):
        high = on if self.active_high else not on
        return self.driver.HIGH if high else self.driver.LOW

    def setup(self):
        if not self.enabled:
            print("[GPIO] DISABLED: BOARD pins and relay polarity are unconfirmed")
            return
        import Jetson.GPIO as GPIO
        self.driver = GPIO
        GPIO.setmode(GPIO.BOARD)
        try:
            for pin in self.pins:
                GPIO.setup(pin, GPIO.OUT, initial=self._level(False))
                self.configured.append(pin)
        except Exception:
            self.cleanup()
            raise
        print("[GPIO] Enabled with explicit BOARD wiring; startup state OFF")

    def set_state(self, on):
        if not self.enabled:
            return False, "GPIO DISABLED: BOARD wiring and polarity must be confirmed"
        for pin in self.configured:
            self.driver.output(pin, self._level(on))
        self.state = on
        return True, "Relay " + self.status

    def cleanup(self):
        if self.driver is not None and self.configured:
            try:
                for pin in self.configured:
                    self.driver.output(pin, self._level(False))
            finally:
                self.driver.cleanup(self.configured)
                self.configured = []
                self.state = False


async def find_device(scanner, address, timeout=15.0):
    """Use the discover() API present in the deployed Bleak 0.12.1."""
    devices = await scanner.discover(timeout=timeout)
    for device in devices:
        if device.address.lower() == address.lower():
            return device
    return None


def run(coroutine):
    """asyncio.run equivalent for the device's Python 3.6 interpreter."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    task = loop.create_task(coroutine)
    try:
        return loop.run_until_complete(task)
    except KeyboardInterrupt:
        task.cancel()
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass
        raise
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
