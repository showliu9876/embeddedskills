# serial

Claude Code skill for embedded serial port debugging: port scanning, real-time monitoring, data transmission, hex dump viewing, and logging.

## Features

- Scan available system serial ports
- Real-time monitoring of serial text output (supports regex filtering, timestamps)
- Send text or hex data (supports AT command debugging)
- Binary stream hex dump viewing
- Serial log capture (text / csv / json formats)

## Requirements

- Python 3.x
- [pyserial](https://pypi.org/project/pyserial/) — `pip install pyserial`
- [socat](http://www.dest-unreach.org/socat/) — `apt install socat` / `pacman -S socat` (required for multiplexing feature)
- USB-to-serial chip drivers (CH340, CP2102, FT232, etc., install corresponding drivers according to hardware)

## Configuration

### Environment-Level Configuration (`config.json`)

The environment-level configuration of the serial skill is currently an empty object `{}`, as serial port parameters are project-level configurations managed in the workspace's `.embeddedskills/config.json`.

### Project-Level Configuration (`.embeddedskills/config.json`)

The `.embeddedskills/config.json` file in the workspace stores project-level serial configuration:

```json
{
  "serial": {
    "port": "",
    "baudrate": 115200,
    "bytesize": 8,
    "parity": "none",
    "stopbits": 1,
    "encoding": "utf-8",
    "timeout_sec": 1.0,
    "log_dir": ".embeddedskills/logs/serial"
  }
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `port` | No | Serial port device (e.g. `/dev/ttyUSB0`, `/dev/ttyACM0`), automatically scans when empty |
| `baudrate` | No | Baud rate, default `115200` |
| `bytesize` | No | Data bits, default `8` |
| `parity` | No | Parity: `none` / `even` / `odd` / `mark` / `space` |
| `stopbits` | No | Stop bits: `1` / `1.5` / `2` |
| `encoding` | No | Text encoding, default `utf-8` |
| `timeout_sec` | No | Read/write timeout in seconds, default `1.0` |
| `log_dir` | No | Log output directory, default `.embeddedskills/logs/serial` |

### Parameter Resolution Priority

1. **CLI arguments** (`--port`, `--baudrate`, etc.) - Highest priority
2. **Project-level configuration** (`serial` section in `.embeddedskills/config.json`)
3. **State file** (History records in `.embeddedskills/state.json`)
4. **Defaults** - Lowest priority

### Auto-Scan Behavior

When `port` is not specified, scripts automatically scan system serial ports:
- If only one serial port is found, automatically use that port and write to project configuration.
- If multiple serial ports are found, return a candidate list for user selection (specified via `--port`).
- If no serial ports are found, display an error message.
