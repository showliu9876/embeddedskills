---
name: keil
description: >-
  Keil MDK project build tool for scanning .uvprojx/.uvproj/.uvmpw projects,
  enumerating Targets, executing build/rebuild/clean, and parsing build logs to
  return artifact paths reusable by jlink/openocd. The flash subcommand is retained
  only as a compatibility entry point. Triggers automatically when the user
  mentions Keil, MDK, uVision, UV4, Target enumeration, compile, rebuild, clean,
  flash, download firmware, and also supports explicit /keil invocations. Even if
  the user only says "compile it" or "flash to board", this skill should be
  triggered as long as the context involves an embedded Keil project.
argument-hint: "[scan|targets|build|rebuild|clean|flash] ..."
---

# Keil MDK Project Build

> **Platform Restriction: Windows Only.** There is no Linux version of Keil MDK's `UV4.exe`; this skill cannot run on Linux.
> All other skills in this repository use Linux as their default platform; to build embedded projects on Linux, use the `gcc` or `eide` skill instead.

This skill provides discovery of Keil MDK projects, Target enumeration, build, rebuild, and clean capabilities, returning firmware artifact paths for subsequent use by `jlink/openocd`. `flash` is retained only as a compatibility entry point.

## Configuration

### Environment-level Configuration (skill/config.json)

The `config.json` in the skill directory contains environment-level configuration. Confirm that `uv4_exe` is correct before first use:

```json
{
  "uv4_exe": "C:\\Keil_v5\\UV4\\UV4.exe",
  "operation_mode": 1
}
```

- `uv4_exe`: Full path to UV4.exe (required)
- `operation_mode`: `1` execute directly / `2` output risk summary without blocking / `3` require confirmation before execution

### Project-level Configuration (workspace/.embeddedskills/config.json)

Project-level shared configuration is uniformly stored in `.embeddedskills/config.json` in the workspace:

```json
{
  "keil": {
    "project": "",
    "target": "",
    "log_dir": ".embeddedskills/build"
  }
}
```

- `project`: Default project path (relative to workspace), automatically updated after successful build
- `target`: Default Target name, automatically updated after successful build
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
|---|---|---|
| `scan` | Search for .uvprojx/.uvproj/.uvmpw projects in current directory | Low |
| `targets` | Enumerate Targets in project | Low |
| `build` | Incremental build | Medium |
| `rebuild` | Full rebuild | Medium |
| `clean` | Clean project | High |
| `flash` | Flash firmware via Keil (compatibility entry point, jlink/openocd preferred) | High |

## Execution Workflow

1. Read `config.json` and verify `uv4_exe` path is valid
2. When no subcommand is specified, default to `scan`
3. When no project path is provided, run `scan` first to discover projects
4. When multiple projects or Targets are found, list options for user selection; never guess automatically
5. `build/rebuild/clean` determine whether confirmation is needed according to `operation_mode`
6. Upon successful `build/rebuild`, resolve artifact paths such as `flash_file` / `debug_file` from project configuration whenever possible
7. `flash` is only permitted when the most recent build succeeded
8. All build commands output to log files and are parsed to return structured results

## Script Invocations

The skill directory contains two Python scripts implemented using the standard library with no extra dependencies.

### keil_project.py — Project Scanning and Target Enumeration

```bash
# Scan projects
python <skill-dir>/scripts/keil_project.py scan --root <search_directory> --json

# Enumerate Targets
python <skill-dir>/scripts/keil_project.py targets --project <project_path> --json
```

### keil_build.py — Build / Rebuild / Clean / Flash

```bash
python <skill-dir>/scripts/keil_build.py <build|rebuild|clean|flash> \
  --uv4 <UV4_path> \
  --project <project_path> \
  --target <TargetName> \
  --log-dir <log_directory> \
  --json
```

`rebuild` additionally supports `--clean-first` to use `-cr` instead of `-r`.

## Output Format

All scripts return results in JSON format with base fields `status` (ok/error), `action`, `summary`, `details`, and optionally `context`, `artifacts`, `metrics`, `state`, `next_actions`, `timing`.

Success example:
```json
{
  "status": "ok",
  "action": "build",
  "summary": "build succeeded, errors=0 warnings=2",
  "details": {
    "project": "project.uvprojx",
    "target": "Debug",
    "log_file": ".build/project-Debug-build.log",
    "flash_file": "Objects/project.hex",
    "debug_file": "Objects/project.axf"
  },
  "metrics": { "errors": 0, "warnings": 2, "flash_bytes": 32768, "ram_bytes": 8192 }
}
```

Error example:
```json
{
  "status": "error",
  "action": "flash",
  "error": { "code": "build_not_clean", "message": "Last build contained errors; flashing is prohibited" }
}
```

## Core Rules

- Do not modify project configuration files (.uvprojx / .uvproj / .uvmpw / .uvoptx)
- `.uvproj` (legacy MDK4 projects) shares the same XML structure (Target/TargetOption/TargetCommonOption) with `.uvprojx`; artifact parsing, Target enumeration, and scanning support both extensions
- Do not automatically guess project paths or Targets; prompt user when ambiguous
- Refer to the "Parameter Resolution Precedence" section above for parameter precedence
- After a successful build, prioritize passing returned `flash_file` / `debug_file` to `jlink/openocd`
- Before `flash`, must confirm the most recent build succeeded (errors == 0)
- `clean` is never executed implicitly in automated workflows
- On build failure, prioritize displaying the first error and log file path
- Result echo must always include project name, Target name, and log path; echo artifact paths when detected

## References

Refer to `references/compiler-notes.md` when encountering compiler-related issues.
