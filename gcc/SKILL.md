---
name: gcc
description: >-
  GCC embedded project build tool (CMake + arm-none-eabi-gcc) for scanning CMake
  embedded projects, listing presets, configuring, compiling, rebuilding,
  cleaning, and analyzing ELF sizes. Triggers automatically when the user mentions
  GCC, arm-none-eabi, CMake embedded build, Ninja build, ELF size analysis,
  arm-gcc, cross compilation, cmake --build, or cmake --preset, and also supports
  explicit /gcc invocations. Even if the user only says "compile it" or "check
  firmware size", this skill should be triggered as long as the context involves
  a CMake embedded GCC project.
argument-hint: "[scan|presets|configure|build|rebuild|clean|size] ..."
---

# GCC Embedded Project Build

This skill provides discovery of embedded projects based on CMake + arm-none-eabi-gcc, preset enumeration, configuration generation, incremental compilation, full rebuilds, cleaning, and ELF size analysis.

Scope note: Currently only supports **CMake-based** GCC embedded projects; does not cover pure `Makefile` projects.

## Configuration

### Environment-level Configuration (skill/config.json)

The `config.json` in the skill directory contains environment-level configuration. Confirm that `cmake_exe` is correct before first use:

```json
{
  "cmake_exe": "cmake",
  "toolchain_prefix": "arm-none-eabi-",
  "toolchain_path": "",
  "operation_mode": 1
}
```

- `cmake_exe`: CMake executable path, searched from PATH by default
- `toolchain_prefix`: Toolchain prefix, defaults to `arm-none-eabi-`, used to locate size and other tools
- `toolchain_path`: Toolchain bin directory; searched from PATH when empty
- `operation_mode`: `1` execute directly / `2` output risk summary without blocking / `3` require confirmation before execution

### Project-level Configuration (workspace/.embeddedskills/config.json)

Project-level shared configuration is uniformly stored in `.embeddedskills/config.json` in the workspace:

```json
{
  "gcc": {
    "project": "",
    "preset": "",
    "log_dir": ".embeddedskills/build"
  }
}
```

- `project`: Default project path (relative to workspace), automatically updated after successful build
- `preset`: Default CMake preset name, automatically updated after successful build
- `log_dir`: Build log output directory, defaults to `.embeddedskills/build`

### Parameter Resolution Precedence

Parameter resolution order (from highest to lowest):
1. CLI explicit arguments
2. Environment-level configuration (skill/config.json)
3. Project-level configuration (.embeddedskills/config.json)
4. state.json (last build record)
5. Search / Prompt user

Conflict resolution rule: When the same parameter exists in multiple sources, the source with the lowest ordinal index prevails; higher-index sources only take effect when lower-index sources do not provide the parameter. For example: If CLI specifies `--preset Debug`, the previous preset recorded in state.json is ignored.

## Subcommands

| Subcommand | Description | Risk |
|---|---|---|
| `scan` | Search for CMake embedded projects in the current directory | Low |
| `presets` | List configure/build presets in CMakePresets.json | Low |
| `configure` | Run `cmake --preset` to generate build system | Medium |
| `build` | Incremental build `cmake --build` | Medium |
| `rebuild` | Full rebuild after clean | Medium |
| `clean` | Clean build directory | High |
| `size` | Analyze ELF file size (text/data/bss and memory usage) | Low |

## Execution Workflow

1. Read `config.json` and verify `cmake_exe` path is valid
2. When no valid subcommand is provided, default to `scan`
3. When no project path is provided, run `scan` first to discover projects
4. When multiple projects or presets are found, list options for user selection; never guess automatically
5. `configure/build/rebuild/clean` determine whether confirmation is needed according to `operation_mode`
6. Automatically check whether configured before `build`; prompt to execute configure first if not configured
7. Return `elf_file` upon successful `build/rebuild` for subsequent use by `jlink/openocd`
8. `size` defaults to analyzing the .elf file from the most recent build artifact

## Script Invocations

The skill directory contains three Python scripts implemented using the standard library with no extra dependencies.

### gcc_project.py — Project Scanning and Preset Enumeration

```bash
# Scan projects
python <skill-dir>/scripts/gcc_project.py scan --root <search_directory> --json

# List presets
python <skill-dir>/scripts/gcc_project.py presets --project <project_directory> --json
```

### gcc_build.py — Configure / Build / Rebuild / Clean

```bash
python <skill-dir>/scripts/gcc_build.py <configure|build|rebuild|clean> \
  --cmake <cmake_path> \
  --project <project_root_directory> \
  --preset <preset_name> \
  --log-dir <log_directory> \
  --json
```

### gcc_size.py — ELF Size Analysis

```bash
# Basic analysis
python <skill-dir>/scripts/gcc_size.py analyze \
  --elf <elf_file_path> \
  --toolchain-prefix arm-none-eabi- \
  --linker-script <linker_script_path> \
  --json

# Comparison analysis
python <skill-dir>/scripts/gcc_size.py compare \
  --elf <elf_file_1> \
  --compare <elf_file_2> \
  --toolchain-prefix arm-none-eabi- \
  --json
```

## Output Format

All scripts return results in JSON format with base fields `status` (ok/error), `action`, `summary`, `details`, and optionally `context`, `artifacts`, `metrics`, `state`, `next_actions`, `timing`.

Success example:
```json
{
  "status": "ok",
  "action": "build",
  "summary": "build succeeded, errors=0 warnings=2",
  "details": { "project": "...", "preset": "Debug", "build_dir": "...", "elf_file": "...", "log_file": "..." },
  "metrics": { "errors": 0, "warnings": 2, "flash_bytes": 99328, "ram_bytes": 46080 }
}
```

Error example:
```json
{
  "status": "error",
  "action": "build",
  "error": { "code": "not_configured", "message": "Build directory does not exist, please execute configure first" }
}
```

## Core Rules

- Do not modify CMakeLists.txt or any CMake configuration files
- Currently this skill only covers CMake-based GCC projects; does not recognize or build pure Makefile projects
- Do not automatically guess project paths or presets; prompt user when ambiguous
- Parameter resolution precedence: CLI explicit arguments > Environment-level config > Project-level config > `.embeddedskills/state.json` > Search / Prompt user
- `clean` is never executed implicitly in automated workflows
- On build failure, prioritize displaying the first error and log file path
- Result echo must always include project name, preset name, and build directory path; on successful build, prioritize echoing `elf_file`
