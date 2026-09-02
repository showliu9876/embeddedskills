"""CAN database decoding: decode single frames or log files using DBC/ARXML/KCD files."""

import argparse
import json
import sys
from pathlib import Path


def parse_hex_data(s):
    s = s.replace(" ", "").replace(",", "")
    return bytes.fromhex(s)


def output_json(result):
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    sys.stdout.buffer.flush()


def load_database(db_path, db_format="auto"):
    """Load database file."""
    import cantools

    path = Path(db_path)
    if not path.exists():
        return None, f"Database file does not exist: {db_path}"

    try:
        if db_format == "auto":
            db = cantools.database.load_file(str(path))
        else:
            db = cantools.database.Database()
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            format_map = {
                "dbc": "dbc",
                "arxml": "autosar",
                "kcd": "kcd",
                "sym": "sym",
                "cdd": "cdd",
            }
            fmt = format_map.get(db_format)
            if fmt:
                db.add_dbc_string(content) if fmt == "dbc" else db.add_autosar_string(content) if fmt == "autosar" else None
                # Fall back to load_file for non-dbc/autosar formats
                if fmt not in ("dbc", "autosar"):
                    db = cantools.database.load_file(str(path))
            else:
                return None, f"Unsupported database format: {db_format}"
        return db, None
    except Exception as e:
        return None, f"Failed to load database: {e}"


def list_messages(db, signal_filter=None):
    """List message definitions in the database."""
    messages = []
    for msg in db.messages:
        signals = []
        for sig in msg.signals:
            if signal_filter and signal_filter.lower() not in sig.name.lower():
                continue
            sig_info = {
                "name": sig.name,
                "start_bit": sig.start,
                "length": sig.length,
                "unit": sig.unit or "",
                "min": sig.minimum,
                "max": sig.maximum,
            }
            signals.append(sig_info)

        if signal_filter and not signals:
            continue

        messages.append({
            "name": msg.name,
            "id": f"0x{msg.frame_id:03X}",
            "dlc": msg.length,
            "signals": signals,
        })
    return messages


def decode_single(db, arb_id, data):
    """Decode a single frame."""
    try:
        msg = db.get_message_by_frame_id(arb_id)
    except KeyError:
        return None, f"Definition for ID 0x{arb_id:03X} not found in database"

    try:
        decoded = msg.decode(data)
        signals = []
        for k, v in decoded.items():
            sig_info = {"name": k, "value": round(v, 6) if isinstance(v, float) else v}
            # Find signal unit
            for sig in msg.signals:
                if sig.name == k:
                    sig_info["unit"] = sig.unit or ""
                    break
            signals.append(sig_info)
        return {"message": msg.name, "id": f"0x{arb_id:03X}", "signals": signals}, None
    except Exception as e:
        return None, f"Decoding failed: {e}"


def decode_log_file(db, log_path, signal_filter=None):
    """Decode log file."""
    import can

    path = Path(log_path)
    if not path.exists():
        return None, f"Log file does not exist: {log_path}"

    results = []
    errors = 0

    try:
        reader = can.LogReader(str(path))
        for msg in reader:
            try:
                db_msg = db.get_message_by_frame_id(msg.arbitration_id)
                decoded = db_msg.decode(msg.data)
                if signal_filter:
                    decoded = {k: v for k, v in decoded.items() if signal_filter.lower() in k.lower()}
                    if not decoded:
                        continue
                decoded = {k: round(v, 6) if isinstance(v, float) else v for k, v in decoded.items()}
                results.append({
                    "timestamp": round(msg.timestamp, 6),
                    "message": db_msg.name,
                    "id": f"0x{msg.arbitration_id:03X}",
                    "decoded": decoded,
                })
            except (KeyError, Exception):
                errors += 1
                continue
    except Exception as e:
        return None, f"Failed to read log: {e}"

    return {"frames": results, "decoded_count": len(results), "error_count": errors}, None


def main():
    parser = argparse.ArgumentParser(description="CAN database decoding")
    parser.add_argument("db_file", help="Database file path (DBC/ARXML/KCD/SYM/CDD)")
    parser.add_argument("--db-format", default="auto", help="Database format (auto|dbc|arxml|kcd|sym|cdd)")
    parser.add_argument("--id", help="Single frame CAN ID (supports 0x prefix)")
    parser.add_argument("--data", help="Single frame data (Hex)")
    parser.add_argument("--log", help="Log file path")
    parser.add_argument("--signal", help="Filter by signal name")
    parser.add_argument("--list", action="store_true", help="List all message definitions in database")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    args = parser.parse_args()

    try:
        import cantools  # noqa: F401
    except ImportError:
        err = {"status": "error", "action": "decode", "error": {"code": "import_error", "message": "cantools is not installed, please run: pip install cantools"}}
        if args.json:
            output_json(err)
        else:
            print(f"Error: {err['error']['message']}", file=sys.stderr)
        sys.exit(1)

    db, err = load_database(args.db_file, args.db_format)
    if err:
        result = {"status": "error", "action": "decode", "error": {"code": "db_load_failed", "message": err}}
        if args.json:
            output_json(result)
        else:
            print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    # List message definitions
    if args.list:
        messages = list_messages(db, args.signal)
        result = {
            "status": "ok",
            "action": "decode",
            "summary": f"Database contains {len(messages)} message(s)",
            "details": {"messages": messages},
        }
        if args.json:
            output_json(result)
        else:
            for m in messages:
                print(f"\n{m['name']} ({m['id']}) DLC={m['dlc']}")
                for s in m["signals"]:
                    unit = f" [{s['unit']}]" if s["unit"] else ""
                    print(f"  {s['name']}: bit {s['start_bit']}+{s['length']}{unit} ({s['min']}~{s['max']})")
        return

    # Decode single frame
    if args.id and args.data:
        arb_id = int(args.id, 0)
        data = parse_hex_data(args.data)
        decoded, err = decode_single(db, arb_id, data)
        if err:
            result = {"status": "error", "action": "decode", "error": {"code": "decode_failed", "message": err}}
            if args.json:
                output_json(result)
            else:
                print(f"Error: {err}", file=sys.stderr)
            sys.exit(1)

        result = {
            "status": "ok",
            "action": "decode",
            "summary": f"Decoded {decoded['message']} ({decoded['id']})",
            "details": decoded,
        }
        if args.json:
            output_json(result)
        else:
            print(f"\n{decoded['message']} ({decoded['id']})")
            for s in decoded["signals"]:
                unit = f" {s.get('unit', '')}" if s.get("unit") else ""
                print(f"  {s['name']} = {s['value']}{unit}")
        return

    # Decode log
    if args.log:
        log_result, err = decode_log_file(db, args.log, args.signal)
        if err:
            result = {"status": "error", "action": "decode", "error": {"code": "log_decode_failed", "message": err}}
            if args.json:
                output_json(result)
            else:
                print(f"Error: {err}", file=sys.stderr)
            sys.exit(1)

        result = {
            "status": "ok",
            "action": "decode",
            "summary": f"Decoded {log_result['decoded_count']} frame(s) ({log_result['error_count']} frame(s) failed to decode)",
            "details": log_result,
        }
        if args.json:
            output_json(result)
        else:
            for f in log_result["frames"]:
                sigs = ", ".join(f"{k}={v}" for k, v in f["decoded"].items())
                print(f"[{f['timestamp']:.6f}] {f['message']} ({f['id']}): {sigs}")
            print(f"\nDecoded {log_result['decoded_count']} frame(s), {log_result['error_count']} frame(s) failed to decode")
        return

    # Prompt if no operation specified
    print("Please specify an operation: --list to list definitions, --id + --data to decode single frame, --log to decode log", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
