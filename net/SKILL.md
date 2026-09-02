---
name: net
description: >-
  Embedded network debugging skill for interface discovery, packet capture, pcap/pcapng analysis,
  connectivity testing, port scanning, and traffic statistics. Automatically triggers when the user
  mentions Wireshark, tshark, libpcap, packet capture, network debugging, port scanning, connectivity
  troubleshooting, pcap analysis, network interfaces, ping tests, traceroute, traffic statistics,
  Modbus TCP, EtherNet/IP, or other network protocol debugging, and is compatible with explicit /net
  calls. Even if the user casually asks to "capture some packets", "scan ports", "check network reachability",
  or "analyze this pcap", this skill should be triggered whenever specific tool names (tshark, Wireshark,
  libpcap), protocol names (Modbus TCP, EtherNet/IP, ICMP, etc.), debugging actions (packet capture,
  port scanning, connectivity test, ping, traceroute, traffic statistics, pcap analysis), or network
  interface operations appear in the context.
argument-hint: "[iface|capture|analyze|ping|scan|stats] ..."
---

# Net Debug Skill

Embedded network communication debugging tool, unifying interface discovery, packet capture, offline analysis, connectivity testing, port scanning, and traffic statistics.

## Script and Configuration Paths

- Scripts directory: `<skill-dir>/scripts/`
- Environment-level configuration: `<skill-dir>/config.json` (tool paths only)
- Project-level configuration: `<workspace>/.embeddedskills/config.json` (network parameters)
- Protocol reference: `<skill-dir>/references/common_protocols.json`

## Dependencies

- `tshark` (installed with Wireshark, must be in PATH)
- `dumpcap` (installed with Wireshark)
- Optional: `capinfos`
- System built-in utilities: `ip`, `ping`, `traceroute`, `ss`, `arp`, `nslookup` (some Linux distributions require installing `iproute2`, `traceroute`, `dnsutils`)
- Python 3.x (standard library only)
- Packet capture requires libpcap; non-root users are recommended to run `sudo dpkg-reconfigure wireshark-common` and join the `wireshark` group, or grant `cap_net_raw,cap_net_admin` capabilities to `dumpcap`

## Configuration

### Environment-Level Configuration (`skill/config.json`)

Only environment-level configurations related to tool paths are retained:

```json
{
  "tshark_exe": "tshark",
  "capinfos_exe": "capinfos"
}
```

### Project-Level Configuration (`.embeddedskills/config.json`)

`.embeddedskills/config.json` under the workspace stores project-level network configuration:

```json
{
  "net": {
    "interface": "",
    "target": "",
    "capture_filter": "",
    "display_filter": "",
    "duration": 30,
    "timeout_ms": 1000,
    "scan_ports": "",
    "capture_format": "pcapng",
    "log_dir": ".embeddedskills/logs/net"
  }
}
```

### Parameter Resolution Priority

1. **CLI arguments** (`--interface`, `--target`, etc.) - highest priority
2. **Project-level configuration** (`net` section in `.embeddedskills/config.json`)
3. **State file** (history in `.embeddedskills/state.json`)
4. **Default values** - lowest priority

Connection and capture parameters are resolved by priority, and scripts receive overrides via CLI arguments. If configuration lacks required items or connection fails, prompt the user and guide them to modify the configuration.

## Execution Flow

1. Check whether `tshark` is available; if unavailable, prompt user to install Wireshark (including tshark) and verify it is added to PATH. If packet capture is requested, also prompt user to install libpcap and verify current user has packet capture permissions. Terminate execution and output `status: error` with installation guidance when dependencies are missing.
2. Resolve parameters by priority: CLI > project configuration > state file > default values. If multiple sources provide values for the same parameter, the higher priority source prevails, and overridden sources are noted in the summary.
3. If no subcommand is specified, default to `iface` (list network interfaces).
4. After successful execution, write confirmed parameters back to project configuration.
5. Run the corresponding script and output structured JSON results.
6. On failure, prioritize diagnosing permissions (`wireshark` group / `cap_net_raw`), libpcap, filters, interface selection, etc.

## Subcommands

### iface — List Network Interfaces

```bash
python <skill-dir>/scripts/net_iface.py [--filter <keyword>] [--tshark] [--json]
```

- `--tshark`: Also display tshark capture interface index mappings
- `--filter`: Filter interfaces by keyword
- No side effects, can be executed directly

### capture — Packet Capture

```bash
python <skill-dir>/scripts/net_capture.py [--interface <interface>] [--duration <seconds>] [--capture-filter <filter>] [--display-filter <filter>] [--output <filepath>] [--format <pcapng|pcap>] [--decode-as <rule>] [--json]
```

- Interface, filters, and duration are resolved by priority
- `--interface`: Capture interface (overrides config)
- `--duration`: Capture duration (overrides config)
- `--capture-filter`: BPF capture filter (overrides config)
- `--display-filter`: Wireshark display filter (overrides config)
- `--output`: Path to save capture file
- `--json`: Output JSON Lines format (based on tshark -T ek)
- `--decode-as`: Custom decode rule
- Default format is pcapng; execute directly once parameters are complete

### analyze — Analyze pcap File

```bash
python <skill-dir>/scripts/net_analyze.py <pcap_file> [--mode <summary|protocols|conversations|endpoints|io|anomalies|all>] [--filter <display_filter>] [--top <count>] [--decode-as <rule>] [--export-fields <field_list>] [--output <csv_path>] [--json]
```

- Perform offline analysis based on tshark and capinfos
- `--mode all` outputs all analysis dimensions
- No side effects, can be executed directly

### ping — Connectivity Testing

```bash
python <skill-dir>/scripts/net_ping.py [--target <target>] [--tcp <port>] [--count <count>] [--traceroute] [--concurrent <threads>] [--timeout <ms>] [--json]
```

- Target is resolved by priority
- `--target`: Target address (overrides config)
- `--tcp`: TCP connectivity test (specifying port)
- `--traceroute`: Run route tracing
- `--timeout`: Timeout in milliseconds (overrides config)
- Execute directly once parameters are complete

### scan — Port Scanning

```bash
python <skill-dir>/scripts/net_scan.py [--target <target>] [--ports <port_range>] [--timeout <ms>] [--banner] [--concurrent <threads>] [--json]
```

- Target and port range are resolved by priority
- `--target`: Target address (overrides config)
- `--ports`: Port range, e.g. '80,443,8000-8100' (overrides config)
- `--banner`: Attempt to grab service banner
- Defaults to common embedded ports set
- Execute directly once parameters are complete

### stats — Traffic Statistics

```bash
python <skill-dir>/scripts/net_stats.py [--interface <interface>] [--duration <seconds>] [--display-filter <filter>] [--interval <seconds>] [--mode <overview|protocol|endpoint|port>] [--json]
```

- Interface and duration are resolved by priority
- `--interface`: Capture interface (overrides config)
- `--duration`: Statistics duration (overrides config)
- `--display-filter`: Wireshark display filter (overrides config)
- Defaults to outputting time-interval aggregated JSON
- No side effects, can be executed directly

## Output Format

All scripts output a unified JSON structure:

```json
{
  "status": "ok",
  "action": "<subcommand_name>",
  "summary": "<brief_description>",
  "details": { ... }
}
```

On error:

```json
{
  "status": "error",
  "action": "<subcommand_name>",
  "error": {
    "code": "<error_code>",
    "message": "<error_description>"
  }
}
```

`capture --json` outputs JSON Lines, with progress information written to stderr.

## Interaction Strategy

- Resolve parameters by priority: CLI > project configuration > state file > default values
- Prefer executing directly with resolved parameters without asking unnecessary questions
- Ask the user and guide configuration changes only when connection fails
- Automatically write confirmed parameters back to `.embeddedskills/config.json` after successful execution
- Default to a single host and small port range when no scan range is provided
- Explicitly echo target range, filters, and duration in results
- Prioritize summarizing abnormal protocols, retransmissions, RSTs, etc. in capture results
- Prioritize diagnosing permissions (`wireshark` group / `cap_net_raw`) and libpcap issues upon capture failure

## Protocol Reference

When querying common embedded ports and protocol mappings, refer to `references/common_protocols.json`.
