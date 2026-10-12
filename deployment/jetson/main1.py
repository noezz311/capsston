import asyncio
import sys
from jetson_runtime import HardwareOwner, RelayGPIO, find_device, run
from bleak import BleakClient, BleakScanner

# ── BLE төхөөрөмжүүд ────────────────────────────────────────
BT_ADDR_2 = "D8:A9:8B:AE:AE:86"   # open/close
BT_ADDR_1 = "50:8C:B1:69:D4:46"   # left/right/stop
CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"   # HM-10 default

# ── GPIO тохиргоо ───────────────────────────────────────────

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
    device = await find_device(BleakScanner, addr, timeout=15.0)
    if device is None:
        print(f"[BLE:{label}] ❌ олдсонгүй")
        return None
    client = BleakClient(device)
    try:
        await client.connect()
        print(f"[BLE:{label}] холбогдсон ✓ ({device.name})")
        return client
    except Exception as e:
        print(f"[BLE:{label}] холбогдох алдаа: {e}", file=sys.stderr)
        return None

async def ble_send(client, label, payload, tag):
    if client is None or not client.is_connected:
        print(f"[BLE:{label}] холбогдоогүй — алгасав")
        return
    try:
        await client.write_gatt_char(CHAR_UUID, payload, response=False)
        print(f"[BLE:{label}] → {tag} ('{payload.decode().strip()}') илгээв")
    except Exception as e:
        print(f"[BLE:{label}] илгээх алдаа: {e}", file=sys.stderr)

# ── Үндсэн логик ────────────────────────────────────────────
async def main():
    setup_gpio()

    client1 = await find_and_connect(BT_ADDR_1, "DOOR")
    client2 = await find_and_connect(BT_ADDR_2, "DIR")

    if client1 is None and client2 is None:
        print("[BLE] аль ч төхөөрөмж олдсонгүй — гарч байна")
        relay.cleanup()
        return

    print("\nMAP control shell")
    print("┌─────────────────────────────────────┐")
    print("│  [релей]   on | off                 │")
    print("│  [хаалга]  open | close             │")
    print("│  [чиглэл]  stop | left | right      │")
    print("│  [бусад]   status | exit            │")
    print("└─────────────────────────────────────┘\n")

    loop = asyncio.get_event_loop()
    try:
        while True:
            try:
                cmd = (await loop.run_in_executor(
                    None, input, "command> ")).strip().lower()
            except EOFError:
                break

            if cmd == "":
                continue

            # ── релей ──
            elif cmd == "on":
                set_on()
            elif cmd == "off":
                set_off()

            # ── DOOR (BT_ADDR_1) ──
            elif cmd == "open":
                await ble_send(client1, "DOOR", b"OPEN\n", "OPEN")
            elif cmd == "close":
                await ble_send(client1, "DOOR", b"CLOSE\n", "CLOSE")

            # ── DIRECTION (BT_ADDR_2) ──
            elif cmd == "left":
                await ble_send(client2, "DIR", b"L", "LEFT")
            elif cmd == "right":
                await ble_send(client2, "DIR", b"R", "RIGHT")
            elif cmd == "stop":
                await ble_send(client2, "DIR", b"S", "STOP")

            # ── статус ──
            elif cmd == "status":
                print(f"  релей : {relay.status}")
                s1 = client1.is_connected if client1 else False
                s2 = client2.is_connected if client2 else False
                print(f"  DOOR  : {'холбогдсон' if s1 else 'тасарсан'} ({BT_ADDR_1})")
                print(f"  DIR   : {'холбогдсон' if s2 else 'тасарсан'} ({BT_ADDR_2})")

            elif cmd in ("exit", "quit"):
                break
            else:
                print("Үл мэдэгдэх команд.")
    finally:
        for c, lbl in ((client1, "DOOR"), (client2, "DIR")):
            if c and c.is_connected:
                try:
                    await c.disconnect()
                    print(f"[BLE:{lbl}] салгав")
                except Exception:
                    pass
        relay.cleanup()
        print("\n[Дуусгав] нөөц цэвэрлэгдлээ")

if __name__ == "__main__":
    owner.acquire()
    try:
        run(main())
    except KeyboardInterrupt:
        relay.cleanup()
        print("\n[Ctrl+C] зогссон")

    finally:
        try:
            relay.cleanup()
        finally:
            owner.release()
