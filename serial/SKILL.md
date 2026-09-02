---
name: serial
description: >-
  Embedded serial port debugging tool for scanning serial ports, real-time monitoring,
  sending data, logging, and hex dump viewing.
  Automatically triggered when the user mentions serial ports, COM ports, UART,
  AT command debugging, baud rates, hex streams, serial log capture, serial monitoring,
  viewing MCU output, or binary protocol debugging; also compatible with explicit
  /serial invocation. Even if the user only says "check serial output", "send an AT command",
  or "capture logs", this skill should be triggered whenever serial communication is involved in context.
argument-hint: "[scan|monitor|send|hex|log] ..."
---

# Serial — Embedded Serial Port Debugging Tool

Unified encapsulation for port discovery, real-time monitoring, data transmission, logging, and hex dump viewing capabilities.

## Configuration

### Environment-Level Configuration (`skill/config.json`)

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

| Field | Description | Default |
|-------|-------------|---------|
| `port` | Serial device, e.g. `/dev/ttyUSB0` | `""` |
| `baudrate` | Baud rate | `115200` |
| `bytesize` | Data bits | `8` |
| `parity` | Parity: none/even/odd/mark/space | `none` |
| `stopbits` | Stop bits: 1/1.5/2 | `1` |
| `encoding` | Text encoding | `utf-8` |
| `timeout_sec` | Read/write timeout (seconds) | `1.0` |
| `log_dir` | Log output directory | `.embeddedskills/logs/serial` |

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

## Subcommands

| Subcommand | Purpose | Risk |
|------------|---------|------|
| `scan` | Scan available serial ports | Low |
| `monitor` | Monitor text output in real-time | Low |
| `send` | Send text or hex data | Medium |
| `hex` | View binary stream in real-time | Low |
| `log` | Save serial log to file | Low |

## Execution Flow

1. Check if `pyserial` is available; prompt `pip install pyserial` if not installed.
2. Resolve parameters by priority: CLI > Project-level config > State file > Defaults.
3. Default to executing `scan` when no subcommand is specified.
4. `monitor / send / hex / log` use resolved connection parameters.
5. If `port` is not specified, auto-scan system serial ports:
   - Unique candidate: automatically use and write to project configuration.
   - Multiple candidates: return candidate list for user selection.
6. After successful execution, write confirmed parameters back to project configuration.
7. Run corresponding script and output structured results.
8. On failure, prioritize reporting port occupation, driver, baud rate, and encoding issues.

## Script Invocation

All scripts reside in `scripts/` under the skill directory and are executed directly via `python`.
Scripts read parameters by priority from CLI arguments, project configuration, and state file.

```bash
# Scan serial ports
python scripts/serial_scan.py [--filter <keyword>] [--json]

# Real-time monitoring
python scripts/serial_monitor.py [--port <port>] [--baudrate <baudrate>] [--timestamp] [--filter <regex>] [--timeout <sec>] [--json]

# Send data
python scripts/serial_send.py [--port <port>] [--baudrate <baudrate>] <data> [--hex] [--crlf] [--repeat <count>] [--wait-response] [--json]

# Hex dump view
python scripts/serial_hex.py [--port <port>] [--baudrate <baudrate>] [--width <cols>] [--timeout <sec>] [--json]

# Logging
python scripts/serial_log.py [--port <port>] [--baudrate <baudrate>] [--output <file>] [--duration <sec>] [--format text|csv|json] [--json]
```

## Output Format

Single commands return standard JSON:
```json
{
  "status": "ok",
  "action": "scan",
  "summary": "Found 2 serial port(s)",
  "details": { ... }
}
```

Continuous commands (`monitor --json`, `hex --json`) output JSON Lines, with end summary written to stderr.

Error output:
```json
{
  "status": "error",
  "action": "monitor",
  "error": { "code": "port_busy", "message": "Serial port is occupied by another process" }
}
```

## Serial Multiplexing (Mux)

When concurrent access to the same serial device is needed between minicom (or other serial tools) and skill scripts, multiplexing can be achieved via the background mux service.

### Prerequisites

- **socat** — `apt install socat` / `pacman -S socat`

### Architecture

```
                   ┌──────────────────┐
                   │   Real Hardware   │
                   │   /dev/ttyUSB0    │
                   └────────┬─────────┘
                            │
                   ┌────────▼─────────┐
                   │ Python mux server │
                   │ TCP-LISTEN:20001  │  Single reader + broadcast
                   └────────┬─────────┘
                            │
            ┌───────────────┼───────────────┐
            │               │               │
   ┌────────▼──────┐ ┌─────▼──────┐ ┌──────▼────────┐
   │  socat PTY    │ │ skill      │ │ skill         │
   │ /tmp/serial_  │ │ monitor    │ │ send/log/hex  │
   │ mux_vserial   │ │ socket://  │ │ socket://     │
   └───────┬───────┘ └────────────┘ └───────────────┘
           │
   ┌───────▼───────┐
   │   minicom     │
   │  (User side)  │
   └───────────────┘
```

- **Layer 1**: Python mux process exclusively opens the real serial port, exposes a TCP server, and broadcasts serial RX to all clients.
- **Layer 2**: socat acts as a TCP client to create a virtual PTY `/tmp/serial_mux_vserial` for minicom.
- **Skill Scripts**: Automatically detect mux status, connecting to TCP port via `socket://` only when current serial configuration matches the mux.
- **Data Flow**: Serial RX -> broadcast to all TCP clients; any client TX -> forwarded to real serial port.

### Mux Management Commands

```bash
# Start multiplexer
python scripts/serial_mux.py start --port /dev/ttyUSB0 [--baudrate 115200]

# Query status
python scripts/serial_mux.py status

# Stop multiplexer
python scripts/serial_mux.py stop
```

Once started, skill scripts (monitor/hex/log/send) automatically connect via multiplexing without extra arguments. If a command explicitly specifies a different port or parameters, it will not reuse the current mux.

### Workflow

1. `python scripts/serial_mux.py start --port /dev/ttyUSB0`
2. `minicom -D /tmp/serial_mux_vserial` (user side interactive terminal)
3. `python scripts/serial_monitor.py` (model side monitoring, automatically routes through mux)
4. Both terminals see serial data simultaneously.
5. `python scripts/serial_mux.py stop` stops multiplexing (terminates socat process and cleans up `/tmp/serial_mux_vserial` symlink).

### Write Conflict Warning

**Concurrent writes from multiple clients will corrupt serial data.** Monitor/hex/log scripts output a warning to stderr when connected via mux. The send script outputs a stronger conflict warning. To connect directly to the real serial port (skipping mux), use the `--direct` flag.

### Mux State Persistence

Mux process PIDs are saved in the `serial_mux` section of `.embeddedskills/state.json`. When subsequent commands run `status`, they check if the processes are still alive and clean up zombie PIDs automatically. After successful `start`, confirmed serial settings are written back to `.embeddedskills/config.json` for reuse by parameterless commands. The `stop` command terminates mux and socat PTY processes, and removes any leftover `/tmp/serial_mux_vserial` symlinks.

## Core Rules

- Do not guess baud rates automatically; do not arbitrarily select ports when multiple candidate serial ports are discovered.
- Parameter resolution priority: CLI > Project-level config > State file > Defaults.
- Auto-scan when `port` is not specified: single candidate is auto-saved to config; multiple candidates require user selection.
- Write confirmed parameters back to `.embeddedskills/config.json` upon successful execution.
- Do not actively send any serial data without clear indication of purpose.
- Continuous streaming output under `--json` must use JSON Lines; summaries are written to stderr to avoid polluting the data stream.
- Regex filter failures should not cause monitoring to exit.
- While Mux is running, remind user to avoid concurrent writes before sending data.

## References

- `references/common_devices.json`: Common USB-to-serial chip VID/PID mapping.
