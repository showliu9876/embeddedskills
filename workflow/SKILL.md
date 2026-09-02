---
name: workflow
description: >-
  Thin orchestration layer for embeddedskills to discover projects in the current workspace, select build/flash/debug/observe
  backends, chain .embeddedskills/state.json, and aggregate underlying skill results.
  Trigger when the user mentions one-click build and flash, automated diagnosis, chaining build -> flash -> debug -> observe, or explicitly calls /workflow.
argument-hint: "[plan|build|build-flash|build-debug|observe|diagnose] ..."
---

# Workflow Orchestration Layer

This skill does not re-implement underlying logic; it only handles discovery, selection, chaining, and aggregation.

Supports three build backends: **Keil** / **GCC** / **EIDE**, and three flash/debug/observe backends: **jlink** / **openocd** / **probe-rs**.

The `observe` phase currently provides candidate observation backends: `jlink:rtt`, `jlink:swo`, `openocd:semihosting`, `openocd:itm`, and `probe-rs:rtt`.

## Commands

```bash
python <skill-dir>/scripts/workflow_plan.py --json
python <skill-dir>/scripts/workflow_run.py plan --json
python <skill-dir>/scripts/workflow_run.py build --json
python <skill-dir>/scripts/workflow_run.py build-flash --json
python <skill-dir>/scripts/workflow_run.py build-debug --json
python <skill-dir>/scripts/workflow_run.py observe --json
python <skill-dir>/scripts/workflow_run.py diagnose --json
```

## Configuration

workflow no longer maintains an independent project configuration structure; all project parameters are read centrally from `.embeddedskills/config.json`.

### Configuration Structure

The `workflow` section in `.embeddedskills/config.json` contains only preferred backend configurations:

```json
{
  "workflow": {
    "preferred_build": "auto",
    "preferred_flash": "auto",
    "preferred_debug": "auto",
    "preferred_observe": "auto"
  }
}
```

workflow retrieves project parameters (e.g. `keil.project`, `eide.project`, `eide.config`, `jlink.device`, `probe-rs.chip`, etc.) by reading configuration sections of other skills in `.embeddedskills/config.json`.

### Parameter Resolution Order

Evaluated in order according to the following decision tree, stopping upon first match:

1. **CLI Arguments** (Highest priority)
   - Condition: User passes parameters like `--build-backend`, `--flash-backend` on the command line
   - Example: `workflow_run.py build-flash --build-backend=keil --flash-backend=jlink`
   - Allowed `--build-backend` values: `auto` / `keil` / `gcc` / `eide`
   - Behavior: Uses the specified backend directly, skipping subsequent steps

2. **Configuration File** (Secondary priority)
   - Condition: Not specified via CLI, and the corresponding `preferred_*` field in the `workflow` section of `.embeddedskills/config.json` is not `"auto"`
   - Example: `"preferred_build": "keil"` → Uses keil as build backend
   - Behavior: Reads and uses the configured value, skipping auto-discovery

3. **Auto Discovery** (Fallback)
   - Condition: Not specified via CLI, and `preferred_*` in configuration is `"auto"` or missing
   - Example: `"preferred_flash": "auto"` → Scans workspace to infer available flash backends
   - Behavior: Enumerates candidate backend list; uses directly if unique, or returns candidate list for user confirmation if multiple

After successful execution, the practically used backend is automatically written back to the `workflow` section of `.embeddedskills/config.json`.

## Rules

- If multiple projects or multiple candidate backends are discovered, return the candidate list without guessing
- Build, flash, debug, and observe stages chain primarily via `.embeddedskills/state.json`
- `observe` only generates recommended commands and does not hold observation channels open long-term within workflow
- On failure, report which stage failed along with structured errors from underlying scripts
- Workflow inter-skill coordination operates exclusively via `.embeddedskills/config.json`, `.embeddedskills/state.json`, and invoking underlying skill scripts as subprocesses
