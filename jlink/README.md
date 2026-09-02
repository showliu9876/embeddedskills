# jlink

Skill for embedded firmware flashing, memory read/write, register inspection, RTT/SWO log capture, and on-target debugging via J-Link debug probes.

## Features

- Probe and target connectivity detection
- Firmware flashing (.hex / .bin / .elf)
- Memory read/write, register inspection, target reset
- Real-time RTT log capture
- SWO event stream wrapping (via external viewer)
- On-target debugging: halt / go / step / run-to breakpoint
- GDB source-level debugging: call stack and local variable inspection

## Prerequisites

- [SEGGER J-Link Software (Linux DEB/RPM/TGZ)](https://www.segger.com/downloads/jlink/) — Provides `JLinkExe`, `JLinkGDBServerCLExe`, `JLinkRTTClient`, `JLinkSWOViewerCLExe`, typically installed under `/opt/SEGGER/JLink`.
- Non-root access to probes requires SEGGER's udev rules (DEB/RPM packages install to `/etc/udev/rules.d/` automatically).
- Python 3.x (standard library only, no external dependencies).
- GDB debugging requires `arm-none-eabi-gdb` (`apt install gcc-arm-none-eabi gdb-multiarch`, or [Arm GNU Toolchain](https://developer.arm.com/Tools%20and%20Software/GNU%20Toolchain)).

## Configuration

### Machine-Level Configuration (skill/config.json)

Copy `config.example.json` to `config.json` and adjust based on actual installation paths:

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

| Field | Required | Description |
|---|---|---|
| `exe` | No | Full path to `JLinkExe`; when omitted, auto-probes PATH and installation dirs like `/opt/SEGGER/JLink` |
| `gdbserver_exe` | No | Path to `JLinkGDBServerCLExe`, required for RTT and GDB debugging |
| `rtt_exe` | No | Path to `JLinkRTTClient`, required for RTT |
| `gdb_exe` | No | Path to `arm-none-eabi-gdb`, required for source-level GDB debugging |
| `serial_no` | No | Probe serial number, used in multi-probe environments |
| `rtt_telnet_port` | No | RTT port, `0` to use tool default |
| `swo_command` | No | Full command array for external SWO viewer, wrapped by `jlink_swo.py` |
| `operation_mode` | No | `1` direct execution / `2` output risk summary / `3` require confirmation before execution |

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

Parameter resolution priority: **CLI arguments > Project configuration > state.json > Defaults**

After successful execution, confirmed device/interface/speed values are automatically written back to project configuration.
