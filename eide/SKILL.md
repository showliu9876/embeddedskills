---
name: eide
description: >-
  EIDE (Embedded IDE) project build tool for scanning .eide/eide.yml projects,
  enumerating build configurations (ConfigName), executing build/rebuild/clean,
  and parsing build logs to return artifact paths reusable by jlink/openocd.
  Triggers automatically when the user mentions EIDE, Embedded IDE, eide.yml,
  unify_builder, VS Code EIDE extension, or Cl.eide, and also supports explicit
  /eide invocations. Even if the user only says "compile with EIDE" or "flash with
  EIDE to board", this skill should be triggered as long as the context involves
  an EIDE embedded project.
argument-hint: "[scan|configs|build|rebuild|clean|size] ..."
---

# EIDE Embedded Project Build

This skill provides discovery of EIDE (Embedded IDE) projects, enumeration of build configurations, incremental compilation, full rebuilds, cleaning, and ELF size analysis, returning firmware artifact paths for subsequent use by `jlink/openocd`.

EIDE is an embedded development extension for VS Code supporting ARM CC (AC5/AC6) or GCC toolchains, driven by the unified build backend `unify_builder`.

## Configuration

### Environment-level Configuration (skill/config.json)

The `config.json` in the skill directory contains environment-level configuration. Confirm that `builder_dir` is correct before first use:

```json
{
  "builder_dir": "~/.vscode/extensions/cl.eide-<version>/res/tools/linux/x86_64/unify_builder",
  "builder_exe": "unify_builder",
  "code_exe": "code",
  "toolchain_prefix": "arm-none-eabi-",
  "operation_mode": 1
}
```

- `builder_dir`: Directory where EIDE unify_builder resides (located under VS Code extension directory); when empty, auto-probes `~/.vscode`, `~/.vscode-server`, `~/.vscode-oss`, `~/.cursor` extension directories
- `builder_exe`: Builder executable file name, defaults to `unify_builder` on Linux
- `code_exe`: VS Code CLI path, searched from PATH for `code`/`codium`/`code-oss`/`code-insiders` by default
- `toolchain_prefix`: Toolchain prefix used for size analysis, defaults to `arm-none-eabi-`
- `operation_mode`: `1` execute directly / `2` print risk summary without blocking / `3` require confirmation before execution

### Project-level Configuration (workspace/.embeddedskills/config.json)

Project-level shared configuration is uniformly stored in `.embeddedskills/config.json` in the workspace:

```json
{
  "eide": {
    "project": "",
    "config": "",
    "log_dir": ".embeddedskills/build"
  }
}
```

- `project`: Default EIDE project root directory (directory containing `.eide/eide.yml`), automatically updated after successful build
- `config`: Default build configuration name (corresponding to ConfigName in eide.yml), automatically updated after successful build
- `log_dir`: Build log output directory, defaults to `.embeddedskills/build`

### Parameter Resolution Precedence

Parameter resolution order (from highest to lowest):
1. CLI explicit arguments
2. Environment-level configuration (skill/config.json)
3. Project-level configuration (.embeddedskills/config.json)
4. `.embeddedskills/state.json` (last build record)
5. Search / Prompt user

## Subcommands

| Subcommand | Description | Risk |
|------------|-------------|------|
| `scan` | Search for EIDE projects in current directory (directories containing `.eide/eide.yml`) | Low |
| `configs` | Enumerate build configurations in project | Low |
| `build` | Incremental build | Medium |
| `rebuild` | Full rebuild | Medium |
| `clean` | Clean build artifacts | High |
| `size` | Analyze ELF file size (text/data/bss and memory usage) | Low |

## Execution Workflow

1. Read `config.json` and verify `builder_dir` path is valid
2. When no subcommand is specified, default to `scan`
3. When no project path is provided, run `scan` first to discover projects
4. When multiple projects or configurations are found, list options for user selection; never guess automatically
5. `build/rebuild/clean` determine whether confirmation is needed according to `operation_mode`
6. Upon successful `build/rebuild`, resolve artifact paths such as `elf_file` / `hex_file` from the build directory
7. All build commands invoke `unify_builder` based on `builder.params` and parse output from log files
8. `size` defaults to analyzing the .elf file from the most recent build artifact

## Script Invocations

The skill directory contains Python scripts implemented using the standard library + PyYAML.

### eide_project.py — Project Scanning and Configuration Enumeration

```bash
# Scan projects
python <skill-dir>/scripts/eide_project.py scan --root <search_directory> --json

# Enumerate build configurations
python <skill-dir>/scripts/eide_project.py configs --project <project_directory> --json
```

### eide_build.py — Build / Rebuild / Clean

```bash
python <skill-dir>/scripts/eide_build.py <build|rebuild|clean> \
  --builder-dir <unify_builder_directory> \
  --project <project_root_directory> \
  --config <config_name> \
  --log-dir <log_directory> \
  --json
```

`rebuild` additionally supports `--clean-first` to clean before rebuilding.

### eide_size.py — ELF Size Analysis

```bash
# Basic analysis
python <skill-dir>/scripts/eide_size.py analyze \
  --elf <elf_file_path> \
  --toolchain-prefix arm-none-eabi- \
  --json

# Comparison analysis
python <skill-dir>/scripts/eide_size.py compare \
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
  "details": {
    "project": "Vendor/EIDE",
    "config": "W20_Mainboard",
    "build_dir": "build/W20_Mainboard",
    "elf_file": "build/W20_Mainboard/MDK-ARM_F403A.elf",
    "hex_file": "build/W20_Mainboard/MDK-ARM_F403A.hex",
    "log_file": ".embeddedskills/build/MDK-ARM_F403A-W20_Mainboard-build.log"
  },
  "artifacts": {
    "elf_file": "build/W20_Mainboard/MDK-ARM_F403A.elf",
    "hex_file": "build/W20_Mainboard/MDK-ARM_F403A.hex",
    "flash_file": "build/W20_Mainboard/MDK-ARM_F403A.hex",
    "debug_file": "build/W20_Mainboard/MDK-ARM_F403A.elf"
  },
  "metrics": { "errors": 0, "warnings": 2, "flash_bytes": 32768, "ram_bytes": 8192 }
}
```

Error example:
```json
{
  "status": "error",
  "action": "build",
  "error": { "code": "builder_not_found", "message": "unify_builder not found, please ensure EIDE extension is installed" }
}
```

## Core Rules

- Do not modify `.eide/eide.yml` or any EIDE project configuration files
- Do not automatically guess project paths or build configurations; prompt user when ambiguous
- Refer to the "Parameter Resolution Precedence" section above for parameter precedence
- After a successful build, prioritize passing returned `flash_file` / `debug_file` to `jlink/openocd`
- `clean` is never executed implicitly in automated workflows
- On build failure, prioritize displaying the first error and log file path
- Result echo must always include project name, config name, and build directory path; on successful build, prioritize echoing artifact paths
- An EIDE project root is defined as the directory containing `.eide/eide.yml`

## Relationship with Keil Projects

EIDE projects in this repository share source code and ARM CC toolchain (`D:\Keil_V543\ARM\ARMCLANG`) with Keil MDK projects. The EIDE project structure is described via `eide.yml`, and `builder.params` is generated automatically by EIDE for use by `unify_builder`. Output artifact formats (.axf/.hex/.elf) are mutually compatible and interchangeable.

## References

- EIDE extension: Search `cl.eide` in VS Code to install
- `eide.yml` format: See EIDE extension documentation
- `builder.params`: Automatically generated by EIDE, located at `build/<ConfigName>/builder.params`
