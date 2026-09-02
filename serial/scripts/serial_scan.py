"""Serial port scan: Enumerate system serial ports and display device information."""

import argparse
import json
import sys
from pathlib import Path

from serial_runtime import get_mux_info

COMMON_DEVICES_PATH = Path(__file__).parent.parent / "references" / "common_devices.json"


def load_chip_map():
    """Load VID/PID -> chip name mapping."""
    chip_map = {}
    try:
        data = json.loads(COMMON_DEVICES_PATH.read_text(encoding="utf-8"))
        for entry in data.get("usb_serial_chips", []):
            key = (entry["vid"].upper(), entry["pid"].upper())
            chip_map[key] = entry["name"]
    except Exception:
        pass
    return chip_map


def scan_ports(filter_keyword=None):
    """Scan system serial ports."""
    try:
        from serial.tools.list_ports import comports
    except ImportError:
        return None, "pyserial is not installed, please run: pip install pyserial"

    chip_map = load_chip_map()
    ports = []

    for p in sorted(comports(), key=lambda x: x.device):
        vid = f"{p.vid:04X}" if p.vid else ""
        pid = f"{p.pid:04X}" if p.pid else ""
        chip_name = chip_map.get((vid, pid), "")

        info = {
            "port": p.device,
            "description": p.description or "",
            "vid": vid,
            "pid": pid,
            "chip": chip_name,
            "serial_number": p.serial_number or "",
            "location": p.location or "",
        }

        if filter_keyword:
            text = " ".join(str(v) for v in info.values()).lower()
            if filter_keyword.lower() not in text:
                continue

        ports.append(info)

    return ports, None


def output_json(result):
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


def main():
    parser = argparse.ArgumentParser(description="Scan system serial ports")
    parser.add_argument("--filter", help="Filter by keyword")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    args = parser.parse_args()

    ports, err = scan_ports(args.filter)

    if err:
        result = {"status": "error", "action": "scan", "error": {"code": "import_error", "message": err}}
        if args.json:
            output_json(result)
        else:
            print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    mux_info = get_mux_info()
    result = {
        "status": "ok",
        "action": "scan",
        "summary": f"Found {len(ports)} serial port(s)",
        "details": {"ports": ports},
    }
    if mux_info:
        result["details"]["mux"] = {
            "running": True,
            "vserial": mux_info["vserial"],
            "tcp_port": mux_info["tcp_port"],
            "real_port": mux_info["real_port"],
        }
        result["summary"] += f" (Mux running: {mux_info['vserial']})"

    if args.json:
        output_json(result)
    else:
        if not ports:
            print("No available serial ports found.")
        else:
            print(f"Found {len(ports)} serial port(s):\n")
            for p in ports:
                chip = f" [{p['chip']}]" if p["chip"] else ""
                vid_pid = f" (VID:{p['vid']} PID:{p['pid']})" if p["vid"] else ""
                print(f"  {p['port']}: {p['description']}{chip}{vid_pid}")
        if mux_info:
            print(f"\nMux running: {mux_info['real_port']} -> TCP:{mux_info['tcp_port']} -> PTY:{mux_info['vserial']}")


if __name__ == "__main__":
    main()
