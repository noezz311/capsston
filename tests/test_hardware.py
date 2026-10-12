"""Hardware contract tests run without ROS, BlueZ, GPIO, or a Jetson."""

import asyncio
import copy
import platform
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from capstone.hardware import DEFAULTS, HardwareController, MockBLEClient, MockGPIO, OwnerLock


class HardwareTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.config = copy.deepcopy(DEFAULTS)
        self.config["ble"]["reconnect_interval"] = 0.025
        self.config["ble"]["disconnect_timeout"] = 0.05
        self.controllers = []

    async def asyncTearDown(self):
        for controller in self.controllers:
            await controller.close()

    async def make_controller(self, **kwargs):
        controller = HardwareController(self.config, **kwargs)
        self.controllers.append(controller)
        await controller.start()
        return controller

    async def test_exact_legacy_payload_routes_and_no_physical_confirmation(self):
        controller = await self.make_controller()
        for command in ("open", "close", "left", "right", "stop"):
            result = await controller.command(command)
            self.assertTrue(result["ok"], result)
        door, direction = controller.clients["door"], controller.clients["direction"]
        uuid = self.config["ble"]["characteristic_uuid"]
        self.assertEqual(door.device, "50:8C:B1:69:D4:46")
        self.assertEqual(direction.device, "D8:A9:8B:AE:AE:86")
        self.assertEqual(door.writes, [(uuid, b"OPEN\n", False), (uuid, b"CLOSE\n", False)])
        self.assertEqual(direction.writes, [(uuid, b"L", False), (uuid, b"R", False), (uuid, b"S", False)])
        status = controller.status()
        self.assertEqual(status["door_status"], "UNKNOWN")
        self.assertEqual(status["door_command"], "CLOSE")
        self.assertFalse(status["door_confirmed"])
        self.assertEqual(status["door_delivery"], "SIMULATED")
        self.assertEqual(status["relay"], "OFF", "S must not operate motor/relay")

    async def test_active_low_startup_command_shutdown_levels(self):
        self.config["gpio"].update(pins=[7, 11], active_high=False)
        controller = await self.make_controller()
        self.assertEqual(controller.gpio.levels, {7: 1, 11: 1})
        await controller.command("on")
        self.assertEqual(controller.gpio.levels, {7: 0, 11: 0})
        await controller.command("off")
        self.assertEqual(controller.gpio.levels, {7: 1, 11: 1})
        await controller.close()
        self.assertTrue(controller.gpio.cleaned)
        self.assertEqual(controller.gpio.levels, {7: 1, 11: 1})
        self.assertFalse(controller.status()["hardware_ready"])

    async def test_expired_command_never_changes_outputs(self):
        controller = await self.make_controller()
        result = await controller.command("on", deadline_epoch=time.time() - 1)
        self.assertFalse(result["ok"])
        self.assertIn("expired", result["message"])
        self.assertEqual(controller.status()["relay"], "OFF")
        self.assertFalse((await controller.command("open", float("nan")))["ok"])

    async def test_deadline_includes_queue_wait(self):
        controller = await self.make_controller()
        async with controller._lock:
            result = await controller.command("on", deadline_epoch=time.time() + 0.02)
        self.assertFalse(result["ok"])
        self.assertEqual(controller.status()["relay"], "OFF")

    async def test_write_timeout_is_unknown_no_automatic_replay(self):
        created = []

        class SlowWrite(MockBLEClient):
            async def write_gatt_char(self, uuid, payload, response):
                self.writes.append((uuid, payload, response))
                await asyncio.sleep(10)

        def factory(device):
            client = SlowWrite(device)
            created.append(client)
            return client

        self.config["ble"]["write_timeout"] = 0.01
        controller = await self.make_controller(ble_factory=factory)
        result = await controller.command("open")
        self.assertFalse(result["ok"])
        self.assertEqual(controller.status()["door_delivery"], "UNKNOWN")
        self.assertFalse(created[0].is_connected)
        await asyncio.sleep(0.07)  # reconnect restores a session, never replays OPEN
        self.assertTrue(controller.clients["door"].is_connected)
        self.assertEqual(sum(len(client.writes) for client in created), 1)
        self.assertEqual(controller.status()["door_status"], "UNKNOWN")

    async def test_connection_failure_retries_after_interval(self):
        attempts = {}

        class InitiallyUnavailableScanner:
            @staticmethod
            async def find_device_by_address(address, timeout):
                attempts[address] = attempts.get(address, 0) + 1
                return None if attempts[address] == 1 else address

        controller = await self.make_controller(scanner=InitiallyUnavailableScanner)
        result = await controller.command("open")
        self.assertFalse(result["ok"])
        self.assertEqual(attempts[self.config["ble"]["door_address"]], 1)
        await asyncio.sleep(0.06)
        self.assertEqual(controller.status()["door_ble"], "CONNECTED")
        self.assertTrue((await controller.command("open"))["ok"])

    async def test_connection_timeout_cleans_partial_ble_client(self):
        created = []

        class StuckConnect(MockBLEClient):
            async def connect(self):
                self.is_connected = True
                await asyncio.sleep(10)

        def factory(device):
            client = StuckConnect(device)
            created.append(client)
            return client

        self.config["ble"]["connect_timeout"] = 0.01
        controller = await self.make_controller(ble_factory=factory)
        self.assertTrue(created)
        self.assertTrue(all(not client.is_connected for client in created))
        self.assertEqual(controller.status()["door_ble"], "DISCONNECTED")

    async def test_incompatible_gatt_characteristic_rejected_without_write(self):
        class Services:
            def get_characteristic(self, uuid):
                return type("Characteristic", (), {"properties": ["read", "write"]})()

        class ResponseOnlyClient(MockBLEClient):
            services = Services()

        controller = await self.make_controller(ble_factory=ResponseOnlyClient)
        self.assertFalse((await controller.command("open"))["ok"])
        self.assertEqual(controller.status()["door_ble"], "DISCONNECTED")
        self.assertTrue(any("write-without-response" in message for message in controller.errors))

    async def test_cancelled_write_disconnects_and_does_not_confirm(self):
        writing = asyncio.Event()

        class CancellableWrite(MockBLEClient):
            async def write_gatt_char(self, uuid, payload, response):
                writing.set()
                await asyncio.sleep(10)

        controller = await self.make_controller(ble_factory=CancellableWrite)
        door = controller.clients["door"]
        task = asyncio.create_task(controller.command("open"))
        await writing.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(door.is_connected)
        self.assertEqual(controller.status()["door_delivery"], "UNKNOWN")
        self.assertEqual(controller.status()["door_status"], "UNKNOWN")

    async def test_shutdown_cancels_inflight_command_and_uses_safe_gpio(self):
        writing = asyncio.Event()

        class BlockingWrite(MockBLEClient):
            async def write_gatt_char(self, uuid, payload, response):
                writing.set()
                await asyncio.sleep(10)

        controller = await self.make_controller(ble_factory=BlockingWrite)
        await controller.command("on")
        task = asyncio.create_task(controller.command("open"))
        await writing.wait()
        await controller.close()
        self.assertTrue(task.cancelled())
        self.assertEqual(controller.status()["relay"], "OFF")
        self.assertTrue(controller.gpio.cleaned)
        self.assertFalse((await controller.command("on"))["ok"])
        self.assertTrue(all(client is None for client in controller.clients.values()))

    async def test_cancelling_close_still_finishes_cleanup(self):
        disconnecting = asyncio.Event()

        class SlowDisconnect(MockBLEClient):
            async def disconnect(self):
                disconnecting.set()
                await asyncio.sleep(0.01)
                self.is_connected = False

        controller = await self.make_controller(ble_factory=SlowDisconnect)
        task = asyncio.create_task(controller.close())
        await disconnecting.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(controller.gpio.cleaned)
        self.assertFalse(controller.status()["hardware_ready"])

    async def test_partial_gpio_failure_attempts_both_safe_outputs(self):
        class FaultyGPIO(MockGPIO):
            fail = False

            def output(self, pin, level):
                if self.fail and pin == 7:
                    raise OSError("first relay failed")
                super().output(pin, level)

        self.config["gpio"].update(pins=[7, 11], active_high=True)
        gpio = FaultyGPIO()
        controller = await self.make_controller(gpio=gpio)
        await controller.command("on")
        gpio.fail = True
        await controller.close()
        self.assertEqual(gpio.levels[11], 0)
        self.assertEqual(controller.status()["relay"], "UNKNOWN")
        self.assertTrue(gpio.cleaned)

    async def test_real_mode_rejects_unverified_model_and_pins_before_import(self):
        self.config["hardware"]["mode"] = "real"
        controller = HardwareController(self.config)
        with patch("capstone.hardware.platform.system", return_value="Linux"):
            with self.assertRaisesRegex(ValueError, "board_model_confirmed"):
                await controller.start()
        self.assertIsNone(controller.gpio)

    async def test_real_mode_rejects_wrong_machine(self):
        self.config["hardware"].update(
            mode="real", board_model="NVIDIA Jetson verified target",
            board_model_confirmed=True, pinmux_confirmed=True,
            wiring_confirmed=True, legacy_controllers_disabled=True,
        )
        controller = HardwareController(self.config)
        with patch("capstone.hardware.platform.system", return_value="Linux"), patch.object(Path, "read_text", return_value="Different Jetson\x00"):
            with self.assertRaisesRegex(RuntimeError, "differs"):
                await controller.start()

    async def test_real_mode_requires_unique_physical_pins_and_explicit_polarity(self):
        self.config["hardware"].update(
            mode="real", board_model="NVIDIA Jetson verified target",
            board_model_confirmed=True, pinmux_confirmed=True,
            wiring_confirmed=True, legacy_controllers_disabled=True,
        )
        for pins, polarity, error in (([7, 7], True, "distinct"), ([True, 11], True, "distinct"), ([7, 11], None, "polarity")):
            with self.subTest(pins=pins, polarity=polarity):
                self.config["gpio"].update(pins=pins, active_high=polarity)
                controller = HardwareController(self.config)
                with patch("capstone.hardware.platform.system", return_value="Linux"), patch.object(Path, "read_text", return_value="NVIDIA Jetson verified target\x00"):
                    with self.assertRaisesRegex(ValueError, error):
                        await controller.start()

    async def test_common_config_rejects_invalid_timeout(self):
        self.config["ble"]["write_timeout"] = 0
        with self.assertRaisesRegex(ValueError, "write_timeout"):
            HardwareController(self.config)

    async def test_duplicate_addresses_rejected(self):
        self.config["ble"]["direction_address"] = self.config["ble"]["door_address"]
        with self.assertRaisesRegex(ValueError, "distinct"):
            HardwareController(self.config)

    async def test_unknown_command_is_rejected_without_writes(self):
        controller = await self.make_controller()
        self.assertFalse((await controller.command("emergency-stop"))["ok"])
        self.assertFalse((await controller.command({"cmd": "on"}))["ok"])
        self.assertEqual(controller.clients["door"].writes, [])
        self.assertEqual(controller.clients["direction"].writes, [])


class OwnerLockTests(unittest.TestCase):
    @unittest.skipUnless(platform.system() == "Linux", "Linux flock integration only")
    def test_exclusive_lock_released_for_next_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            first = OwnerLock(str(Path(directory) / "owner.lock"))
            second = OwnerLock(first.path)
            first.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "Another hardware node"):
                    second.acquire()
            finally:
                first.release()
            second.acquire()
            second.release()


if __name__ == "__main__":
    unittest.main()
