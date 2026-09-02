"""CAN bus monitoring: continuously read messages, supports filtering, DBC decoding, and CAN-FD."""

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


def parse_id_list(s):
    """Parse comma-separated CAN ID list, supporting 0x prefix."""
    if not s:
        return None
    ids = set()
    for part in s.split(","):
        part = part.strip()
        if part:
            ids.add(int(part, 0))
    return ids


def output_json_line(obj):
    sys.stdout.buffer.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


def format_data(data):
    return " ".join(f"{b:02X}" for b in data)


def main():
    parser = argparse.ArgumentParser(description="CAN bus real-time monitor")
    add_can_connection_args(parser, include_data_bitrate=True)
    parser.add_argument("--fd", action="store_true", help="Enable CAN-FD mode")
    parser.add_argument("--filter-id", help="Only show specified IDs (comma-separated)")
    parser.add_argument("--exclude-id", help="Exclude specified IDs (comma-separated)")
    parser.add_argument("--dbc", help="DBC database file path for decoding")
    parser.add_argument("--timeout", type=float, help="Monitoring duration (seconds)")
    parser.add_argument("--json", action="store_true", help="Output in JSON Lines format")
    args = parser.parse_args()

    try:
        import can
    except ImportError:
        err = {"status": "error", "action": "monitor", "error": {"code": "import_error", "message": "python-can is not installed, please run: pip install python-can"}}
        if args.json:
            output_json_line(err)
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
            err = {"status": "error", "action": "monitor", "error": {"code": "multiple_candidates", "message": f"{sources['error']}; please specify with --interface and --channel"}}
        else:
            err = {"status": "error", "action": "monitor", "error": {"code": "config_error", "message": sources.get("error", "Configuration error")}}
        if args.json:
            output_json_line(err)
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

    filter_ids = parse_id_list(args.filter_id)
    exclude_ids = parse_id_list(args.exclude_id)

    # Load DBC
    db = None
    if args.dbc:
        try:
            import cantools
            db = cantools.database.load_file(args.dbc)
        except ImportError:
            print("Warning: cantools is not installed, DBC decoding unavailable", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Failed to load DBC: {e}", file=sys.stderr)

    # Connect to bus
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
        err = {"status": "error", "action": "monitor", "error": {"code": "interface_open_failed", "message": str(e)}}
        if args.json:
            output_json_line(err)
        else:
            print(f"Error: Unable to open CAN interface — {e}", file=sys.stderr)
        sys.exit(1)

    start = time.time()
    count = 0

    try:
        while True:
            if args.timeout and (time.time() - start) >= args.timeout:
                break

            remaining = None
            if args.timeout:
                remaining = args.timeout - (time.time() - start)
                if remaining <= 0:
                    break

            msg = bus.recv(timeout=min(remaining, 1.0) if remaining else 1.0)
            if msg is None:
                continue

            arb_id = msg.arbitration_id
            if filter_ids and arb_id not in filter_ids:
                continue
            if exclude_ids and arb_id in exclude_ids:
                continue

            count += 1

            # Attempt DBC decoding
            decoded = None
            if db:
                try:
                    db_msg = db.get_message_by_frame_id(arb_id)
                    decoded = db_msg.decode(msg.data)
                    decoded = {k: round(v, 6) if isinstance(v, float) else v for k, v in decoded.items()}
                except Exception:
                    pass

            if args.json:
                obj = {
                    "timestamp": round(msg.timestamp, 6),
                    "id": f"0x{arb_id:03X}",
                    "dlc": msg.dlc,
                    "data": format_data(msg.data),
                    "is_fd": msg.is_fd,
                }
                if decoded:
                    obj["decoded"] = decoded
                output_json_line(obj)
            else:
                fd_flag = " [FD]" if msg.is_fd else ""
                dec_str = ""
                if decoded:
                    dec_str = " | " + ", ".join(f"{k}={v}" for k, v in decoded.items())
                print(f"[{msg.timestamp:.6f}] 0x{arb_id:03X} [{msg.dlc}] {format_data(msg.data)}{fd_flag}{dec_str}")

    except KeyboardInterrupt:
        pass
    finally:
        bus.shutdown()
        elapsed = time.time() - start
        print(f"\nMonitoring ended: {count} frames, {elapsed:.1f} seconds", file=sys.stderr)

    # Update state
    update_state_entry("last_observe", {
        "type": "can_monitor",
        "interface": interface,
        "channel": channel,
        "frames": count,
        "duration_sec": round(elapsed, 1),
    })


if __name__ == "__main__":
    main()
