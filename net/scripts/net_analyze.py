#!/usr/bin/env python3
"""Offline pcap analysis tool based on tshark/capinfos."""

import argparse
import io
import json
import os
import re
import subprocess
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from net_runtime import (
    DEFAULT_CAPINFOS,
    DEFAULT_TSHARK,
    decode_text,
    load_local_config,
    resolve_tool_path,
)


def load_config():
    return load_local_config()


def run_cmd(cmd, timeout=30):
    try:
        result = subprocess.run(cmd, capture_output=True, text=False, timeout=timeout)
        return decode_text(result.stdout), decode_text(result.stderr), result.returncode
    except FileNotFoundError:
        return "", f"Command not found: {cmd[0]}", -1
    except subprocess.TimeoutExpired:
        return "", "Command timed out", -2


def get_capinfos_summary(capinfos_exe, pcap_file):
    """Get file-level statistics via capinfos."""
    stdout, stderr, rc = run_cmd([capinfos_exe, "-M", pcap_file])
    if rc != 0:
        return None

    info = {}
    for line in stdout.splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        val = val.strip()
        if "number of packets" in key:
            info["packet_count"] = int(val) if val.isdigit() else val
        elif "capture duration" in key:
            info["duration"] = val
        elif "file size" in key:
            info["file_size"] = val
        elif "data size" in key:
            info["data_size"] = val
        elif "first packet time" in key:
            info["first_packet"] = val
        elif "last packet time" in key:
            info["last_packet"] = val
        elif "average packet size" in key:
            info["avg_packet_size"] = val
        elif "data byte rate" in key:
            info["byte_rate"] = val
    return info


def get_protocol_hierarchy(tshark_exe, pcap_file, display_filter="", decode_as=""):
    """Get protocol hierarchy statistics."""
    cmd = [tshark_exe, "-r", pcap_file, "-q", "-z", "io,phs"]
    if display_filter:
        cmd += ["-Y", display_filter]
    if decode_as:
        cmd += ["-d", decode_as]

    stdout, _, rc = run_cmd(cmd, timeout=60)
    if rc != 0:
        return []

    protocols = []
    for line in stdout.splitlines():
        line = line.strip()
        m = re.match(r"(\S+)\s+frames:(\d+)\s+bytes:(\d+)", line)
        if m:
            protocols.append({
                "protocol": m.group(1),
                "frames": int(m.group(2)),
                "bytes": int(m.group(3)),
            })
    return protocols


def get_conversations(tshark_exe, pcap_file, display_filter="", decode_as="", top=20):
    """Get conversation statistics."""
    cmd = [tshark_exe, "-r", pcap_file, "-q", "-z", "conv,ip"]
    if display_filter:
        cmd += ["-Y", display_filter]
    if decode_as:
        cmd += ["-d", decode_as]

    stdout, _, rc = run_cmd(cmd, timeout=60)
    if rc != 0:
        return []

    conversations = []
    header_found = False
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("="):
            header_found = True
            continue
        if not header_found:
            continue
        # Format: addr_a <-> addr_b  frames_a bytes_a frames_b bytes_b frames_total bytes_total ...
        parts = re.split(r"\s+", line)
        if len(parts) >= 8 and "<->" in parts:
            idx = parts.index("<->")
            if idx >= 1 and idx + 1 < len(parts):
                conversations.append({
                    "addr_a": parts[idx - 1],
                    "addr_b": parts[idx + 1],
                    "raw": line,
                })
    return conversations[:top]


def get_endpoints(tshark_exe, pcap_file, display_filter="", decode_as="", top=20):
    """Get endpoint statistics."""
    cmd = [tshark_exe, "-r", pcap_file, "-q", "-z", "endpoints,ip"]
    if display_filter:
        cmd += ["-Y", display_filter]
    if decode_as:
        cmd += ["-d", decode_as]

    stdout, _, rc = run_cmd(cmd, timeout=60)
    if rc != 0:
        return []

    endpoints = []
    header_found = False
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("="):
            header_found = True
            continue
        if not header_found or "Address" in line or line.startswith("|"):
            continue
        parts = re.split(r"\s+", line)
        if len(parts) >= 3:
            endpoints.append({
                "address": parts[0],
                "packets": parts[1] if len(parts) > 1 else "",
                "bytes": parts[2] if len(parts) > 2 else "",
                "raw": line,
            })
    return endpoints[:top]


def detect_anomalies(tshark_exe, pcap_file, display_filter="", decode_as=""):
    """Detect common network anomalies (retransmissions, RST, errors, etc.)."""
    checks = [
        ("tcp.analysis.retransmission", "TCP retransmission"),
        ("tcp.analysis.fast_retransmission", "TCP fast retransmission"),
        ("tcp.analysis.duplicate_ack", "TCP duplicate ACK"),
        ("tcp.flags.reset==1", "TCP RST"),
        ("icmp.type==3", "ICMP unreachable"),
        ("dns.flags.rcode!=0", "DNS error"),
        ("tcp.analysis.zero_window", "TCP zero window"),
    ]

    anomalies = []
    for filt, desc in checks:
        combined = f"({filt})"
        if display_filter:
            combined = f"({display_filter}) && ({filt})"

        cmd = [tshark_exe, "-r", pcap_file, "-Y", combined, "-T", "fields", "-e", "frame.number"]
        if decode_as:
            cmd += ["-d", decode_as]

        stdout, _, rc = run_cmd(cmd, timeout=30)
        if rc == 0:
            count = len([l for l in stdout.strip().splitlines() if l.strip()])
            if count > 0:
                anomalies.append({"type": desc, "filter": filt, "count": count})

    return anomalies


def get_io_stats(tshark_exe, pcap_file, display_filter="", decode_as=""):
    """Get IO statistics."""
    cmd = [tshark_exe, "-r", pcap_file, "-q", "-z", "io,stat,1"]
    if display_filter:
        cmd += ["-Y", display_filter]
    if decode_as:
        cmd += ["-d", decode_as]

    stdout, _, rc = run_cmd(cmd, timeout=60)
    if rc != 0:
        return []

    intervals = []
    for line in stdout.splitlines():
        m = re.match(r"\|\s*([\d.]+)\s*<>\s*([\d.]+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|", line)
        if m:
            intervals.append({
                "start": float(m.group(1)),
                "end": float(m.group(2)),
                "frames": int(m.group(3)),
                "bytes": int(m.group(4)),
            })
    return intervals


def main():
    parser = argparse.ArgumentParser(description="Analyze pcap file")
    parser.add_argument("pcap_file", help="Path to pcap/pcapng file")
    parser.add_argument("--mode", default="summary",
                        choices=["summary", "protocols", "conversations", "endpoints", "io", "anomalies", "all"])
    parser.add_argument("--filter", default="", help="Display filter")
    parser.add_argument("--top", type=int, default=20, help="Display top N entries")
    parser.add_argument("--decode-as", default="", help="Decode rule")
    parser.add_argument("--export-fields", default="", help="List of fields to export")
    parser.add_argument("--output", default="", help="Output CSV path")
    parser.add_argument("--json", action="store_true", dest="output_json", help="Output JSON format")
    args = parser.parse_args()

    if not os.path.exists(args.pcap_file):
        error = {
            "status": "error",
            "action": "analyze",
            "error": {"code": "file_not_found", "message": f"File does not exist: {args.pcap_file}"},
        }
        print(json.dumps(error, ensure_ascii=False, indent=2))
        sys.exit(1)

    config = load_config()
    tshark_exe = resolve_tool_path(config.get("tshark_exe"), DEFAULT_TSHARK)
    capinfos_exe = resolve_tool_path(config.get("capinfos_exe"), DEFAULT_CAPINFOS)

    filtered_input = ""
    analysis_input = args.pcap_file

    if args.filter:
        fd, filtered_input = tempfile.mkstemp(prefix="net_analyze_filtered_", suffix=os.path.splitext(args.pcap_file)[1] or ".pcapng")
        os.close(fd)
        filter_cmd = [tshark_exe, "-r", args.pcap_file, "-Y", args.filter, "-w", filtered_input]
        if args.decode_as:
            filter_cmd += ["-d", args.decode_as]
        stdout, stderr, rc = run_cmd(filter_cmd, timeout=120)
        if rc != 0:
            error = {
                "status": "error",
                "action": "analyze",
                "error": {"code": "filter_failed", "message": stderr.strip() or "Filter failed"},
            }
            print(json.dumps(error, ensure_ascii=False, indent=2))
            sys.exit(1)
        analysis_input = filtered_input

    result = {
        "status": "ok",
        "action": "analyze",
        "summary": "",
        "details": {},
    }

    modes = [args.mode] if args.mode != "all" else [
        "summary", "protocols", "conversations", "endpoints", "io", "anomalies"
    ]

    for mode in modes:
        if mode == "summary":
            info = get_capinfos_summary(capinfos_exe, analysis_input)
            if info:
                result["details"]["summary"] = info
                result["summary"] = f"File contains {info.get('packet_count', '?')} packets"
            else:
                # Fallback to tshark statistics
                stdout, _, rc = run_cmd([tshark_exe, "-r", analysis_input, "-q", "-z", "io,stat,0"])
                result["details"]["summary"] = {"raw": stdout}

        elif mode == "protocols":
            result["details"]["protocols"] = get_protocol_hierarchy(
                tshark_exe, analysis_input, "", args.decode_as
            )

        elif mode == "conversations":
            result["details"]["conversations"] = get_conversations(
                tshark_exe, analysis_input, "", args.decode_as, args.top
            )

        elif mode == "endpoints":
            result["details"]["endpoints"] = get_endpoints(
                tshark_exe, analysis_input, "", args.decode_as, args.top
            )

        elif mode == "io":
            result["details"]["io_stats"] = get_io_stats(
                tshark_exe, analysis_input, "", args.decode_as
            )

        elif mode == "anomalies":
            result["details"]["anomalies"] = detect_anomalies(
                tshark_exe, analysis_input, "", args.decode_as
            )

    # Export fields
    if args.export_fields and args.output:
        fields = [f.strip() for f in args.export_fields.split(",")]
        cmd = [tshark_exe, "-r", analysis_input, "-T", "fields"]
        for f in fields:
            cmd += ["-e", f]
        cmd += ["-E", "header=y", "-E", "separator=,"]
        if args.decode_as:
            cmd += ["-d", args.decode_as]

        stdout, _, rc = run_cmd(cmd, timeout=120)
        if rc == 0:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(stdout)
            result["details"]["exported"] = {"file": args.output, "fields": fields}

    try:
        if args.output_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"[net analyze] {result.get('summary', 'Analysis complete')}")
            details = result["details"]
            if "summary" in details and isinstance(details["summary"], dict):
                for k, v in details["summary"].items():
                    if k != "raw":
                        print(f"  {k}: {v}")
            if "protocols" in details:
                print("\n  Protocol statistics:")
                for p in details["protocols"][:args.top]:
                    print(f"    {p['protocol']}: {p['frames']} frames, {p['bytes']} bytes")
            if "anomalies" in details and details["anomalies"]:
                print("\n  Anomaly detection:")
                for a in details["anomalies"]:
                    print(f"    {a['type']}: {a['count']}")
            if "conversations" in details:
                print("\n  Conversations:")
                for c in details["conversations"][:5]:
                    print(f"    {c['addr_a']} <-> {c['addr_b']}")
            if "endpoints" in details:
                print("\n  Endpoints:")
                for e in details["endpoints"][:5]:
                    print(f"    {e['address']}")
    finally:
        if filtered_input and os.path.exists(filtered_input):
            os.remove(filtered_input)


if __name__ == "__main__":
    main()
