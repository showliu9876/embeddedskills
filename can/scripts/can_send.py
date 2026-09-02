"""CAN message transmission: supports standard frames, extended frames, remote frames, and CAN-FD frames."""

import argparse
import json
import sys
import time
from pathlib import Path

from can_runtime import (
    add_can_connection_args,
    get_can_config,
    open_can_bus,
    save_project_config,
    update_state_entry,
)


def parse_hex_data(s):
    """Parse hex data string, supporting with or without spaces."""
    s = s.replace(" ", "").replace(",", "")
    return bytes.fromhex(s)


def output_json(result):
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


def output_json_line(obj):
    sys.stdout.buffer.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


def format_data(data):
    return " ".join(f"{b:02X}" for b in data)


def main():
    parser = argparse.ArgumentParser(description="CAN message transmission")
    add_can_connection_args(parser, include_data_bitrate=True)
    parser.add_argument("id", help="CAN ID (supports 0x prefix)")
    parser.add_argument("data", help="Data (Hex string, e.g. 'DE AD BE EF')")
    parser.add_argument("--extended", action="store_true", help="Extended frame (29-bit ID)")
    parser.add_argument("--remote", action="store_true", help="Remote frame")
    parser.add_argument("--fd", action="store_true", help="CAN-FD frame")
    parser.add_argument("--repeat", type=int, default=1, help="Number of repeat transmissions")
    parser.add_argument("--interval", type=float, default=0, help="Interval between repeat transmissions (seconds)")
    parser.add_argument("--periodic", type=float, help="Periodic transmission interval (milliseconds), press Ctrl+C to stop")
    parser.add_argument("--listen", action="store_true", help="Listen for response after sending")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    args = parser.parse_args()

    try:
        import can
    except ImportError:
        err = {"status": "error", "action": "send", "error": {"code": "import_error", "message": "python-can is not installed, please run: pip install python-can"}}
        if args.json:
            output_json(err)
        else:
            print(f"Error: {err['error']['message']}", file=sys.stderr)
        sys.exit(1)

    # Get configuration
    config, sources = get_can_config(
        cli_interface=args.interface,
        cli_channel=args.channel,
        cli_bitrate=args.bitrate,
        cli_data_bitrate=args.data_bitrate,
    )

    if config is None:
        if sources.get("need_selection"):
            err = {"status": "error", "action": "send", "error": {"code": "multiple_candidates", "message": f"{sources['error']}; please specify with --interface and --channel"}}
        else:
            err = {"status": "error", "action": "send", "error": {"code": "config_error", "message": sources.get("error", "Configuration error")}}
        if args.json:
            output_json(err)
        else:
            print(f"Error: {err['error']['message']}", file=sys.stderr)
        sys.exit(1)

    interface = config["interface"]
    channel = config["channel"]
    bitrate = config["bitrate"]
    data_bitrate = config["data_bitrate"]

    # Save confirmed configuration
    save_project_config(values={
        "interface": interface,
        "channel": channel,
        "bitrate": bitrate,
        "data_bitrate": data_bitrate,
    })

    arb_id = int(args.id, 0)
    data = parse_hex_data(args.data) if not args.remote else b""

    try:
        bus = open_can_bus(config)
        if args.fd and data_bitrate:
            # Reopen to enable FD mode
            bus = can.Bus(
                interface=interface,
                channel=channel,
                bitrate=bitrate,
                fd=True,
                data_bitrate=data_bitrate,
            )
    except Exception as e:
        err = {"status": "error", "action": "send", "error": {"code": "interface_open_failed", "message": str(e)}}
        if args.json:
            output_json(err)
        else:
            print(f"Error: Unable to open CAN interface — {e}", file=sys.stderr)
        sys.exit(1)

    msg = can.Message(
        arbitration_id=arb_id,
        data=data,
        is_extended_id=args.extended,
        is_remote_frame=args.remote,
        is_fd=args.fd,
    )

    tx_count = 0

    try:
        if args.periodic is not None:
            # Periodic transmission
            period_sec = args.periodic / 1000.0
            print(f"Periodic transmission: 0x{arb_id:03X} every {args.periodic:.0f}ms, press Ctrl+C to stop", file=sys.stderr)
            while True:
                bus.send(msg)
                tx_count += 1
                time.sleep(period_sec)
        else:
            # Normal transmission (repeatable)
            for i in range(args.repeat):
                bus.send(msg)
                tx_count += 1
                if args.interval > 0 and i < args.repeat - 1:
                    time.sleep(args.interval)
    except KeyboardInterrupt:
        pass

    # Transmission result
    tx_info = {
        "id": f"0x{arb_id:03X}",
        "data": format_data(data),
        "dlc": len(data),
        "extended": args.extended,
        "remote": args.remote,
        "fd": args.fd,
        "count": tx_count,
    }

    # Listen for response
    rx_list = []
    if args.listen:
        listen_timeout = 2.0
        listen_start = time.time()
        while (time.time() - listen_start) < listen_timeout:
            resp = bus.recv(timeout=0.5)
            if resp and resp.arbitration_id != arb_id:
                rx_entry = {
                    "timestamp": round(resp.timestamp, 6),
                    "id": f"0x{resp.arbitration_id:03X}",
                    "dlc": resp.dlc,
                    "data": format_data(resp.data),
                    "is_fd": resp.is_fd,
                }
                rx_list.append(rx_entry)
                if args.json:
                    output_json_line(rx_entry)
                else:
                    print(f"  <- [{resp.timestamp:.6f}] 0x{resp.arbitration_id:03X} [{resp.dlc}] {format_data(resp.data)}")

    bus.shutdown()

    result = {
        "status": "ok",
        "action": "send",
        "summary": f"Sent {tx_count} frame(s) to 0x{arb_id:03X}",
        "details": {"tx": tx_info},
    }
    if args.listen:
        result["details"]["rx"] = rx_list
        result["summary"] += f", received {len(rx_list)} response frame(s)"

    if args.json:
        output_json(result)
    else:
        print(f"\nSent {tx_count} frame(s): 0x{arb_id:03X} [{len(data)}] {format_data(data)}")
        if args.listen:
            print(f"Received {len(rx_list)} response frame(s)")

    # Update state
    update_state_entry("last_can_send", {
        "interface": interface,
        "channel": channel,
        "id": f"0x{arb_id:03X}",
        "count": tx_count,
    })


if __name__ == "__main__":
    main()
