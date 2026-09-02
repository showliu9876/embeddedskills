# openocd

Claude Code skill for probe detection, firmware flashing, flash erasing, GDB Server launch, target reset, Telnet online debugging, GDB source-level debugging, and Semihosting/ITM output capture via OpenOCD. Supports open-source debug probes including ST-Link, CMSIS-DAP, DAPLink, and FTDI.

## Features

- Probe and target connectivity detection
- Firmware flashing (.elf / .hex / .bin)
- Flash erase (supports `auto|mass|sector` modes)
- GDB Server launch (for GDB connection and source-level debugging)
- Target reset (supports halt/run modes)
- **Telnet online debugging**: halt / resume / step / register inspection / memory read/write / hardware breakpoints / run-to
- **GDB debugging interaction**: custom GDB command sequence execution, quick call stack inspection, local variable inspection
- **Semihosting output capture**: capture target `printf` output (ARM Semihosting, similar to J-Link RTT)
- **ITM/SWO observation**: read SWO output based on TPIU/ITM

## Prerequisites

- [OpenOCD](https://openocd.org/) — Ensure `openocd` is executable or configure full path after installation
- Python 3.x (standard library only, no extra dependencies)
- Debug probe access permissions: Linux relies on libusb; non-root users must install udev rules provided by OpenOCD (`/usr/share/openocd/contrib/60-openocd.rules` → `/etc/udev/rules.d/`), applicable to CMSIS-DAP, ST-Link, FTDI
- [Arm GNU Toolchain](https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads) (`arm-none-eabi-gdb` is required for GDB debugging subcommands)

## Configuration

### Environment-Level Configuration (skill/config.json)

Copy `config.example.json` to `config.json` and adjust according to your actual environment:

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

| Field | Required | Description |
|-------|----------|-------------|
| `exe` | Yes | openocd path or command name |
| `scripts_dir` | No | OpenOCD configuration script directory, uses built-in path when empty |
| `gdb_port` | No | GDB Server port, default 3333 |
| `telnet_port` | No | Telnet port, default 4444 |
| `gdb_exe` | No | arm-none-eabi-gdb path, required for GDB debugging subcommands |
| `operation_mode` | No | `1` direct execution / `2` output risk summary / `3` confirm before execution |

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

Parameter resolution priority: **CLI arguments > project configuration > state.json > defaults**

Upon successful execution, confirmed parameters are automatically written back to the project configuration.

Currently implemented basic commands also include `targets`, `flash-banks`, `adapter-info`, `raw`, and `gdb-server`. Observation commands support `itm` in addition to `semihosting`.

## Erase Behavior

- `erase --mode auto`: prefers target-mapped mass erase, falls back to sector erase when no match is found
- `erase --mode mass`: forces mass erase; returns `mass_erase_unsupported` if current target has no mapping
- `erase --mode sector`: forces bank erase via `flash erase_sector <bank> 0 last`
- `.bin` flashing must explicitly provide an address, such as `0x08000000`
