"""Serial port data sender."""

import argparse
import json
import sys
import time
from pathlib import Path

from serial_runtime import (
    get_serial_config,
    open_serial_port,
    save_project_config,
    update_state_entry,
)

PARITY_MAP = {"none": "N", "even": "E", "odd": "O", "mark": "M", "space": "S"}


def output_json(obj):
    sys.stdout.buffer.write(json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


def error_exit(code, message, use_json):
    result = {"status": "error", "action": "send", "error": {"code": code, "message": message}}
    if use_json:
        output_json(result)
    else:
        print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


def build_payload(data, hex_mode, line_ending):
    if hex_mode:
        try:
            clean = data.replace(" ", "").replace("0x", "").replace(",", "")
            return bytes.fromhex(clean)
        except ValueError:
            return None
    else:
        payload = data.encode("utf-8")
        if line_ending == "cr":
            payload += b"\r"
        elif line_ending == "lf":
            payload += b"\n"
        elif line_ending == "crlf":
            payload += b"\r\n"
        return payload


def main():
    parser = argparse.ArgumentParser(description="Serial port data sender")
    parser.add_argument("data", help="Data to send")
    parser.add_argument("--port", help="Serial port device (e.g. /dev/ttyUSB0)")
    parser.add_argument("--baudrate", type=int, help="Baud rate")
    parser.add_argument("--bytesize", type=int, help="Byte size / data bits")
    parser.add_argument("--parity", help="Parity (none/even/odd)")
    parser.add_argument("--stopbits", type=int, help="Stop bits")
    parser.add_argument("--encoding", help="Encoding")
    parser.add_argument("--hex", action="store_true", help="Send in Hex mode")
    parser.add_argument("--cr", action="store_true", help="Append CR")
    parser.add_argument("--lf", action="store_true", help="Append LF")
    parser.add_argument("--crlf", action="store_true", help="Append CRLF")
    parser.add_argument("--repeat", type=int, default=1, help="Repeat count")
    parser.add_argument("--interval", type=float, default=0.1, help="Repeat interval in seconds")
    parser.add_argument("--wait-response", action="store_true", help="Wait for response")
    parser.add_argument("--response-timeout", type=float, default=2.0, help="Response timeout in seconds")
    parser.add_argument("--direct", action="store_true", help="Connect directly to real serial port, skipping mux")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    args = parser.parse_args()

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
            error_exit("multiple_candidates", f"{sources['error']}, please specify with --port", args.json)
        else:
            error_exit("config_error", sources.get("error", "Configuration error"), args.json)

    # Save confirmed configuration
    save_project_config(values={
        "port": cfg["port"],
        "baudrate": cfg["baudrate"],
        "bytesize": cfg["bytesize"],
        "parity": cfg["parity"],
        "stopbits": cfg["stopbits"],
        "encoding": cfg["encoding"],
    })

    line_ending = "crlf" if args.crlf else ("cr" if args.cr else ("lf" if args.lf else ""))

    payload = build_payload(args.data, args.hex, line_ending)
    if payload is None:
        error_exit("bad_hex", "Hex parsing failed, please check input format", args.json)

    try:
        use_mux = not args.direct
        ser = open_serial_port(cfg, use_mux=use_mux)
        if getattr(ser, "_serial_skill_using_mux", False):
            print("[mux] Warning: Sending data via multiplexer; concurrent writes in minicom may cause serial data conflict", file=sys.stderr)
    except Exception as e:
        error_exit("connect_failed", str(e), args.json)

    results = []
    try:
        for i in range(args.repeat):
            ser.write(payload)
            ser.flush()
            tx_display = payload.hex(" ") if args.hex else args.data

            entry = {"seq": i + 1, "tx": tx_display, "tx_bytes": len(payload)}

            if args.wait_response:
                ser.timeout = args.response_timeout
                rx_raw = ser.read(4096)
                if rx_raw:
                    try:
                        entry["rx"] = rx_raw.decode(cfg["encoding"], errors="replace")
                    except Exception:
                        entry["rx"] = rx_raw.hex(" ")
                    entry["rx_bytes"] = len(rx_raw)
                else:
                    entry["rx"] = ""
                    entry["rx_bytes"] = 0

            results.append(entry)

            if args.repeat > 1 and i < args.repeat - 1:
                time.sleep(args.interval)
    except Exception as e:
        error_exit("write_error", str(e), args.json)
    finally:
        ser.close()

    if args.repeat == 1:
        details = results[0]
    else:
        details = {"rounds": results, "total": len(results)}

    result = {
        "status": "ok",
        "action": "send",
        "summary": f"Sent {args.repeat} time(s) to {cfg['port']}@{cfg['baudrate']}",
        "details": details,
    }

    if args.json:
        output_json(result)
    else:
        for r in results:
            print(f"TX[{r['seq']}]: {r['tx']}")
            if "rx" in r:
                print(f"RX[{r['seq']}]: {r['rx']}")

    # Update state
    update_state_entry("last_serial_send", {
        "port": cfg["port"],
        "baudrate": cfg["baudrate"],
        "bytes_sent": len(payload) * args.repeat,
    })


if __name__ == "__main__":
    main()
