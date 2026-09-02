"""CAN interface scan: enumerate system-available CAN backends and USB-CAN devices."""

import argparse
import json
import sys
import platform
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config.json"
COMMON_INTERFACES_PATH = Path(__file__).parent.parent / "references" / "common_interfaces.json"


def load_config():
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_known_devices():
    try:
        data = json.loads(COMMON_INTERFACES_PATH.read_text(encoding="utf-8"))
        return data.get("usb_can_devices", []), data.get("known_interfaces", [])
    except Exception:
        return [], []


def check_interface_available(interface_name):
    """Attempt to import the corresponding backend to determine if it is available."""
    try:
        import can
        # Use python-can interface enumeration to check if backend is registered
        from can.interfaces import VALID_INTERFACES
        return interface_name in VALID_INTERFACES
    except Exception:
        return False


def scan_usb_devices():
    """Scan USB devices and match known USB-CAN adapters."""
    known_devices, _ = load_known_devices()
    if not known_devices:
        return []

    found = []

    if platform.system() != "Windows":
        # Linux: match VID:PID against lsusb output.
        try:
            import subprocess
            result = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    line_upper = line.upper()
                    for known in known_devices:
                        vid = known["vid"].upper()
                        pid = known["pid"].upper()
                        if f"{vid}:{pid}" in line_upper:
                            found.append({
                                "name": known["name"],
                                "vid": vid,
                                "pid": pid,
                                "interface": known["interface"],
                                "channel": known["channel"],
                                "friendly_name": line.strip(),
                            })
        except Exception:
            pass
        return found

    # Windows fallback: query PnP devices through PowerShell.
    try:
        import subprocess
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-PnpDevice -Class USB -Status OK | Select-Object -Property InstanceId,FriendlyName | ConvertTo-Json"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0 and result.stdout.strip():
            devices = json.loads(result.stdout)
            if isinstance(devices, dict):
                devices = [devices]
            for dev in devices:
                instance_id = dev.get("InstanceId", "").upper()
                friendly = dev.get("FriendlyName", "")
                for known in known_devices:
                    vid = known["vid"].upper()
                    pid = known["pid"].upper()
                    if f"VID_{vid}" in instance_id and f"PID_{pid}" in instance_id:
                        found.append({
                            "name": known["name"],
                            "vid": vid,
                            "pid": pid,
                            "interface": known["interface"],
                            "channel": known["channel"],
                            "friendly_name": friendly,
                        })
    except Exception:
        pass

    return found


def scan_socketcan():
    """Linux: Scan SocketCAN interfaces."""
    if platform.system() != "Linux":
        return []
    interfaces = []
    try:
        import subprocess
        result = subprocess.run(
            ["ip", "-j", "link", "show", "type", "can"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            for iface in json.loads(result.stdout):
                # Some iproute2 builds emit one empty object per non-matching
                # link instead of an empty array; skip those.
                ifname = iface.get("ifname", "")
                if not ifname:
                    continue
                interfaces.append({
                    "interface": "socketcan",
                    "channel": ifname,
                    "status": iface.get("operstate", "unknown").lower(),
                })
    except Exception:
        pass
    return interfaces


def scan_interfaces():
    """Comprehensive scan of all available CAN interfaces."""
    try:
        import can  # noqa: F401
    except ImportError:
        return None, "python-can is not installed, please run: pip install python-can"

    results = []

    # 1. Scan USB-CAN devices
    usb_devices = scan_usb_devices()
    for dev in usb_devices:
        results.append({
            "interface": dev["interface"],
            "channel": dev["channel"],
            "device": dev["name"],
            "vid": dev["vid"],
            "pid": dev["pid"],
            "status": "detected",
        })

    # 2. Scan SocketCAN (Linux)
    for iface in scan_socketcan():
        results.append({
            "interface": iface["interface"],
            "channel": iface["channel"],
            "device": "",
            "vid": "",
            "pid": "",
            "status": iface["status"],
        })

    # 3. Check known backend availability
    _, known_interfaces = load_known_devices()
    backends_found = {r["interface"] for r in results}
    for ki in known_interfaces:
        iface_name = ki["interface"]
        if iface_name not in backends_found:
            if check_interface_available(iface_name):
                results.append({
                    "interface": iface_name,
                    "channel": "",
                    "device": "",
                    "vid": "",
                    "pid": "",
                    "status": "backend_available",
                })

    return results, None


def output_json(result):
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


def main():
    parser = argparse.ArgumentParser(description="Scan available CAN interfaces")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    args = parser.parse_args()

    interfaces, err = scan_interfaces()

    if err:
        result = {"status": "error", "action": "scan", "error": {"code": "import_error", "message": err}}
        if args.json:
            output_json(result)
        else:
            print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    result = {
        "status": "ok",
        "action": "scan",
        "summary": f"Found {len(interfaces)} CAN interface(s)",
        "details": {"interfaces": interfaces},
    }

    if args.json:
        output_json(result)
    else:
        if not interfaces:
            print("No available CAN interfaces found")
        else:
            print(f"Found {len(interfaces)} CAN interface(s):\n")
            for iface in interfaces:
                dev = f" [{iface['device']}]" if iface["device"] else ""
                vid_pid = f" (VID:{iface['vid']} PID:{iface['pid']})" if iface["vid"] else ""
                print(f"  {iface['interface']}:{iface['channel']}{dev}{vid_pid} — {iface['status']}")


if __name__ == "__main__":
    main()
