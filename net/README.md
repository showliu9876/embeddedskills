# net

Claude Code skill for embedded network communication debugging: interface discovery, packet capture, pcap analysis, connectivity testing, port scanning, and traffic statistics.

## Features

- List network interfaces and map them to tshark interfaces
- Real-time packet capture with pcapng/pcap format output
- Offline pcap file analysis (protocol hierarchy, conversations, endpoints, IO stats, anomaly detection)
- Ping / TCP connectivity testing / route tracing
- Port scanning (including banner grabbing)
- Real-time traffic statistics

## Requirements

- [Wireshark](https://www.wireshark.org/) CLI tools — provides tshark, dumpcap, capinfos (`sudo apt install tshark wireshark-common`)
- libpcap — automatically installed via Wireshark/tshark dependencies
- Python 3.x (standard library only, no external dependencies)
- Non-root users capturing packets must be added to the `wireshark` group (`sudo dpkg-reconfigure wireshark-common` followed by `sudo usermod -aG wireshark $USER`, effective after re-login), or set `cap_net_raw,cap_net_admin` capabilities on `dumpcap`

## Configuration

### Environment-Level Configuration (`config.json`)

Only environment-level configurations related to tool paths are retained:

```json
{
  "tshark_exe": "tshark",
  "capinfos_exe": "capinfos"
}
```

| Field | Required | Description |
|---|---|---|
| `tshark_exe` | Yes | Path or command name for tshark |
| `capinfos_exe` | No | Path or command name for capinfos |

### Project-Level Configuration (`.embeddedskills/config.json`)

`.embeddedskills/config.json` in the workspace stores project-level network configuration:

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

| Field | Required | Description |
|---|---|---|
| `interface` | No | Default capture interface (use `iface` subcommand to view available interfaces) |
| `target` | No | Default target IP, comma-separated for multiple |
| `capture_filter` | No | Default capture filter (BPF syntax) |
| `display_filter` | No | Default display filter (Wireshark syntax) |
| `duration` | No | Default capture/statistics duration (seconds), default 30 |
| `timeout_ms` | No | Ping/scan timeout in milliseconds, default 1000 |
| `scan_ports` | No | Default port scanning range; defaults to common embedded ports set when empty |
| `capture_format` | No | Packet capture format: `pcapng` or `pcap`, default `pcapng` |
| `log_dir` | No | Log output directory, default `.embeddedskills/logs/net` |

### Parameter Resolution Priority

1. **CLI arguments** (`--interface`, `--target`, etc.) - highest priority
2. **Project-level configuration** (`net` section in `.embeddedskills/config.json`)
3. **State file** (history in `.embeddedskills/state.json`)
4. **Default values** - lowest priority

### Configuration Write-back

Upon successful execution, confirmed parameters are automatically written back to `.embeddedskills/config.json` for subsequent usage.
