---
name: can
description: >-
  Embedded CAN / CAN-FD debugging tool for scanning interfaces, monitoring messages,
  transmitting test frames, logging traffic, decoding database files, and bus statistics.
  Triggered when user mentions CAN, CAN-FD, DBC decoding, bus packet capture, USB-CAN debugging,
  message transmission, bus statistics, PCAN, Vector, slcan, CAN interface scanning,
  CAN ID filtering, ASC logs, or BLF files, and compatible with explicit /can invocation.
argument-hint: "[scan|monitor|send|log|decode|stats] ..."
---

# CAN — Embedded CAN / CAN-FD Debugging Tool

Provides unified interface discovery, real-time monitoring, message transmission, logging, database decoding, and statistical analysis capabilities.

## Configuration

### Environment-Level Configuration (`skill/config.json`)

Retains only slcan-related environment-level configuration:

```json
{
  "slcan_serial_port": "",
  "slcan_serial_baudrate": 115200
}
```

| Field | Description | Default |
|-------|-------------|---------|
| `slcan_serial_port` | Serial port for slcan | `""` |
| `slcan_serial_baudrate` | Serial baudrate for slcan | `115200` |

### Project-Level Configuration (`.embeddedskills/config.json`)

Project-level CAN configuration located in `.embeddedskills/config.json` under workspace:

```json
{
  "can": {
    "interface": "",
    "channel": "",
    "bitrate": 500000,
    "data_bitrate": 2000000,
    "log_dir": ".embeddedskills/logs/can"
  }
}
```

| Field | Description | Default |
|-------|-------------|---------|
| `interface` | CAN backend, e.g. `pcan` / `vector` / `slcan` | `""` |
| `channel` | Channel name, e.g. `PCAN_USBBUS1` | `""` |
| `bitrate` | Arbitration phase bitrate | `500000` |
| `data_bitrate` | CAN-FD data phase bitrate | `2000000` |
| `log_dir` | Log output directory | `.embeddedskills/logs/can` |

### Parameter Resolution Priority

1. **CLI Arguments** (`--interface`, `--channel`, `--bitrate`, etc.) - Highest priority
2. **Project-Level Configuration** (`can` section in `.embeddedskills/config.json`)
3. **State File** (History records in `.embeddedskills/state.json`)
4. **Default Values** - Lowest priority

### Auto-Scan Behavior

When `interface` and `channel` are not specified, the scripts automatically scan system CAN interfaces and proceed as follows:

1. Scan all available CAN interfaces on the system
2. If only one interface is found → Automatically use it and save to project configuration
3. If multiple interfaces are found → Return candidate list and prompt user to choose
4. If no interfaces are found → Report error and abort execution

## Subcommands

| Subcommand | Description | Risk |
|------------|-------------|------|
| `scan` | Scan available CAN interfaces and USB-CAN devices | Low |
| `monitor` | Real-time bus message monitoring | Low |
| `send` | Transmit standard / extended / remote / CAN-FD frames | High |
| `log` | Log bus messages to ASC / BLF / CSV files | Low |
| `decode` | Decode messages or logs using database files (e.g. DBC) | Low |
| `stats` | Analyze bus load, ID distribution, and frame rates | Low |

## Execution Flow

1. Verify `python-can` is available; if not installed, prompt to run `pip install python-can`
2. Resolve parameters according to priority: CLI > Project-level configuration > State file > Defaults
3. Default to `scan` when no subcommand is specified
4. `monitor / send / log / stats` use resolved connection parameters
5. `decode` first verifies existence of database file and input source
6. If `interface`/`channel` is not specified, auto-scan system CAN interfaces:
   - Single candidate: Automatically use it and write to project configuration
   - Multiple candidates: Return list for user selection
7. After successful execution, write confirmed parameters back to project configuration
8. `send` executes directly once connection configuration is valid, without secondary confirmation
9. Execute corresponding script and output structured results
10. On failure, prioritize reporting issues regarding interface, driver, bitrate, or filter conditions

## Script Invocation

All scripts reside under `scripts/` in the skill directory and are invoked directly via `python`.
Scripts read parameters based on priority from CLI arguments, project-level configuration, and state file.

```bash
# Scan interfaces
python scripts/can_scan.py [--json]

# Real-time monitoring
python scripts/can_monitor.py [--interface <interface>] [--channel <channel>] [--bitrate <bitrate>] [--fd] [--filter-id <id_list>] [--exclude-id <id_list>] [--dbc <dbc_file>] [--timeout <sec>] [--json]

# Message transmission
python scripts/can_send.py [--interface <interface>] [--channel <channel>] [--bitrate <bitrate>] <id> <data> [--extended] [--remote] [--fd] [--repeat <count>] [--interval <sec>] [--periodic <ms>] [--listen] [--json]

# Data logging
python scripts/can_log.py [--interface <interface>] [--channel <channel>] [--bitrate <bitrate>] [--output <file>] [--duration <sec>] [--max-count <count>] [--filter-id <id_list>] [--console] [--json]

# Database decoding
python scripts/can_decode.py <db_file> [--db-format <auto|dbc|arxml|kcd|sym|cdd>] [--id <can_id>] [--data <hex_data>] [--log <log_file>] [--signal <signal_name>] [--list] [--json]

# Bus statistics
python scripts/can_stats.py [--interface <interface>] [--channel <channel>] [--bitrate <bitrate>] [--duration <sec>] [--top <count>] [--watch <id_list>] [--json]
```

## Output Format

Single command returns standard JSON:
```json
{
  "status": "ok",
  "action": "scan",
  "summary": "Found 2 CAN interface(s)",
  "details": { ... }
}
```

Streaming commands (`monitor --json`, `send --listen --json`) output JSON Lines, with final summary written to stderr.

Error output:
```json
{
  "status": "error",
  "action": "send",
  "error": { "code": "interface_open_failed", "message": "Unable to open specified CAN interface" }
}
```

## Core Rules

- Do not automatically guess interface, channel, or bitrate; do not arbitrarily select when multiple interfaces exist
- Parameter resolution priority: CLI > Project-level configuration > State file > Default values; auto-scan results apply only when no CLI parameters are provided
- When `interface`/`channel` is unspecified, perform auto-scan: a single candidate is automatically written to configuration, while multiple candidates require user selection
- After successful execution, confirmed parameters are automatically written back to `.embeddedskills/config.json`
- Do not proactively send any messages without explicit intent
- Continuous streaming with `--json` uses JSON Lines; summaries go to stderr to prevent polluting the data stream
- DBC decoding errors should not disrupt message monitoring
- If a frame definition is not found, return an explicit error rather than silently ignoring it

## References

- `references/common_interfaces.json`: Common USB-CAN device definitions
