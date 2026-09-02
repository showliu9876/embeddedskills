"""Serial port real-time text monitor."""

import argparse
import json
import re
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from serial_runtime import (
    get_serial_config,
    open_serial_port,
    save_project_config,
    update_state_entry,
    make_timing,
)

PARITY_MAP = {"none": "N", "even": "E", "odd": "O", "mark": "M", "space": "S"}
IDLE_FLUSH_SEC = 0.2


def output_json(obj):
    sys.stdout.buffer.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


def error_exit(action, code, message, use_json):
    result = {"status": "error", "action": action, "error": {"code": code, "message": message}}
    if use_json:
        output_json(result)
    else:
        print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


def emit_line(text, cfg, args, include_re, exclude_re):
    if include_re:
        try:
            if not include_re.search(text):
                return False
        except Exception:
            pass

    if exclude_re:
        try:
            if exclude_re.search(text):
                return False
        except Exception:
            pass

    now = datetime.now().isoformat(timespec="milliseconds")
    if args.json:
        output_json({"timestamp": now, "port": cfg["port"], "baudrate": cfg["baudrate"], "text": text})
    else:
        prefix = f"[{now}] " if args.timestamp else ""
        print(f"{prefix}{text}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Serial port real-time text monitor")
    parser.add_argument("--port", help="Serial port device (e.g. /dev/ttyUSB0)")
    parser.add_argument("--baudrate", type=int, help="Baud rate")
    parser.add_argument("--bytesize", type=int, help="Byte size / data bits")
    parser.add_argument("--parity", help="Parity (none/even/odd)")
    parser.add_argument("--stopbits", type=int, help="Stop bits")
    parser.add_argument("--encoding", help="Encoding")
    parser.add_argument("--timestamp", action="store_true", help="Display timestamps")
    parser.add_argument("--filter", help="Regex filter (only show matching lines)")
    parser.add_argument("--exclude", help="Regex exclusion (hide matching lines)")
    parser.add_argument("--timeout", type=float, default=0, help="Timeout in seconds, 0=unlimited")
    parser.add_argument("--direct", action="store_true", help="Connect directly to real serial port, skipping mux")
    parser.add_argument("--json", action="store_true", help="Output in JSON Lines format")
    args = parser.parse_args()

    start_time = time.time()

    # Get configuration
    cfg, sources = get_serial_config(
        cli_port=args.port,
        cli_baudrate=args.baudrate,
        cli_bytesize=args.bytesize,
        cli_parity=args.parity,
        cli_stopbits=args.stopbits,
        cli_encoding=args.encoding,
    )

    if cfg is None:
        if sources.get("need_selection"):
            # Multiple candidates
            error_exit("monitor", "multiple_candidates", f"{sources['error']}, please specify with --port", args.json)
        else:
            error_exit("monitor", "config_error", sources.get("error", "Configuration error"), args.json)

    # Save confirmed configuration
    save_project_config(values={
        "port": cfg["port"],
        "baudrate": cfg["baudrate"],
        "bytesize": cfg["bytesize"],
        "parity": cfg["parity"],
        "stopbits": cfg["stopbits"],
        "encoding": cfg["encoding"],
    })

    include_re = None
    exclude_re = None
    if args.filter:
        try:
            include_re = re.compile(args.filter)
        except re.error:
            error_exit("monitor", "bad_regex", f"Invalid regex: {args.filter}", args.json)
    if args.exclude:
        try:
            exclude_re = re.compile(args.exclude)
        except re.error:
            error_exit("monitor", "bad_regex", f"Invalid regex: {args.exclude}", args.json)

    try:
        use_mux = not args.direct
        ser = open_serial_port(cfg, use_mux=use_mux)
        if getattr(ser, "_serial_skill_using_mux", False):
            print("[mux] Connected via multiplexer; avoid concurrent writes in minicom to prevent data conflict", file=sys.stderr)
        ser.timeout = 0.1
    except Exception as e:
        error_exit("monitor", "connect_failed", str(e), args.json)

    line_count = 0
    running = True

    def on_signal(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    encoding = cfg.get("encoding", "utf-8")
    text_buffer = ""
    last_data_at = 0.0
    skip_leading_lf = False

    try:
        while running:
            if args.timeout > 0 and (time.time() - start_time) >= args.timeout:
                break

            read_size = max(1, getattr(ser, "in_waiting", 0) or 1)
            raw = ser.read(read_size)
            if not raw:
                if text_buffer and last_data_at and (time.time() - last_data_at) >= IDLE_FLUSH_SEC:
                    if emit_line(text_buffer, cfg, args, include_re, exclude_re):
                        line_count += 1
                    text_buffer = ""
                continue

            try:
                chunk = raw.decode(encoding, errors="replace")
            except Exception:
                chunk = raw.hex()
            if skip_leading_lf and chunk.startswith("\n"):
                chunk = chunk[1:]
            skip_leading_lf = chunk.endswith("\r")
            text_buffer += chunk.replace("\r\n", "\n").replace("\r", "\n")
            last_data_at = time.time()

            parts = text_buffer.split("\n")
            if text_buffer.endswith("\n"):
                complete_lines = parts[:-1]
                text_buffer = ""
            else:
                complete_lines = parts[:-1]
                text_buffer = parts[-1]

            for text in complete_lines:
                if emit_line(text, cfg, args, include_re, exclude_re):
                    line_count += 1

    except Exception as e:
        error_exit("monitor", "read_error", str(e), args.json)
    finally:
        if text_buffer:
            if emit_line(text_buffer, cfg, args, include_re, exclude_re):
                line_count += 1
        ser.close()

    duration = round(time.time() - start_time, 1)
    summary = f"Monitor finished, total {line_count} line(s), elapsed {duration}s\n"
    sys.stderr.buffer.write(summary.encode("utf-8"))
    sys.stderr.buffer.flush()

    # Update state
    update_state_entry("last_observe", {
        "type": "serial_monitor",
        "port": cfg["port"],
        "baudrate": cfg["baudrate"],
        "lines": line_count,
        "duration_sec": duration,
    })


if __name__ == "__main__":
    main()
