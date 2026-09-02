---
name: probe-rs
description: >-
  probe-rs programming and debugging tool for probe discovery, firmware flashing, reset,
  memory read/write, GDB server debugging, and RTT log reading. Triggers automatically
  when the user mentions probe-rs, cargo-embed, DAP, RTT, CMSIS-DAP, ST-Link, J-Link,
  flashing, chip info, connect under reset, probe selector, probe-rs gdb, or probe-rs attach,
  and supports explicit /probe-rs calls. Even if the user says "flash using probe-rs",
  "check RTT", or "pull a backtrace", trigger this skill whenever the context clearly refers
  to probe-rs features, CLI commands, or related terms.
argument-hint: "[list|info|flash|erase|reset|read-mem|write-mem|attach|run|gdb|rtt] ..."
---

# probe-rs Flashing and Debugging

This skill provides a structured wrapper around the `probe-rs` CLI, covering probe discovery, target information inspection, flashing, resetting, memory read/write, one-shot GDB debugging, and RTT log capture.

Scripts are invoked via system `python3`; if `probe-rs` and `arm-none-eabi-gdb` (or `gdb-multiarch`) are already in `PATH`, they will be discovered automatically without strictly requiring the skill's `config.json`.

## Configuration

### Machine-Level Configuration (skill/config.json)

Before first use, creating a `config.json` under the skill directory is recommended:

```json
{
  "exe": "probe-rs",
  "gdb_exe": "/usr/bin/arm-none-eabi-gdb",
  "gdb_port": 3333,
  "dap_port": 50000,
  "operation_mode": 1
}
```

- `exe`: Path or command name for the `probe-rs` executable
- `gdb_exe`: Path to `arm-none-eabi-gdb`, required for the `gdb` subcommand
- `gdb_port`: Default GDB port
- `dap_port`: Reserved for interactive DAP sessions
- `operation_mode`: `1` direct execution / `2` output risk summary without blocking / `3` require confirmation before execution

### Project-Level Configuration (.embeddedskills/config.json)

```json
{
  "probe-rs": {
    "chip": "STM32F407VGTx",
    "protocol": "swd",
    "probe": "",
    "speed": 4000,
    "connect_under_reset": false
  }
}
```

- `chip`: Target chip model, mandatory for the `probe-rs` primary backend
- `protocol`: `swd` or `jtag`
- `probe`: Probe selector in `VID:PID[:Serial]` format
- `speed`: Debug speed in kHz
- `connect_under_reset`: Whether to hold reset during connection

Parameter resolution priority: **CLI arguments > Project configuration (.embeddedskills/config.json) > state.json > Skill configuration (config.json) > Defaults**

Layer responsibilities: skill `config.json` supplies machine-level constants such as tool paths and ports; `.embeddedskills/config.json` supplies project-level parameters like chip and protocol; CLI arguments override everything for a single invocation.

## Subcommands

| Subcommand | Purpose | Risk |
|---|---|---|
| `list` | Enumerate available probes | Low |
| `info` | Inspect probe and target information | Low |
| `flash` | Flash firmware (elf/hex/bin/uf2) | High |
| `erase` | Erase target chip non-volatile storage | High |
| `reset` | Reset target chip | High |
| `read-mem` | Read target memory | Low |
| `write-mem` | Write target memory | High |
| `attach` / `run` | Wrap probe-rs attach/run | Low |
| `gdb` | Start GDB server and execute one-shot debug | Low |
| `rtt` | Read RTT logs | Low |

## Typical Invocations

```bash
# List probes
py -3 <skill-dir>/scripts/probe_rs_exec.py list --json

# Flash ELF
py -3 <skill-dir>/scripts/probe_rs_exec.py flash --chip STM32F407VGTx --file build/app.elf --json

# Flash BIN (address is mandatory)
py -3 <skill-dir>/scripts/probe_rs_exec.py flash --chip STM32F407VGTx --file build/app.bin --address 0x08000000 --json

# Read memory
py -3 <skill-dir>/scripts/probe_rs_exec.py read-mem --chip STM32F407VGTx --address 0x20000000 --length 16 --width b32 --json

# One-shot backtrace
py -3 <skill-dir>/scripts/probe_rs_gdb.py backtrace --chip STM32F407VGTx --elf build/app.elf --json

# RTT
py -3 <skill-dir>/scripts/probe_rs_rtt.py --chip STM32F407VGTx --json
```

## Core Rules

- Never guess `chip`; raise an error immediately if missing.
- In multi-probe scenarios, explicitly specifying `--probe` is recommended. If no probe is detected, prompt the user to check USB connection and retry. If probe configuration fails (e.g. VID:PID mismatch), report the specific error and suggest running `list` to inspect available probes.
- Flashing `.bin` files requires an explicit address.
- `workflow build-debug` only uses one-shot diagnostic wrappers and does not launch long-running DAP sessions requiring manual intervention.
- Non-root users on Linux need udev rules to access probes; install the official `probe-rs` rules (`69-probe-rs.rules` → `/etc/udev/rules.d/`), then execute `sudo udevadm control --reload` and replug the probe.
- `probe-rs` and official SEGGER tools contend for the same J-Link device; do not run them concurrently. If still dependent on the official J-Link toolchain, prioritize using the existing `jlink` skill.
