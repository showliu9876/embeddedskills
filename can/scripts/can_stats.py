"""CAN bus statistics: bus load, ID distribution, frame rate, and data changes."""

import argparse
import json
import sys
import time
from collections import defaultdict
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
    parser = argparse.ArgumentParser(description="CAN bus statistics")
    add_can_connection_args(parser)
    parser.add_argument("--duration", type=float, default=5.0, help="Statistics duration (seconds, default: 5)")
    parser.add_argument("--top", type=int, default=20, help="Display top N IDs")
    parser.add_argument("--watch", help="List of IDs to watch specifically (comma-separated)")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    args = parser.parse_args()

    try:
        import can
    except ImportError:
        err = {"status": "error", "action": "stats", "error": {"code": "import_error", "message": "python-can is not installed, please run: pip install python-can"}}
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
            err = {"status": "error", "action": "stats", "error": {"code": "multiple_candidates", "message": f"{sources['error']}; please specify with --interface and --channel"}}
        else:
            err = {"status": "error", "action": "stats", "error": {"code": "config_error", "message": sources.get("error", "Configuration error")}}
        if args.json:
            output_json(err)
        else:
            print(f"Error: {err['error']['message']}", file=sys.stderr)
        sys.exit(1)

    interface = config["interface"]
    channel = config["channel"]
    bitrate = config["bitrate"]

    # Save confirmed configuration
    save_project_config(values={
        "interface": interface,
        "channel": channel,
        "bitrate": bitrate,
    })

    watch_ids = parse_id_list(args.watch)

    try:
        bus = open_can_bus(config)
    except Exception as e:
        err = {"status": "error", "action": "stats", "error": {"code": "interface_open_failed", "message": str(e)}}
        if args.json:
            output_json(err)
        else:
            print(f"Error: Unable to open CAN interface — {e}", file=sys.stderr)
        sys.exit(1)

    # Statistics data
    id_count = defaultdict(int)
    id_bytes = defaultdict(int)
    id_last_data = {}
    id_data_changes = defaultdict(int)
    total_bits = 0

    start = time.time()
    total_frames = 0

    print(f"Collecting statistics ({args.duration} seconds)...", file=sys.stderr)

    try:
        while True:
            elapsed = time.time() - start
            if elapsed >= args.duration:
                break

            remaining = args.duration - elapsed
            msg = bus.recv(timeout=min(remaining, 0.5))
            if msg is None:
                continue

            total_frames += 1
            arb_id = msg.arbitration_id
            id_count[arb_id] += 1
            id_bytes[arb_id] += msg.dlc

            # Estimate bus bits: SOF(1) + ID(11/29) + Control(6) + Data(dlc*8) + CRC(15) + ACK(2) + EOF(7) + IFS(3)
            if msg.is_extended_id:
                frame_bits = 1 + 29 + 6 + msg.dlc * 8 + 15 + 2 + 7 + 3
            else:
                frame_bits = 1 + 11 + 6 + msg.dlc * 8 + 15 + 2 + 7 + 3
            total_bits += frame_bits

            # Data change detection
            data_hex = msg.data.hex()
            if arb_id in id_last_data and id_last_data[arb_id] != data_hex:
                id_data_changes[arb_id] += 1
            id_last_data[arb_id] = data_hex

    except KeyboardInterrupt:
        pass
    finally:
        bus.shutdown()

    actual_duration = time.time() - start
    bus_bitrate = bitrate if bitrate else 500000  # Default to 500k for estimation
    bus_load = (total_bits / (actual_duration * bus_bitrate)) * 100 if actual_duration > 0 else 0

    # Sort ID list
    sorted_ids = sorted(id_count.keys(), key=lambda x: id_count[x], reverse=True)

    ids_detail = []
    for arb_id in sorted_ids[:args.top]:
        entry = {
            "id": f"0x{arb_id:03X}",
            "count": id_count[arb_id],
            "rate_hz": round(id_count[arb_id] / actual_duration, 1) if actual_duration > 0 else 0,
            "total_bytes": id_bytes[arb_id],
            "data_changes": id_data_changes.get(arb_id, 0),
            "last_data": format_data(bytes.fromhex(id_last_data.get(arb_id, ""))),
        }
        ids_detail.append(entry)

    # Additional output for watched IDs
    watch_detail = []
    if watch_ids:
        for arb_id in sorted(watch_ids):
            if arb_id in id_count:
                watch_detail.append({
                    "id": f"0x{arb_id:03X}",
                    "count": id_count[arb_id],
                    "rate_hz": round(id_count[arb_id] / actual_duration, 1) if actual_duration > 0 else 0,
                    "data_changes": id_data_changes.get(arb_id, 0),
                    "last_data": format_data(bytes.fromhex(id_last_data.get(arb_id, ""))),
                })
            else:
                watch_detail.append({
                    "id": f"0x{arb_id:03X}",
                    "count": 0,
                    "rate_hz": 0,
                    "data_changes": 0,
                    "last_data": "",
                })

    result = {
        "status": "ok",
        "action": "stats",
        "summary": f"Received {total_frames} frames across {len(id_count)} distinct IDs in {actual_duration:.1f}s, estimated bus load ~{bus_load:.1f}%",
        "details": {
            "duration_sec": round(actual_duration, 1),
            "total_frames": total_frames,
            "unique_ids": len(id_count),
            "bus_load_percent": round(bus_load, 1),
            "bus_load_note": "Estimated value based on standard frame bit count",
            "ids": ids_detail,
        },
    }
    if watch_detail:
        result["details"]["watched"] = watch_detail

    if args.json:
        output_json(result)
    else:
        print(f"\nStatistics results ({actual_duration:.1f} seconds):")
        print(f"  Total frames: {total_frames}")
        print(f"  Distinct IDs: {len(id_count)}")
        print(f"  Bus load: ~{bus_load:.1f}% (estimated)")
        print(f"\n  {'ID':<12} {'Frames':>8} {'Rate(Hz)':>10} {'Changes':>8} {'Latest Data'}")
        print(f"  {'─'*12} {'─'*8} {'─'*10} {'─'*8} {'─'*24}")
        for entry in ids_detail:
            print(f"  {entry['id']:<12} {entry['count']:>8} {entry['rate_hz']:>10.1f} {entry['data_changes']:>8} {entry['last_data']}")

        if watch_detail:
            print(f"\n  Watched IDs:")
            for entry in watch_detail:
                print(f"  {entry['id']}: {entry['count']} frames, {entry['rate_hz']:.1f} Hz, {entry['data_changes']} changes, latest: {entry['last_data']}")

    # Update state
    update_state_entry("last_observe", {
        "type": "can_stats",
        "interface": interface,
        "channel": channel,
        "frames": total_frames,
        "unique_ids": len(id_count),
        "duration_sec": round(actual_duration, 1),
    })


if __name__ == "__main__":
    main()
