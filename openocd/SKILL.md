---
name: openocd
description: >-
  OpenOCD flashing and debugging tool for probe detection, firmware flashing, flash erasing, GDB Server launch, target reset control,
  Telnet online debugging (halt/resume/step/registers/memory/breakpoints), GDB source-level debugging, as well as Semihosting/ITM output capture and low-level queries.
  Triggered automatically when the user mentions OpenOCD, ST-Link, CMSIS-DAP, DAPLink, FTDI, flashing firmware, erasing flash, GDB Server,
  reset, interface/target/board configurations, openocd.cfg, online debugging, single-stepping, breakpoints, inspecting registers,
  reading/writing memory, or semihosting, and also compatible with explicit /openocd invocation.
  Even if the user simply says "flash it", "start GDB Server", "erase chip", "check registers", "single-step debug",
  or "capture semihosting", as long as the context involves open-source debug probes supported by OpenOCD, this skill should be triggered.
argument-hint: "[probe|flash|erase|reset|reset-init|targets|flash-banks|adapter-info|raw|gdb-server|gdb|halt|resume|step|reg|read-mem|write-mem|bp|rbp|run-to|semihosting|itm] ..."
---

# OpenOCD Flashing and Debugging

This skill provides OpenOCD capabilities for probe detection, firmware flashing, flash erasing, GDB Server launch, target reset,
Telnet online debugging, GDB source-level debugging, and Semihosting output capture.

## Configuration

### Environment-Level Configuration (skill/config.json)

`config.json` under the skill directory contains environment-level configuration (tool paths, port numbers, etc.). Verify that the `exe` path is correct before first use:

```json
{
  "exe": "openocd",
  "scripts_dir": "",
  "gdb_port": 3333,
  "telnet_port": 4444,
  "gdb_exe": "",
  "operation_mode": 1
}
```

- `exe`: `openocd` path or command name; automatically detected from PATH when empty
- `scripts_dir`: OpenOCD configuration script directory; when empty, detects in order `/usr/share/openocd/scripts`, `/usr/local/share/openocd/scripts`, `/usr/share/openocd`, and falls back to OpenOCD built-in path if none exist
- `gdb_port`: GDB Server port, default 3333
- `telnet_port`: Telnet port, default 4444
- `gdb_exe`: arm-none-eabi-gdb path, required for GDB debugging subcommands (run/backtrace/locals)
- `operation_mode`: `1` direct execution / `2` output risk summary without blocking / `3` confirm before execution

### Project-Level Configuration (.embeddedskills/config.json)

Project parameters such as board/interface/target are centrally managed in `.embeddedskills/config.json` within the workspace:

```json
{
  "openocd": {
    "board": "",
    "interface": "interface/stlink.cfg",
    "target": "target/stm32f4x.cfg",
    "adapter_speed": "4000",
    "transport": "swd",
    "tpiu_name": "stm32f4x.tpiu",
    "traceclk": "168000000",
    "pin_freq": "2000000"
  }
}
```

- `board`: board configuration (e.g. `board/stm32f4discovery.cfg`), higher priority than interface+target
- `interface`: interface configuration (e.g. `interface/stlink.cfg`)
- `target`: target configuration (e.g. `target/stm32f4x.cfg`)
- `adapter_speed`: adapter speed in kHz
- `transport`: transport protocol (swd/jtag)
- `tpiu_name` / `traceclk` / `pin_freq`: TPIU parameters required for ITM/SWO observation

Parameter resolution priority: **CLI explicit arguments > `.embeddedskills/config.json` (project-level) > `skill/config.json` (environment-level) > `.embeddedskills/state.json` > defaults / error**

Upon successful execution, confirmed parameters are automatically written back to the project configuration.

## Subcommands

### Basic Operations

| Subcommand | Description | Risk |
|------------|-------------|------|
| `probe` | Verify board or interface+target combination and test target connectivity | Low |
| `flash` | Flash firmware (.elf / .hex / .bin) | High |
| `erase` | Erase target flash | High |
| `reset` / `reset-init` | Reset target chip | High |
| `targets` / `flash-banks` / `adapter-info` | Query low-level target / flash / adapter information | Low |
| `raw` | Execute controlled native OpenOCD commands | High |

### GDB Server

| Subcommand | Description | Risk |
|------------|-------------|------|
| `gdb-server` | Start GDB Server and keep running waiting for GDB connection | Low |
| `gdb backtrace/locals` | Quickly retrieve call stack and local variables | Low |
| `gdb break/continue/next/step/finish/until` | One-shot execution flow control | Low |
| `gdb frame/print/watch/disassemble/threads/crash-report` | One-shot source-level diagnostics | Low |

### Telnet Online Debugging

| Subcommand | Description | Risk |
|------------|-------------|------|
| `halt` | Halt CPU, return PC/xPSR | Low |
| `resume` | Resume CPU execution | Low |
| `step` | Single-step execution (supports `--count N`) | Low |
| `reg` | View all CPU registers | Low |
| `read-mem` | Read memory (`--width 8/16/32`, `--length N`) | Low |
| `write-mem` | Write memory (`--width 8/16/32`) | High |
| `bp` | Set hardware breakpoint | Low |
| `rbp` | Remove breakpoint | Low |
| `run-to` | Run to specified address (set breakpoint + resume + wait for hit) | Low |

### Semihosting

| Subcommand | Description | Risk |
|------------|-------------|------|
| `semihosting` | Enable ARM Semihosting and capture target printf output | Low |
| `itm` | Read SWO/ITM observation data based on TPIU/ITM | Low |

## Execution Flow

1. Read `skill/config.json`, verify that `exe` path is valid.
2. Read `.embeddedskills/config.json` to get project-level configuration (board/interface/target, etc.).
3. Read `.embeddedskills/state.json` to get historical state.
4. Parameter resolution priority: **CLI explicit arguments > `.embeddedskills/config.json` (project-level) > `skill/config.json` (environment-level) > `.embeddedskills/state.json` > defaults / error**.
5. When `board` is known, prefer `-f board/*.cfg`; otherwise combine `-f interface/*.cfg -f target/*.cfg`.
6. When `board`, `interface`, and `target` are all missing, do not automatically guess combinations; prompt the user to provide them directly.
7. Determine whether confirmation is needed before execution according to `operation_mode`.
8. Invoke the corresponding script based on the subcommand.
9. Uniformly parse `Info`, `Error`, and readiness messages from the output, returning structured results.
10. Upon successful execution, write confirmed parameters back to `.embeddedskills/config.json`.

## Script Invocations

There are five Python scripts under the skill directory, implemented using the standard library with no external dependencies.

### openocd_run.py — Probe / Flash / Erase / Reset

```bash
# Probe connectivity (using board)
python <skill-dir>/scripts/openocd_run.py probe --board board/stm32f4discovery.cfg --json

# Probe connectivity (using interface + target)
python <skill-dir>/scripts/openocd_run.py probe --interface interface/stlink.cfg --target target/stm32f4x.cfg --json

# Flash ELF firmware
python <skill-dir>/scripts/openocd_run.py flash --file build/app.elf --interface interface/stlink.cfg --target target/stm32f4x.cfg --json

# Flash BIN firmware (address must be provided)
python <skill-dir>/scripts/openocd_run.py flash --file build/app.bin --address 0x08000000 --interface interface/stlink.cfg --target target/stm32f4x.cfg --json

# Erase Flash (automatically chooses mass/sector)
python <skill-dir>/scripts/openocd_run.py erase --mode auto --interface interface/stlink.cfg --target target/stm32f4x.cfg --json

# Reset target
python <skill-dir>/scripts/openocd_run.py reset --mode halt --interface interface/stlink.cfg --target target/stm32f4x.cfg --json

# Query target list
python <skill-dir>/scripts/openocd_run.py targets --interface interface/stlink.cfg --target target/stm32f4x.cfg --json

# Query flash banks
python <skill-dir>/scripts/openocd_run.py flash-banks --interface interface/stlink.cfg --target target/stm32f4x.cfg --json

# Execute controlled raw commands
python <skill-dir>/scripts/openocd_run.py raw --interface interface/stlink.cfg --target target/stm32f4x.cfg --command "init" "targets" --json
```

Common optional arguments: `--board <cfg>`, `--search <dir>`, `--adapter-speed <kHz>`, `--transport <swd|jtag>`, `--exe <openocd_path>`

### openocd_gdb.py — GDB Server Launch and Debugging

```bash
# Start GDB Server (keep running)
python <skill-dir>/scripts/openocd_gdb.py server --interface interface/stlink.cfg --target target/stm32f4x.cfg --json

# Default to server when no subcommand is provided (backwards compatibility)
python <skill-dir>/scripts/openocd_gdb.py --interface interface/stlink.cfg --target target/stm32f4x.cfg --json

# Execute custom GDB command sequence
python <skill-dir>/scripts/openocd_gdb.py run --gdb-exe arm-none-eabi-gdb --elf build/app.elf --interface interface/stlink.cfg --target target/stm32f4x.cfg --commands "break main" "continue" "backtrace" "info locals" --json

# Quick call stack inspection
python <skill-dir>/scripts/openocd_gdb.py backtrace --gdb-exe arm-none-eabi-gdb --elf build/app.elf --interface interface/stlink.cfg --target target/stm32f4x.cfg --json

# Quick local variables inspection
python <skill-dir>/scripts/openocd_gdb.py locals --gdb-exe arm-none-eabi-gdb --elf build/app.elf --interface interface/stlink.cfg --target target/stm32f4x.cfg --json
```

Optional arguments: `--gdb-port`, `--telnet-port`, `--search`, `--adapter-speed`, `--transport`, `--board`

### openocd_telnet.py — Telnet Online Debugging

```bash
# Halt CPU
python <skill-dir>/scripts/openocd_telnet.py halt --interface interface/stlink.cfg --target target/stm32f4x.cfg --json

# Resume execution
python <skill-dir>/scripts/openocd_telnet.py resume --interface interface/stlink.cfg --target target/stm32f4x.cfg --json

# Single-step 5 times
python <skill-dir>/scripts/openocd_telnet.py step --count 5 --interface interface/stlink.cfg --target target/stm32f4x.cfg --json

# View registers
python <skill-dir>/scripts/openocd_telnet.py reg --interface interface/stlink.cfg --target target/stm32f4x.cfg --json

# Read memory (32bit x 16 words)
python <skill-dir>/scripts/openocd_telnet.py read-mem --address 0x20000000 --length 16 --width 32 --interface interface/stlink.cfg --target target/stm32f4x.cfg --json

# Write memory
python <skill-dir>/scripts/openocd_telnet.py write-mem --address 0x20000000 --value 0xDEADBEEF --width 32 --interface interface/stlink.cfg --target target/stm32f4x.cfg --json

# Set hardware breakpoint
python <skill-dir>/scripts/openocd_telnet.py bp --address 0x08001234 --bp-length 2 --interface interface/stlink.cfg --target target/stm32f4x.cfg --json

# Remove breakpoint
python <skill-dir>/scripts/openocd_telnet.py rbp --address 0x08001234 --interface interface/stlink.cfg --target target/stm32f4x.cfg --json

# Run to specified address (set breakpoint + resume + wait)
python <skill-dir>/scripts/openocd_telnet.py run-to --address 0x08001234 --timeout-ms 3000 --interface interface/stlink.cfg --target target/stm32f4x.cfg --json
```

Common optional arguments: `--board`, `--search`, `--adapter-speed`, `--transport`, `--gdb-port`, `--telnet-port`

### openocd_semihosting.py — Semihosting Output Capture

```bash
# Capture semihosting output (continuous until Ctrl+C)
python <skill-dir>/scripts/openocd_semihosting.py --interface interface/stlink.cfg --target target/stm32f4x.cfg --json

# Capture for 30 seconds
python <skill-dir>/scripts/openocd_semihosting.py --timeout 30 --interface interface/stlink.cfg --target target/stm32f4x.cfg --json
```

### openocd_itm.py — ITM/SWO Observation

```bash
# Continuously read ITM using configured TPIU parameters
python <skill-dir>/scripts/openocd_itm.py --interface interface/stlink.cfg --target target/stm32f4x.cfg --json

# Specify TPIU name and ports
python <skill-dir>/scripts/openocd_itm.py \
  --interface interface/stlink.cfg --target target/stm32f4x.cfg \
  --tpiu-name stm32f4x.tpiu --traceclk 168000000 --pin-freq 2000000 \
  --itm-port 0 --itm-port 1 --json
```

`openocd_itm.py` starts an independent OpenOCD Server, opens TPIU/ITM configuration, and uniformly wraps trace output into JSON Lines.

## Typical Debugging Workflows

### Quick Inspection (Telnet)

```
halt -> reg -> read-mem 0x20000000 -> step -> resume
```

Suitable for quickly inspecting current CPU state and memory contents.

### Breakpoint Debugging (Telnet)

```
run-to 0x08001234 -> reg -> read-mem -> resume
```

Halts after running to specified address, inspecting registers and memory.

### Source-Level Debugging (GDB)

```bash
gdb run --elf app.elf --commands "break main" "continue" "backtrace" "info locals"
```

Uses ELF file to provide symbol information for function-level breakpoints and variable inspection.

### Semihosting Output

```bash
semihosting
```

Captures debug information output by target via `printf` (SVC instruction), similar to J-Link RTT.

## Output Format

All scripts return in JSON format with base fields `status` (ok/error), `action`, `summary`, and `details`, optionally accompanied by `context`, `artifacts`, `metrics`, `state`, `next_actions`, and `timing`. Streaming observation commands use JSON Lines and uniformly output `source`, `channel_type`, and `stream_type`.

Success example:
```json
{
  "status": "ok",
  "action": "halt",
  "summary": "Halted, PC=0x08000298",
  "details": {
    "pc": "0x08000298",
    "xpsr": "0x01000000",
    "msp": "0x20020000",
    "halted": true
  }
}
```

GDB call stack example:
```json
{
  "status": "ok",
  "action": "backtrace",
  "summary": "GDB backtrace executed successfully",
  "details": {
    "gdb_port": 3333,
    "frames": [
      {"frame": 0, "function": "main", "location": "src/main.c:42"}
    ]
  }
}
```

Error example:
```json
{
  "status": "error",
  "action": "halt",
  "error": {
    "code": "server_failed",
    "message": "OpenOCD failed to start or timed out"
  }
}
```

## Core Rules

- Do not automatically guess combinations of `board`, `interface`, and `target`; prompt user if missing.
- When `board` is known, prefer board configuration; interface+target is no longer required.
- Parameter resolution priority: **CLI explicit arguments > `.embeddedskills/config.json` (project-level) > `skill/config.json` (environment-level) > `.embeddedskills/state.json` > defaults / error**.
- `.bin` files must explicitly provide flash address; report error if missing.
- Mapped targets such as STM32F4 will execute `reset halt` first under `erase --mode auto`, then prefer mass erase.
- `erase --mode mass` directly returns `mass_erase_unsupported` when no mapping matches, avoiding misleading assumptions that mass erase has completed.
- When flash lock protection is detected, only alert and do not automatically unlock.
- Provide troubleshooting advice on connection failure (check wiring, power, drivers, cfg paths) without automatically attempting aggressive parameters.
- Flashing, erasing, and reset are executed directly when parameters are complete and user intent is clear.
- `gdb-server` returns port and connection details after launch and keeps the process running.
- GDB debugging (run/backtrace/locals) requires `gdb_exe` (arm-none-eabi-gdb path) to be configured.
- Telnet debug commands start an independent OpenOCD Server per execution and shut down automatically when complete.
- Semihosting continuously reads OpenOCD stderr output after enabling via Telnet.
- Result echo always includes cfg combination, port, and executed action.
- Artifact paths (elf/file) do not enter project config and rely only on `state.json`.
- Runtime states such as `last_flash`/`last_debug`/`last_observe` continue to be written to `state.json`.

## References

Consult `references/common_targets.md` for board/interface/target configuration guidance.
