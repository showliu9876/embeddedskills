# gcc

Claude Code skill for embedded project scanning, preset enumeration, configuration, building, and ELF size analysis based on CMake + arm-none-eabi-gcc.

Scope note: Currently only supports **CMake-based** embedded GCC projects; does not cover pure `Makefile` projects.

## Features

- Scan directories for embedded CMake projects
- Enumerate configure/build presets in `CMakePresets.json`
- Execute `configure` / `build` / `rebuild` / `clean`
- Analyze ELF `text` / `data` / `bss` and memory footprint
- Return artifact paths such as `elf_file` / `flash_file` / `debug_file` / `log_file` for seamless handover to `jlink/openocd`

## Requirements

- [CMake](https://cmake.org/) 3.21 or higher
- Ninja (recommended) or Make
- [Arm GNU Toolchain](https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads) (provides `arm-none-eabi-gcc`, `arm-none-eabi-size`, etc.)
- Python 3.x (standard library only, no extra dependencies)

## Configuration

### Environment-level Configuration (skill/config.json)

Copy `config.example.json` to `config.json` and adjust according to the actual environment:

```json
{
  "cmake_exe": "cmake",
  "toolchain_prefix": "arm-none-eabi-",
  "toolchain_path": "",
  "operation_mode": 1
}
```

| Field | Required | Description |
|---|---|---|
| `cmake_exe` | No | Path to `cmake` or command name, searched from PATH by default |
| `toolchain_prefix` | No | Toolchain prefix, defaults to `arm-none-eabi-` |
| `toolchain_path` | No | Toolchain bin directory; searched from PATH when empty |
| `operation_mode` | No | `1` execute directly / `2` output risk summary / `3` require confirmation before execution |

### Project-level Configuration (workspace/.embeddedskills/config.json)

Project-level shared configuration is stored in `.embeddedskills/config.json` within the workspace:

```json
{
  "gcc": {
    "project": "",
    "preset": "",
    "log_dir": ".embeddedskills/build"
  }
}
```

| Field | Description |
|---|---|
| `project` | Default project path (relative to workspace) |
| `preset` | Default CMake preset name |
| `log_dir` | Build log output directory, defaults to `.embeddedskills/build` |

### Parameter Resolution Precedence

Parameter resolution order (from highest to lowest):
1. CLI explicit arguments
2. Environment-level configuration (skill/config.json)
3. Project-level configuration (.embeddedskills/config.json)
4. state.json (last build record)
5. Search / Prompt user

## Subcommands

| Subcommand | Description |
|---|---|
| `scan` | Search for embedded CMake projects |
| `presets` | List CMake presets |
| `configure` | Generate build system |
| `build` | Incremental build |
| `rebuild` | Full rebuild |
| `clean` | Clean build directory |
| `size` | Analyze ELF size |

## Usage Notes

- If `configure` has not been completed before `build`, the script prompts to run `configure` first
- When multiple projects or presets are found, only candidate options are returned without automatic guessing
- Upon successful `build/rebuild`, returns `elf_file`, which is also reused as `flash_file` and `debug_file`
- `size` defaults to analyzing the most recent build artifact; underlying `gcc_size.py` additionally supports comparison between two ELFs
- `clean` is never executed implicitly in automated workflows
