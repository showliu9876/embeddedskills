#!/usr/bin/env python3
"""Connectivity test tool, supporting ICMP/TCP ping, batch testing, and route tracing."""

import argparse
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from net_runtime import (
    get_net_config,
    save_project_config,
    update_state_entry,
)


IS_WINDOWS = os.name == "nt"
# Windows console tools emit the OEM code page (gbk on zh-CN); Linux tools emit UTF-8.
TOOL_ENCODING = "gbk" if IS_WINDOWS else "utf-8"


def icmp_ping(target, count=4, timeout_ms=1000):
    """Use system ping command to perform ICMP test (Linux iputils first, Windows fallback)."""
    timeout_sec = max(1, timeout_ms // 1000)
    if IS_WINDOWS:
        cmd = ["ping", "-n", str(count), "-w", str(timeout_ms), target]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(timeout_sec), target]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding=TOOL_ENCODING,
                                errors="replace", timeout=count * timeout_sec + 10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"target": target, "reachable": False, "error": "ping command timed out or unavailable"}

    output = result.stdout
    reachable = False
    sent = received = 0
    avg_ms = None

    for line in output.splitlines():
        # Summary line: Linux "4 packets transmitted, 4 received", then Windows zh-CN / en
        m = re.search(r"(\d+)\s+packets transmitted,\s*(\d+)\s+(?:packets\s+)?received", line)
        if not m:
            m = re.search(r"\u5df2\u53d1\u9001\s*=\s*(\d+).*\u5df2\u63a5\u6536\s*=\s*(\d+)", line)
        if not m:
            m = re.search(r"Sent\s*=\s*(\d+).*Received\s*=\s*(\d+)", line, re.IGNORECASE)
        if m:
            sent = int(m.group(1))
            received = int(m.group(2))
            reachable = received > 0

        # Average latency: Linux "rtt min/avg/max/mdev = a/b/c/d ms", then Windows zh-CN / en
        m2 = re.search(r"min/avg/max[^=]*=\s*[\d.]+/([\d.]+)/", line)
        if m2:
            avg_ms = round(float(m2.group(1)), 1)
            continue
        m2 = re.search(r"\u5e73\u5747\s*=\s*(\d+)ms", line)
        if not m2:
            m2 = re.search(r"Average\s*=\s*(\d+)ms", line, re.IGNORECASE)
        if m2:
            avg_ms = int(m2.group(1))

    return {
        "target": target,
        "reachable": reachable,
        "sent": sent,
        "received": received,
        "loss_rate": f"{((sent - received) / sent * 100):.0f}%" if sent > 0 else "N/A",
        "avg_ms": avg_ms,
    }


def tcp_ping(target, port, timeout_ms=1000):
    """TCP connectivity test."""
    timeout_sec = timeout_ms / 1000.0
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout_sec)
        start = __import__("time").time()
        sock.connect((target, port))
        elapsed = (__import__("time").time() - start) * 1000
        sock.close()
        return {"target": target, "port": port, "reachable": True, "latency_ms": round(elapsed, 1)}
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        return {"target": target, "port": port, "reachable": False, "error": str(e)}


MAX_HOPS = 30


def _is_inetutils_traceroute():
    """GNU inetutils traceroute has no -n (it never resolves names unless --resolve-hostnames)."""
    try:
        result = subprocess.run(["traceroute", "--version"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "inetutils" in (result.stdout + result.stderr).lower()


def traceroute_command(target, timeout_ms):
    """Pick a route-tracing command: traceroute, then tracepath, Windows tracert last."""
    timeout_sec = max(1, timeout_ms // 1000)
    if not IS_WINDOWS and shutil.which("traceroute"):
        numeric = [] if _is_inetutils_traceroute() else ["-n"]
        return ["traceroute", *numeric, "-w", str(timeout_sec), "-m", str(MAX_HOPS), target]
    if not IS_WINDOWS and shutil.which("tracepath"):
        return ["tracepath", "-n", "-m", str(MAX_HOPS), target]
    return ["tracert", "-d", "-w", str(timeout_ms), "-h", str(MAX_HOPS), target]


def traceroute(target, timeout_ms=1000):
    """Route tracing."""
    timeout_sec = max(1, timeout_ms // 1000)
    cmd = traceroute_command(target, timeout_ms)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding=TOOL_ENCODING,
                                errors="replace", timeout=max(60, MAX_HOPS * timeout_sec + 10))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"target": target, "hops": [], "error": f"{cmd[0]} timed out or unavailable"}

    hops = []
    for line in result.stdout.splitlines():
        m = re.match(r"\s*(\d+)\s+(.+)", line)
        if m:
            hop_num = int(m.group(1))
            rest = m.group(2).strip()
            hops.append({"hop": hop_num, "detail": rest})

    reachable = any(target in hop["detail"] for hop in hops)
    return {"target": target, "hops": hops, "reachable": reachable}


def main():
    parser = argparse.ArgumentParser(description="Connectivity test")
    parser.add_argument("--target", "-t", help="Target address")
    parser.add_argument("--tcp", type=int, default=0, help="TCP port")
    parser.add_argument("--count", type=int, default=4, help="Ping count")
    parser.add_argument("--traceroute", action="store_true", help="Trace route")
    parser.add_argument("--concurrent", type=int, default=4, help="Concurrent thread count")
    parser.add_argument("--timeout", type=int, help="Timeout in milliseconds")
    parser.add_argument("--json", action="store_true", dest="output_json", help="Output JSON format")
    args = parser.parse_args()

    # Get configuration
    config, sources = get_net_config(
        cli_target=args.target,
        cli_timeout_ms=args.timeout,
    )

    target = config["target"]
    timeout_ms = config["timeout_ms"]

    if not target:
        error = {
            "status": "error",
            "action": "ping",
            "error": {"code": "no_target", "message": "Target address not configured. Specify with --target or configure in .embeddedskills/config.json"},
        }
        print(json.dumps(error, ensure_ascii=False, indent=2))
        sys.exit(1)

    # Save confirmed configuration
    save_project_config(values={
        "target": target,
        "timeout_ms": timeout_ms,
    })

    # Support comma-separated multiple targets
    targets = [t.strip() for t in target.split(",") if t.strip()]

    results = []

    if args.traceroute:
        for t in targets:
            results.append(traceroute(t, timeout_ms))
    elif args.tcp > 0:
        with ThreadPoolExecutor(max_workers=args.concurrent) as pool:
            futures = {pool.submit(tcp_ping, t, args.tcp, timeout_ms): t for t in targets}
            for future in as_completed(futures):
                results.append(future.result())
    else:
        with ThreadPoolExecutor(max_workers=args.concurrent) as pool:
            futures = {pool.submit(icmp_ping, t, args.count, timeout_ms): t for t in targets}
            for future in as_completed(futures):
                results.append(future.result())

    reachable_count = sum(1 for r in results if r.get("reachable", False))
    total = len(results)
    action = "traceroute" if args.traceroute else ("tcp_ping" if args.tcp > 0 else "ping")

    output = {
        "status": "ok",
        "action": action,
        "summary": {
            "total": total,
            "reachable": reachable_count,
            "description": f"{reachable_count}/{total} targets reachable",
        },
        "details": {"results": results},
    }

    if args.output_json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(f"[net {action}] {output['summary']['description']}")
        for r in results:
            if args.traceroute:
                print(f"\n  Trace {r['target']}:")
                for h in r.get("hops", []):
                    print(f"    {h['hop']:>3}  {h['detail']}")
            else:
                icon = "+" if r.get("reachable") else "x"
                line = f"  [{icon}] {r['target']}"
                if r.get("port"):
                    line += f":{r['port']}"
                if r.get("avg_ms") is not None:
                    line += f"  latency={r['avg_ms']}ms"
                elif r.get("latency_ms") is not None:
                    line += f"  latency={r['latency_ms']}ms"
                if r.get("loss_rate"):
                    line += f"  loss={r['loss_rate']}"
                if r.get("error"):
                    line += f"  ({r['error']})"
                print(line)

    # Update state
    update_state_entry("last_net_ping", {
        "target": target,
        "reachable_count": reachable_count,
        "total": total,
    })


if __name__ == "__main__":
    main()
