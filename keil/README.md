# keil

Claude Code skill for driving Keil MDK to scan projects, enumerate Targets, compile and build, and return artifact paths to hand over to `jlink/openocd`. `flash` is retained as a compatibility entry point.

## Features

- Scan directories for .uvprojx / .uvproj / .uvmpw project files
- Enumerate Targets in projects
- Incremental build / Full rebuild / Clean
- Return artifact paths such as `flash_file` / `debug_file` for seamless handover to `jlink/openocd`
- Download firmware to target board via Keil (compatibility entry point)
- Parse build logs and output structured error/warning information

## Requirements

> **Platform Restriction: Windows Only.** There is no Linux version of `UV4.exe`; this skill cannot run on Linux.
> All other skills in this repository use Linux as their default platform; to build embedded projects on Linux, use the `gcc` or `eide` skill instead.

- [Keil MDK](https://www.keil.com/mdk5/) — Provides UV4.exe
- Python 3.x (standard library only, no extra dependencies)

## Configuration

### Environment-level Configuration (skill/config.json)

Copy `config.example.json` to `config.json` and adjust according to the actual installation path:

```json
{
  "uv4_exe": "C:\\Keil_v5\\UV4\\UV4.exe",
  "operation_mode": 1
}
```

| Field | Required | Description |
|---|---|---|
| `uv4_exe` | Yes | Full path to UV4.exe |
| `operation_mode` | No | `1` execute directly / `2` output risk summary / `3` require confirmation before execution |

### Project-level Configuration (workspace/.embeddedskills/config.json)

Project-level shared configuration is stored in `.embeddedskills/config.json` within the workspace:

```json
{
  "keil": {
    "project": "",
    "target": "",
    "log_dir": ".embeddedskills/build"
  }
}
```

| Field | Description |
|---|---|
| `project` | Default project path (relative to workspace) |
| `target` | Default Target name |
| `log_dir` | Build log output directory, defaults to `.embeddedskills/build` |

### Parameter Resolution Precedence

Parameter resolution order (from highest to lowest):
1. CLI explicit arguments
2. Environment-level configuration (skill/config.json)
3. Project-level configuration (.embeddedskills/config.json)
4. state.json (last build record)
5. Search / Prompt user
