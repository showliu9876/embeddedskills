# can

Claude Code skill for embedded CAN / CAN-FD bus debugging: interface scanning, real-time monitoring, message transmission, logging, DBC decoding, and bus statistics.

## Features

- Scan system available CAN interfaces and USB-CAN devices
- Real-time bus message monitoring (supports ID filtering, DBC decoding, CAN-FD)
- Transmit standard / extended / remote / CAN-FD frames (supports periodic transmission and listening)
- Log bus messages to ASC / BLF / CSV files
- Decode messages or logs using database files such as DBC / ARXML / KCD
- Analyze bus load, ID distribution, and frame rates

## Requirements

- Python 3.x
- [python-can](https://python-can.readthedocs.io/) — `pip install python-can`
- [cantools](https://cantools.readthedocs.io/) — `pip install cantools`
- [pyserial](https://pypi.org/project/pyserial/) — `pip install pyserial` (required only for slcan scenarios)
- USB-CAN device drivers (PEAK, Vector, Kvaser, etc., install corresponding driver per hardware)

## Configuration

### Environment-Level Configuration (`config.json`)

Retains only slcan-related environment-level configuration:

```json
{
  "slcan_serial_port": "",
  "slcan_serial_baudrate": 115200
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `slcan_serial_port` | No | Serial port for slcan |
| `slcan_serial_baudrate` | No | Serial baudrate for slcan, default: 115200 |

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

| Field | Required | Description |
|-------|----------|-------------|
| `interface` | No | CAN backend, e.g. `pcan` / `vector` / `slcan`; auto-scanned when empty |
| `channel` | No | Channel name, e.g. `PCAN_USBBUS1` |
| `bitrate` | No | Arbitration phase bitrate, default: 500000 |
| `data_bitrate` | No | CAN-FD data phase bitrate, default: 2000000 |
| `log_dir` | No | Log output directory, default: `.embeddedskills/logs/can` |

### Parameter Resolution Priority

1. **CLI Arguments** (`--interface`, `--channel`, `--bitrate`, etc.) - Highest priority
2. **Project-Level Configuration** (`can` section in `.embeddedskills/config.json`)
3. **State File** (History records in `.embeddedskills/state.json`)
4. **Default Values** - Lowest priority

### Auto-Scan Behavior

When `interface` and `channel` are not specified, the scripts automatically scan system CAN interfaces:
- If only one interface is found, automatically use it and write to project configuration
- If multiple interfaces are found, return candidate list for user selection
- If no interfaces are found, report error

> The database file for the `decode` subcommand is passed explicitly via positional argument and is not read from configuration.

## Subcommands

| Subcommand | Description | Example |
|------------|-------------|---------|
| `scan` | Scan available CAN interfaces (default subcommand) | `/can scan` |
| `monitor` | Real-time bus message monitoring | `/can monitor --timeout 10` |
| `send` | Transmit test frames | `/can send 0x123 "DE AD BE EF"` |
| `log` | Record bus logs | `/can log --output trace.asc` |
| `decode` | Decode messages or logs using database files | `/can decode vehicle.dbc --log trace.asc` |
| `stats` | Analyze bus load and ID distribution | `/can stats --duration 10` |

## Directory Structure

```
can/
├── README.md
├── SKILL.md
├── config.json
├── config.example.json
├── scripts/
│   ├── can_scan.py
│   ├── can_monitor.py
│   ├── can_send.py
│   ├── can_log.py
│   ├── can_decode.py
│   └── can_stats.py
└── references/
    └── common_interfaces.json
```

## Supported Interfaces

| Interface | Platform | Notes |
|-----------|----------|-------|
| `socketcan` | Linux | Native kernel support, recommended for primary use |
| `slcan` | Linux | Serial to CAN, requires pyserial |
| `kvaser` | Linux | Requires Kvaser Linux driver and CANlib |
| `pcan` | Linux | Requires kernel `peak_usb` driver; can also connect directly via `socketcan` |
| `ixxat` | Linux | Requires IXXAT ECI Linux driver |
| `vector` | Windows only | Only provides Windows XL Driver Library, unavailable on Linux |
| `gs_usb` | Linux | gs_usb firmware devices such as candleLight / CANable |
| `virtual` | Cross-platform | Virtual bus, for testing |

