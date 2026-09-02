---
name: jlink
description: >-
  J-Link programming and on-target debugging tool for device probing, firmware flashing,
  memory read/write, register inspection, target reset, RTT/SWO log capture,
  and on-target debugging (halt / go / step / run-to breakpoint / call stack / variable inspection).
  Triggers automatically when the user mentions J-Link, JLink, RTT, firmware flashing,
  memory write, memory read, register inspection, target reset, probe connectivity check,
  on-target debugging, single-step, breakpoint, or call stack, and supports explicit /jlink calls.
  Even if the user says "flash it", "check RTT output", or "debug target", trigger this skill
  whenever the context involves J-Link probes.
argument-hint: "[info|flash|read-mem|write-mem|regs|reset|halt|go|step|run-to|rtt|swo|gdb] ..."
---

# J-Link Flashing and On-Target Debugging

This skill provides device probing, firmware flashing, memory read/write, register inspection, target reset, RTT log capture, lightweight on-target debugging, and source-level GDB debugging for J-Link probes.

## Configuration

### Machine-Level Configuration (skill/config.json)

The `config.json` file in the skill directory contains machine-level configuration (tool paths, port numbers, etc.). Verify the `exe` path before first use:

```json
{
  "exe": "/opt/SEGGER/JLink/JLinkExe",
  "gdbserver_exe": "/opt/SEGGER/JLink/JLinkGDBServerCLExe",
  "rtt_exe": "/opt/SEGGER/JLink/JLinkRTTClient",
  "gdb_exe": "/usr/bin/arm-none-eabi-gdb",
  "serial_no": "",
  "rtt_telnet_port": 0,
  "swo_command": [],
  "operation_mode": 1
}
```

- `exe`: Full path to J-Link Commander (`JLinkExe` on Linux); when omitted, auto-probed via PATH and standard installation directories such as `/opt/SEGGER/JLink`
- `gdbserver_exe`: Path to J-Link GDB Server (`JLinkGDBServerCLExe` on Linux), required for RTT and GDB debugging
- `rtt_exe`: Path to J-Link RTT Client (`JLinkRTTClient` on Linux)
- `gdb_exe`: Path to arm-none-eabi-gdb, required for source-level GDB debugging
- `serial_no`: Default probe serial number, used in multi-probe environments
- `rtt_telnet_port`: RTT port, `0` to use tool default
- `swo_command`: Optional full command array for external SWO viewer, wrapped by `jlink_swo.py`
- `operation_mode`: `1` direct execution / `2` output risk summary without blocking / `3` require confirmation before execution

### Project-Level Configuration (.embeddedskills/config.json)

Device parameters (device/interface/speed) are managed centrally in the workspace's `.embeddedskills/config.json`:

```json
{
  "jlink": {
    "device": "STM32F407VG",
    "interface": "SWD",
    "speed": "4000"
  }
}
```

- `device`: Target chip model (e.g., STM32F407VG, GD32F470ZG)
- `interface`: Debug interface, SWD or JTAG, defaults to SWD
- `speed`: Debug speed in kHz, defaults to 4000

Parameter resolution priority: **Explicit CLI arguments > `.embeddedskills/config.json` (Project-level) > `skill/config.json` (Machine-level) > `.embeddedskills/state.json` > Defaults/Error**

After successful execution, confirmed device/interface/speed values are automatically written back to project configuration.

## Subcommands

### Basic Operations

| Subcommand | Purpose | Risk |
|---|---|---|
| `info` | Probe connectivity with target | Low |
| `flash` | Flash firmware (.hex / .bin / .elf) | High |
| `read-mem` | Read memory region | Low |
| `write-mem` | Write memory region | High |
| `regs` | Inspect CPU registers | Low |
| `reset` | Reset target chip | High |
| `rtt` | Read RTT log output | Low |
| `swo` | Wrap external SWO viewer into unified event stream | Low |

### On-Target Debugging (JLink Commander)

| Subcommand | Purpose | Risk |
|---|---|---|
| `halt` | Halt CPU and return register state | Low |
| `go` | Resume CPU execution | Low |
| `step` | Single-step execution (supports step count), returns executed instructions and registers | Low |
| `run-to` | Set breakpoint and run, wait for hit and return state | Low |

### GDB Source-Level Debugging

| Subcommand | Purpose | Dependency |
|---|---|---|
| `gdb backtrace/locals` | Inspect call stack and local variables | arm-none-eabi-gdb |
| `gdb break/continue/next/step/finish/until` | One-shot execution flow control | arm-none-eabi-gdb |
| `gdb frame/print/watch/disassemble/threads/crash-report` | One-shot source-level diagnostics | arm-none-eabi-gdb |

## Execution Flow

1. Read `skill/config.json` and verify `exe` path validity.
2. Read `.embeddedskills/config.json` to get project-level configuration (device/interface/speed).
3. Read `.embeddedskills/state.json` to get historical state.
4. Parameter resolution priority: **Explicit CLI arguments > `.embeddedskills/config.json` (Project-level) > `skill/config.json` (Machine-level) > `.embeddedskills/state.json` > Defaults/Error**
5. If the current action requires `device` and it remains empty, prompt the user directly; never guess.
6. When multiple probes are present and `serial_no` is not specified, list probes for the user to choose; do not auto-select.
7. Decide whether confirmation is required before execution based on `operation_mode`.
8. Generate temporary `.jlink` command file using templates, and call `JLinkExe` with `-NoGui 1 -ExitOnError 1 -AutoConnect 1`.
9. Parse output and return code to produce structured results.
10. After successful execution, write confirmed device/interface/speed back to `.embeddedskills/config.json`.

## Script Invocations

Four Python scripts are available in the skill directory, implemented using the standard library with no external dependencies.

### jlink_exec.py — Basic Operations + Lightweight Debugging

```bash
# Probe connectivity
python <skill-dir>/scripts/jlink_exec.py info --device GD32F470ZG --json

# Flash firmware
python <skill-dir>/scripts/jlink_exec.py flash --file build/app.hex --device GD32F470ZG --json

# Flash .bin (address is mandatory)
python <skill-dir>/scripts/jlink_exec.py flash --file build/app.bin --device GD32F470ZG --address 0x08000000 --json

# Read memory
python <skill-dir>/scripts/jlink_exec.py read-mem --address 0x08000000 --length 256 --device GD32F470ZG --json

# Write memory
python <skill-dir>/scripts/jlink_exec.py write-mem --address 0x20000000 --value 0x12345678 --device GD32F470ZG --json

# Inspect registers
python <skill-dir>/scripts/jlink_exec.py regs --device GD32F470ZG --json

# Reset target
python <skill-dir>/scripts/jlink_exec.py reset --device GD32F470ZG --json

# Halt CPU
python <skill-dir>/scripts/jlink_exec.py halt --device GD32F470ZG --json

# Resume execution
python <skill-dir>/scripts/jlink_exec.py go --device GD32F470ZG --json

# Single-step execution (3 steps)
python <skill-dir>/scripts/jlink_exec.py step --device GD32F470ZG --count 3 --json

# Run to breakpoint address
python <skill-dir>/scripts/jlink_exec.py run-to --device GD32F470ZG --address 0x08001234 --timeout-ms 3000 --json
```

Common optional arguments: `--interface SWD|JTAG`, `--speed 4000`, `--serial-no <serial>`, `--exe <JLinkExe path>`

### jlink_rtt.py — RTT Log Capture

```bash
python <skill-dir>/scripts/jlink_rtt.py --device GD32F470ZG --json
```

Optional arguments: `--serial-no`, `--channel`, `--encoding`, `--rtt-port`, `--gdbserver-exe <path>`, `--rtt-exe <path>`

How RTT works: The script establishes a debug connection via `JLinkGDBServerCLExe` first, then launches `JLinkRTTClient` to capture RTT data. `--json` mode outputs JSON Lines.

### jlink_swo.py — SWO Event Stream Wrapper

```bash
# Use swo_command from config.json
python <skill-dir>/scripts/jlink_swo.py --json

# Or pass viewer command explicitly
python <skill-dir>/scripts/jlink_swo.py \
  --viewer-cmd JLinkSWOViewerCLExe -device GD32F470ZG -itf SWD -speed 4000 \
  --json
```

`jlink_swo.py` does not implement the SWO protocol directly, but wraps stdout/stderr from an external viewer into unified JSON Lines for consumption by upstream workflows or AI.

### jlink_gdb.py — GDB Source-Level Debugging (requires arm-none-eabi-gdb)

```bash
# Execute custom GDB command sequence
python <skill-dir>/scripts/jlink_gdb.py run \
  --gdbserver-exe <path> --gdb-exe <arm-none-eabi-gdb path> \
  --device GD32F470ZG --elf build/app.elf \
  --commands "break main" "continue" "backtrace" "info locals" --json

# Shortcut: inspect call stack
python <skill-dir>/scripts/jlink_gdb.py backtrace \
  --gdbserver-exe <path> --gdb-exe <path> \
  --device GD32F470ZG --elf build/app.elf --json

# Shortcut: inspect local variables
python <skill-dir>/scripts/jlink_gdb.py locals \
  --gdbserver-exe <path> --gdb-exe <path> \
  --device GD32F470ZG --elf build/app.elf --json
```

GDB debugging requires an ELF file for source-level debugging (function name breakpoints, variable inspection). Address-level debugging is still supported without an ELF.

## Output Format

All scripts return JSON format with base fields `status` (ok/error), `action`, `summary`, and `details`, optionally accompanied by `context`, `artifacts`, `metrics`, `state`, `next_actions`, and `timing`. Streaming observation commands use JSON Lines and uniformly output `source`, `channel_type`, and `stream_type`.

Success example:
```json
{
  "status": "ok",
  "action": "halt",
  "summary": "Halted, PC=0x08049ABC",
  "details": {
    "device": "GD32F470ZG",
    "registers": { "PC": "0x08049ABC", "R0": "0x00000004", "..." : "..." }
  }
}
```

step example (including executed instructions):
```json
{
  "status": "ok",
  "action": "step",
  "summary": "Stepped 3 times, PC=0x08049AB4",
  "details": {
    "steps": [
      { "address": "0x08049AB8", "opcode": "80 1B", "instruction": "SUBS R0, R0, R6" },
      { "address": "0x08049ABA", "opcode": "A8 42", "instruction": "CMP R0, R5" },
      { "address": "0x08049ABC", "opcode": "FA D3", "instruction": "BCC #-0x0C" }
    ],
    "registers": { "PC": "0x08049AB4", "..." : "..." }
  }
}
```

run-to example (breakpoint hit):
```json
{
  "status": "ok",
  "action": "run-to",
  "summary": "Breakpoint hit @ 0x08049AB4, PC=0x08049AB4",
  "details": {
    "bp_address": "0x08049AB4",
    "bp_hit": true,
    "registers": { "PC": "0x08049AB4", "..." : "..." }
  }
}
```

## Core Rules

- Never guess target chip `device`; prompt the user when missing.
- Do not auto-select probes in multi-probe environments; prompt the user to specify serial number.
- Parameter resolution priority: **Explicit CLI arguments > `.embeddedskills/config.json` (Project-level) > `skill/config.json` (Machine-level) > `.embeddedskills/state.json` > Defaults/Error**
- Flashing `.bin` files requires an explicit address; raise an error when missing.
- Provide troubleshooting suggestions on connection failure (check wiring, power, interface type, speed); do not automatically attempt more aggressive parameters.
- Flashing, memory writing, and resetting execute directly when parameters are complete and user intent is clear.
- `run-to` breakpoints are set and cleared within a single JLink session, avoiding cross-session handle issues.
- Execution responses always include target chip, interface type, and action performed.
- Artifact paths (elf/file) are not stored in project configuration, relying only on `state.json`.
- Operational states such as `last_flash`/`last_debug` continue to be recorded in `state.json`.

## Typical Debugging Workflows

### Quick Inspection (JLink Commander)

```
halt → regs → read-mem → step → go
```
Suitable for inspecting current execution location, register states, and memory values without ELF or GDB.

### Breakpoint Debugging (JLink Commander)

```
run-to(address) → regs → read-mem → go
```
Set a breakpoint at a specific address, wait for hit, and inspect target state.

### Source-Level Debugging (GDB)

```
gdb run --elf app.elf --commands "break main" "continue" "backtrace" "info locals"
```
Requires an ELF file and arm-none-eabi-gdb; supports function name breakpoints and variable inspection.

## References

Refer to `references/common_devices.md` when encountering chip device name issues.
