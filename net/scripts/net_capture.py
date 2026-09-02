#!/usr/bin/env python3
"""Capture tool based on tshark, supporting file saving, filtering, decode rules, and structured output."""

import argparse
import io
import json
import os
import subprocess
import sys
import signal
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from net_runtime import (
    decode_text,
    get_net_config,
    save_project_config,
    update_state_entry,
    check_tshark,
)


def build_tshark_cmd(config, args, *, output_path="", include_display_filter=True):
    exe = config["tshark_exe"]
    cmd = [exe]

    # Interface
    iface = config["interface"]
    if iface:
        cmd += ["-i", str(iface)]

    # Capture filter (BPF)
    capture_filter = config["capture_filter"]
    if capture_filter:
        cmd += ["-f", capture_filter]

    # Display filter
    display_filter = config["display_filter"]
    if display_filter and include_display_filter:
        cmd += ["-Y", display_filter]

    # Duration
    duration = config["duration"]
    cmd += ["-a", f"duration:{duration}"]

    # Output file
    if output_path:
        fmt = args.format or config["capture_format"]
        cmd += ["-w", output_path]
        if fmt == "pcap":
            cmd += ["-F", "pcap"]

    # Decode rules
    if args.decode_as:
        cmd += ["-d", args.decode_as]

    # JSON Lines output (using -T ek)
    if args.output_json and not args.output:
        cmd += ["-T", "ek"]

    return cmd, exe


def main():
    parser = argparse.ArgumentParser(description="tshark packet capture")
    parser.add_argument("--interface", "-i", help="Capture interface")
    parser.add_argument("--duration", type=int, help="Capture duration in seconds")
    parser.add_argument("--capture-filter", "-f", help="Capture filter (BPF)")
    parser.add_argument("--display-filter", "-Y", help="Display filter")
    parser.add_argument("--output", "-o", default="", help="Path to save capture file")
    parser.add_argument("--format", choices=["pcapng", "pcap"], help="Capture file format")
    parser.add_argument("--decode-as", default="", help="Custom decode rule")
    parser.add_argument("--json", action="store_true", dest="output_json", help="JSON Lines output")
    args = parser.parse_args()

    # Get configuration
    config, sources = get_net_config(
        cli_interface=args.interface,
        cli_duration=args.duration,
        cli_capture_filter=args.capture_filter,
        cli_display_filter=args.display_filter,
    )

    exe = config["tshark_exe"]

    if not check_tshark(exe):
        error = {
            "status": "error",
            "action": "capture",
            "error": {
                "code": "tshark_not_found",
                "message": f"tshark not found ({exe}). Please ensure Wireshark is installed and added to PATH",
            },
        }
        print(json.dumps(error, ensure_ascii=False, indent=2))
        sys.exit(1)

    iface = config["interface"]
    if not iface:
        error = {
            "status": "error",
            "action": "capture",
            "error": {
                "code": "no_interface",
                "message": "Capture interface not configured. Specify with --interface or configure in .embeddedskills/config.json",
            },
        }
        print(json.dumps(error, ensure_ascii=False, indent=2))
        sys.exit(1)

    # Save confirmed configuration
    save_project_config(values={
        "interface": iface,
        "duration": config["duration"],
        "capture_filter": config["capture_filter"],
        "display_filter": config["display_filter"],
    })

    filter_after_capture = bool(args.output and config.get("display_filter"))
    temp_output = ""
    output_path = args.output
    if filter_after_capture:
        fd, temp_output = tempfile.mkstemp(
            prefix="net_capture_",
            suffix=".pcap" if (args.format or config["capture_format"]) == "pcap" else ".pcapng",
        )
        os.close(fd)
        output_path = temp_output

    cmd, _ = build_tshark_cmd(
        config,
        args,
        output_path=output_path,
        include_display_filter=not filter_after_capture,
    )
    duration = config["duration"]

    print(f"[net capture] interface={iface}, duration={duration}s", file=sys.stderr)
    if config.get("capture_filter"):
        print(f"  Capture filter: {config['capture_filter']}", file=sys.stderr)
    if config.get("display_filter"):
        print(f"  Display filter: {config['display_filter']}", file=sys.stderr)
    if args.output:
        print(f"  Output file: {args.output}", file=sys.stderr)
        if filter_after_capture:
            print("  Save strategy: raw capture first, then filter offline with display filter", file=sys.stderr)
    print(f"  Command: {' '.join(cmd)}", file=sys.stderr)

    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False
        )
        stdout_data, stderr_data = proc.communicate()
        stdout_text = decode_text(stdout_data)
        stderr_output = decode_text(stderr_data)

        if stdout_text:
            print(stdout_text, end="")

        if proc.returncode != 0:
            error = {
                "status": "error",
                "action": "capture",
                "error": {
                    "code": "capture_failed",
                    "message": stderr_output.strip() or f"tshark exit code {proc.returncode}",
                },
            }
            print(json.dumps(error, ensure_ascii=False, indent=2))
            sys.exit(1)

        if filter_after_capture:
            filter_cmd = [exe, "-r", temp_output, "-Y", config["display_filter"], "-w", args.output]
            if (args.format or config["capture_format"]) == "pcap":
                filter_cmd += ["-F", "pcap"]
            if args.decode_as:
                filter_cmd += ["-d", args.decode_as]

            filtered = subprocess.run(
                filter_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,
            )
            filtered_stderr = decode_text(filtered.stderr)
            if filtered.returncode != 0:
                error = {
                    "status": "error",
                    "action": "capture",
                    "error": {
                        "code": "capture_filter_failed",
                        "message": filtered_stderr.strip() or f"Filter failed, exit code {filtered.returncode}",
                    },
                }
                print(json.dumps(error, ensure_ascii=False, indent=2))
                sys.exit(1)
            if filtered_stderr.strip():
                print(filtered_stderr, file=sys.stderr)

        if stderr_output.strip():
            print(stderr_output, file=sys.stderr)

        # Output summary
        summary = {"status": "ok", "action": "capture", "summary": f"Capture complete, duration {duration}s"}
        if args.output and os.path.exists(args.output):
            size = os.path.getsize(args.output)
            summary["summary"] += f", file: {args.output} ({size} bytes)"
            summary["details"] = {"output_file": args.output, "file_size": size}

        print(json.dumps(summary, ensure_ascii=False, indent=2), file=sys.stderr)

        # Update state
        update_state_entry("last_observe", {
            "type": "net_capture",
            "interface": iface,
            "duration": duration,
            "output_file": args.output if args.output and os.path.exists(args.output) else None,
        })

    except KeyboardInterrupt:
        proc.terminate()
        print("\n[net capture] User interrupted capture", file=sys.stderr)
    except Exception as e:
        error = {
            "status": "error",
            "action": "capture",
            "error": {"code": "capture_failed", "message": str(e)},
        }
        print(json.dumps(error, ensure_ascii=False, indent=2))
        sys.exit(1)
    finally:
        if temp_output and os.path.exists(temp_output):
            os.remove(temp_output)


if __name__ == "__main__":
    main()
