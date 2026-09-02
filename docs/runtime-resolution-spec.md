# Unified Runtime Environment Resolution Specification

## Purpose

This document defines the unified runtime environment resolution specification to be adopted across all skills in embeddedskills, replacing the previously fragmented and inconsistent parameter parsing logic in individual skills.

Goals:

- Standardize the responsibilities and precedence of `CLI / skill/config.json / .embeddedskills/config.json / .embeddedskills/state.json / system PATH`
- Explicitly define which parameters are allowed to be resolved from which layers
- Require scripts to proactively probe the system `PATH`, rather than passively relying on errors after execution failure
- Standardize parameter source echoing, automatic writeback, and missing parameter handling

## Scope

Applies to the following skills:

- `can`
- `serial`
- `net`
- `gcc`
- `keil`
- `jlink`
- `openocd`
- `probe-rs`
- `workflow`

## File Responsibilities

### 1. CLI Explicit Arguments

Highest priority. Arguments explicitly provided by the user in the current invocation must override all other sources.

### 2. `skill/config.json`

Machine-level environment configuration. Only stores settings specific to the local machine that should not be committed to the project repository.

Allowed:

- Tool executable paths, e.g., `uv4_exe`, `cmake_exe`, `gdb_exe`
- Default paths for local probes, packet capture tools, and serial port tools
- Local private hardware parameters, e.g., default probe serial number of the local machine

Not allowed:

- Project paths
- Chip models, targets, board/interface/target
- Build presets, log directories, artifact paths

### 3. `<workspace>/.embeddedskills/config.json`

Project-level shared configuration. Used to persist default parameters shareable among project members.

Allowed:

- Project paths, targets, presets
- Chip models, interface types, protocol types
- `workflow.preferred_*`
- Shared log directories

Not allowed:

- Machine-dependent absolute tool paths
- Absolute paths depending on the current user's home directory (e.g., `/home/<user>/...`)

### 4. `<workspace>/.embeddedskills/state.json`

Runtime state, not a source of truth for configuration. Used solely as a fallback source from the most recent successful execution.

Allowed:

- Parameters used in the most recent successful build / flash / debug / observe operation
- Most recent build artifact paths
- Results from the most recent auto-discovery or auto-completion

Not allowed:

- Long-term storage of tool paths
- Overriding project configuration

### 5. System `PATH`

Used for proactive discovery of tool commands. Not a configuration file layer, but a formal resolution tier.

Applicable to:

- `cmake`
- `probe-rs`
- `openocd`
- `arm-none-eabi-gdb`
- `JLinkExe`, `JLinkGDBServerCLExe`
- `tshark`, `capinfos`
- Other executable tools

## Unified Resolution Model

Not all parameters follow the exact same resolution order. The unified specification defines available sources according to parameter types.

### A. Executable / Command Parameters

Examples:

- `exe`
- `uv4_exe`
- `cmake_exe`
- `gdb_exe`
- `gdbserver_exe`
- `tshark_exe`

Unified precedence:

1. CLI explicit arguments
2. `skill/config.json`
3. System `PATH`
4. Built-in command name defaults
5. Raise error

Rules:

- Do not read absolute tool paths from `.embeddedskills/config.json`
- Do not fall back tool paths from `state.json`
- If multiple candidates are matched in `PATH`, prefer the first result returned by `shutil.which()`

### B. Project / Hardware Configuration Parameters

Examples:

- `project`
- `target`
- `preset`
- `device`
- `chip`
- `board`
- `interface`
- `transport`
- `protocol`
- `speed`
- `adapter_speed`
- `connect_under_reset`

Unified precedence:

1. CLI explicit arguments
2. `.embeddedskills/config.json`
3. `.embeddedskills/state.json`
4. Auto-discovery
5. Built-in defaults
6. Prompt user or raise error

Rules:

- Do not read project truth parameters from `skill/config.json`
- `state.json` is only a fallback for the most recent successful result
- Auto-discovery can only be used for "enumerable and unambiguous" parameters, such as a single project, a single serial port, or a single CAN interface

### C. Artifact / Input File Path Parameters

Examples:

- `elf`
- `file`
- `flash_file`
- `debug_file`

Unified precedence:

1. CLI explicit arguments
2. `.embeddedskills/config.json`
3. `.embeddedskills/state.json`
4. Workspace search
5. Raise error

Rules:

- Fallback to the artifact of the last successful build from `state.json` is allowed
- Workspace search must be explainable, prioritizing the latest build directory or conventional directories; unbounded recursive guessing is not permitted

### D. Runtime Port / Log / Observation Parameters

Examples:

- `gdb_port`
- `telnet_port`
- `rtt_port`
- `log_dir`
- `capture_format`

Unified precedence:

1. CLI explicit arguments
2. `.embeddedskills/config.json`
3. `skill/config.json`
4. `.embeddedskills/state.json`
5. Built-in defaults

Rules:

- `log_dir` is a project-level priority parameter, prioritizing project configuration
- Port-like parameters allow machine defaults to be provided at the environment level

### E. workflow Compatibility Override File

Only `workflow` retains the `--config` compatibility entry point.

Precedence:

1. CLI explicit arguments
2. Compatibility config file pointed to by `--config`
3. `.embeddedskills/config.json`
4. Auto-discovery
5. Raise error

Note:

- This layer is only used for backward compatibility with legacy usage and does not serve as a general mechanism for other skills

## System PATH Proactive Probing Specification

All skills requiring external tools must proactively probe the system `PATH`.

### Probing Requirements

1. Prefer using Python `shutil.which()`
2. Define candidate command name lists for the same tool, **with Linux names first and Windows names at the end as a minimal compatibility layer**
3. If no match in `PATH`, probe common installation prefixes for the tool (e.g., `/opt/SEGGER/JLink`, `/usr/share/openocd/scripts`)
4. Record the absolute path upon a match
5. Proceed to default values or error branches only when probing fails

### Candidate Command Examples

- `cmake`: `["cmake", "cmake.exe"]`
- `probe-rs`: `["probe-rs", "probe-rs.exe"]`
- `openocd`: `["openocd", "openocd.exe"]`
- `arm-none-eabi-gdb`: `["arm-none-eabi-gdb", "gdb-multiarch", "arm-none-eabi-gdb.exe"]`
- J-Link Commander: `["JLinkExe", "JLink.exe"]`
- J-Link GDB Server: `["JLinkGDBServerCLExe", "JLinkGDBServerCL.exe"]`
- `tshark`: `["tshark", "tshark.exe"]`

### Source Tagging

When matching `PATH`, `parameter_sources` must be uniformly recorded as:

- `path:cmake`
- `path:probe-rs`
- `path:arm-none-eabi-gdb`

Do not record as an ambiguous `path`.

When matching an installation directory (instead of `PATH`), uniformly record as `install_dir:<absolute_path>`, for example `install_dir:/opt/SEGGER/JLink/JLinkExe`.

## Automatic Writeback Specification

### Writeback to `.embeddedskills/config.json`

Only allowed to write back "confirmed project-level parameters":

- Project parameters after successful auto-discovery with a single candidate
- `device/chip/interface/target/preset/project` confirmed valid after successful user execution
- `workflow.preferred_*`

### Writeback to `.embeddedskills/state.json`

Write back the record of the most recent successful run:

- `last_build`
- `last_flash`
- `last_debug`
- `last_observe`
- Technically reusable artifact paths

### Do Not Automatically Write Back to `skill/config.json`

Even if a tool is successfully discovered via `PATH`, do not automatically write back to `skill/config.json`.

Reasons:

- `skill/config.json` is a local machine explicit configuration and should not be contaminated by a transient match
- If persisting PATH match results is desired in the future, it must be explicitly confirmed by the user

## Handling Missing Parameters

### Allowed Auto-Discovery

Limited to the following scenarios:

- Exactly one project found after scanning
- Exactly one serial port found after scanning
- Exactly one CAN interface found after scanning
- Exactly one clearly matched build artifact in the workspace

### Disallowed Automatic Guessing

When the following parameters are missing, an error must be raised or the user must be prompted to specify explicitly:

- `device` among multiple candidates
- Probe serial number among multiple candidates
- `board/interface/target` among multiple candidates
- `.bin` flash address

## Unified Implementation Recommendations

Future implementations should converge into a common resolver supporting at least:

- `cli_value`
- `project_config`
- `local_config`
- `state_record`
- `path_candidates`
- `default`
- `required`
- `normalize_as_path`
- `source_policy`

Where `source_policy` declares which category the parameter belongs to:

- `tool_exe`
- `project_param`
- `artifact_path`
- `runtime_option`

## Differences from the Current Repository

Once this specification is effective, the following behaviors need to be updated:

- Discrepancies between helper documentation and actual invocations in `can / serial / net`
- Two sets of precedence descriptions present in `SKILL.md` of `jlink` and `openocd`
- Alignment of `openocd_telnet.py` with other `openocd_*` scripts
- Addition of the `PATH` proactive probing tier in `probe-rs` documentation
- Upgrading the "three-layer configuration" description in `README.md` and `docs/getting-started.md` to the unified model including `PATH`

## Unified External Statement

When presenting to users, the recommended unified statement is:

> Parameter precedence is resolved according to parameter type. Project parameters prioritize CLI and `.embeddedskills/config.json`, tool paths prioritize CLI, `skill/config.json`, and system `PATH`, and runtime history only serves as a fallback source from `state.json`.
