#!/usr/bin/env python3
"""Port scanning tool, supporting TCP scanning and banner grabbing."""

import argparse
import io
import json
import os
import socket
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from net_runtime import (
    get_net_config,
    save_project_config,
    update_state_entry,
)


# Common embedded ports
DEFAULT_PORTS = [
    20, 21, 22, 23, 25, 53, 67, 68, 69, 80, 102, 161, 162,
    443, 502, 554, 1883, 2404, 4840, 5060, 5683, 8080, 8443,
    8883, 20000, 44818, 47808,
]


def parse_ports(port_str):
    """Parse port string, supporting comma-separated list and ranges. Example: '80,443,8000-8100'"""
    if not port_str:
        return DEFAULT_PORTS

    ports = set()
    for part in port_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            for p in range(int(start), int(end) + 1):
                ports.add(p)
        elif part.isdigit():
            ports.add(int(part))
    return sorted(ports)


def scan_port(target, port, timeout_ms=1000, grab_banner=False):
    """Scan a single port."""
    timeout_sec = timeout_ms / 1000.0
    result = {"port": port, "state": "closed", "service": "", "banner": ""}

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout_sec)
        sock.connect((target, port))
        result["state"] = "open"

        if grab_banner:
            try:
                sock.settimeout(2)
                # Send newline to trigger banner
                sock.send(b"\r\n")
                banner = sock.recv(1024)
                result["banner"] = banner.decode("utf-8", errors="replace").strip()[:200]
            except (socket.timeout, OSError):
                pass

        sock.close()
    except (socket.timeout, ConnectionRefusedError):
        result["state"] = "closed"
    except OSError:
        result["state"] = "filtered"

    return result


# Common port to service mapping
PORT_SERVICE_MAP = {
    20: "FTP-Data", 21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP",
    53: "DNS", 67: "DHCP-Server", 68: "DHCP-Client", 69: "TFTP",
    80: "HTTP", 102: "S7comm", 161: "SNMP", 162: "SNMP-Trap",
    443: "HTTPS", 502: "Modbus", 554: "RTSP",
    1883: "MQTT", 2404: "IEC 60870-5-104", 4840: "OPC UA",
    5060: "SIP", 5683: "CoAP", 8080: "HTTP-Alt", 8443: "HTTPS-Alt",
    8883: "MQTT-TLS", 20000: "DNP3", 44818: "EtherNet/IP", 47808: "BACnet",
}


def main():
    parser = argparse.ArgumentParser(description="Port scan")
    parser.add_argument("--target", "-t", help="Target address")
    parser.add_argument("--ports", "-p", help="Port list (e.g. '80,443,8000-8100')")
    parser.add_argument("--timeout", type=int, default=0, help="Timeout in milliseconds")
    parser.add_argument("--banner", action="store_true", help="Grab banner")
    parser.add_argument("--concurrent", type=int, default=20, help="Concurrent thread count")
    parser.add_argument("--json", action="store_true", dest="output_json", help="Output JSON format")
    args = parser.parse_args()

    # Get configuration
    config, sources = get_net_config(
        cli_target=args.target,
        cli_timeout_ms=args.timeout if args.timeout > 0 else None,
        cli_scan_ports=args.ports,
    )

    target = config["target"]
    timeout_ms = config["timeout_ms"]
    port_str = config["scan_ports"]

    if not target:
        error = {
            "status": "error",
            "action": "scan",
            "error": {"code": "no_target", "message": "Target address not configured. Specify with --target or configure in .embeddedskills/config.json"},
        }
        print(json.dumps(error, ensure_ascii=False, indent=2))
        sys.exit(1)

    # Save confirmed configuration
    save_project_config(values={
        "target": target,
        "timeout_ms": timeout_ms,
        "scan_ports": port_str,
    })

    ports = parse_ports(port_str)
    open_ports = []

    with ThreadPoolExecutor(max_workers=args.concurrent) as pool:
        futures = {
            pool.submit(scan_port, target, port, timeout_ms, args.banner): port
            for port in ports
        }
        for future in as_completed(futures):
            result = future.result()
            if result["state"] == "open":
                result["service"] = PORT_SERVICE_MAP.get(result["port"], "")
                open_ports.append(result)

    open_ports.sort(key=lambda x: x["port"])

    output = {
        "status": "ok",
        "action": "scan",
        "summary": f"Scanned {target}, checked {len(ports)} ports, found {len(open_ports)} open ports",
        "details": {
            "target": target,
            "ports_scanned": len(ports),
            "open_count": len(open_ports),
            "open_ports": open_ports,
        },
    }

    if args.output_json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"[net scan] {output['summary']}")
        if open_ports:
            print(f"\n  {'PORT':<8} {'STATE':<8} {'SERVICE':<16} {'BANNER'}")
            print(f"  {'----':<8} {'----':<8} {'----':<16} {'------'}")
            for p in open_ports:
                banner = p.get("banner", "")[:40]
                print(f"  {p['port']:<8} {p['state']:<8} {p['service']:<16} {banner}")
        else:
            print("  No open ports found")

    # Update state
    update_state_entry("last_net_scan", {
        "target": target,
        "ports_scanned": len(ports),
        "open_count": len(open_ports),
    })


if __name__ == "__main__":
    main()
