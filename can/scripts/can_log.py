"""CAN bus data logging: save messages to ASC / BLF / CSV / LOG files."""

import argparse
import json
import os
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
    if not s:
        return None
    ids = set()
    for part in s.split(","):
        part = part.strip()
        if part:
            ids.add(int(part, 0))
    return ids


def format_data(data):
    return " ".join(f"{b:02X}" for b in data)


def output_json(result):
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


def main():
    parser = argparse.ArgumentParser(description="CAN bus data logging")
    add_can_connection_args(parser)
    parser.add_argument("--output", "-o", help="Output file path (format selected by extension: .asc/.blf/.csv/.log)")
    parser.add_argument("--duration", type=float, help="Logging duration (seconds)")
    parser.add_argument("--max-count", type=int, help="Maximum number of frames to log")
    parser.add_argument("--filter-id", help="Log only specified IDs (comma-separated)")
    parser.add_argument("--console", action="store_true", help="Also output to console")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    args = parser.parse_args()

    try:
        import can
    except ImportError:
        err = {"status": "error", "action": "log", "error": {"code": "import_error", "message": "python-can is not installed, please run: pip install python-can"}}
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
    )

    if config is None:
        if sources.get("need_selection"):
            err = {"status": "error", "action": "log", "error": {"code": "multiple_candidates", "message": f"{sources['error']}; please specify with --interface and --channel"}}
        else:
            err = {"status": "error", "action": "log", "error": {"code": "config_error", "message": sources.get("error", "Configuration error")}}
        if args.json:
            output_json(err)
        else:
            print(f"Error: {err['error']['message']}", file=sys.stderr)
        sys.exit(1)

    interface = config["interface"]
    channel = config["channel"]
    bitrate = config["bitrate"]
    log_dir = config["log_dir"]

    # Save confirmed configuration
    save_project_config(values={
        "interface": interface,
        "channel": channel,
        "bitrate": bitrate,
    })

    # Determine output file
    if args.output:
        output_path = Path(args.output)
    else:
        os.makedirs(log_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_path = Path(log_dir) / f"can_{timestamp}.asc"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    filter_ids = parse_id_list(args.filter_id)

    try:
        bus = open_can_bus(config)
    except Exception as e:
        err = {"status": "error", "action": "log", "error": {"code": "interface_open_failed", "message": str(e)}}
        if args.json:
            output_json(err)
        else:
            print(f"Error: Unable to open CAN interface — {e}", file=sys.stderr)
        sys.exit(1)

    # Select logger based on file extension
    try:
        logger = can.Logger(str(output_path))
    except Exception as e:
        bus.shutdown()
        err = {"status": "error", "action": "log", "error": {"code": "logger_init_failed", "message": str(e)}}
        if args.json:
            output_json(err)
        else:
            print(f"Error: Unable to create log file — {e}", file=sys.stderr)
        sys.exit(1)

    start = time.time()
    count = 0

    print(f"Started logging to {output_path} ...", file=sys.stderr)

    try:
        while True:
            if args.duration and (time.time() - start) >= args.duration:
                break
            if args.max_count and count >= args.max_count:
                break

            remaining = None
            if args.duration:
                remaining = args.duration - (time.time() - start)
                if remaining <= 0:
                    break

            msg = bus.recv(timeout=min(remaining, 1.0) if remaining else 1.0)
            if msg is None:
                continue

            if filter_ids and msg.arbitration_id not in filter_ids:
                continue

            logger.on_message_received(msg)
            count += 1

            if args.console:
                print(f"[{msg.timestamp:.6f}] 0x{msg.arbitration_id:03X} [{msg.dlc}] {format_data(msg.data)}", file=sys.stderr)

    except KeyboardInterrupt:
        pass
    finally:
        logger.stop()
        bus.shutdown()

    elapsed = time.time() - start
    result = {
        "status": "ok",
        "action": "log",
        "summary": f"Logged {count} frames to {output_path}",
        "details": {
            "file": str(output_path),
            "frames": count,
            "duration_sec": round(elapsed, 1),
        },
    }

    if args.json:
        output_json(result)
    else:
        print(f"\nLogging complete: {count} frames, {elapsed:.1f} seconds -> {output_path}", file=sys.stderr)

    # Update state
    update_state_entry("last_observe", {
        "type": "can_log",
        "interface": interface,
        "channel": channel,
        "file": str(output_path),
        "frames": count,
        "duration_sec": round(elapsed, 1),
    })


if __name__ == "__main__":
    main()
