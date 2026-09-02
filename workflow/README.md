# Workflow

`workflow` is a thin orchestration layer responsible solely for:

- Discovering Keil / GCC / EIDE projects in the current workspace
- Selecting build, flash, debug, and observe backends
- Chaining `.embeddedskills/state.json`
- Aggregating underlying script outputs

The current `observe` phase returns candidate observation backends: `jlink:rtt`, `jlink:swo`, `openocd:semihosting`, `openocd:itm`, and `probe-rs:rtt`.

It does not rewrite underlying builders, flashers, or GDB parsing logic.

## Commands

```bash
python workflow/scripts/workflow_plan.py --json
python workflow/scripts/workflow_run.py plan --json
python workflow/scripts/workflow_run.py build --json
python workflow/scripts/workflow_run.py build-flash --json
python workflow/scripts/workflow_run.py build-debug --json
python workflow/scripts/workflow_run.py observe --json
python workflow/scripts/workflow_run.py diagnose --json
```

## Configuration

workflow no longer maintains an independent project configuration structure; all project parameters are read centrally from `.embeddedskills/config.json`.

### Shared Project-Level Configuration

In `.embeddedskills/config.json`, the `workflow` section contains only preferred backend configurations:

```json
{
  "workflow": {
    "preferred_build": "auto",
    "preferred_flash": "auto",
    "preferred_debug": "auto",
    "preferred_observe": "auto"
  },
  "keil": { "project": "...", "target": "..." },
  "gcc": { "project": "...", "preset": "..." },
  "eide": { "project": "...", "config": "..." },
  "jlink": { "device": "...", "interface": "SWD" },
  "openocd": { "board": "...", "interface": "..." },
  "probe-rs": { "chip": "...", "protocol": "swd" }
}
```

### Parameter Resolution Order

1. **CLI Arguments** (e.g. `--build-backend=keil`) take highest priority
2. **`workflow` section** in `.embeddedskills/config.json`
3. **Auto-discovery** (when `preferred_*` is set to `"auto"`)

After successful execution, the practically used backend is automatically written back to the `workflow` section of `.embeddedskills/config.json` for future invocations.

### Coordination with Other Skills

workflow coordinates with other skills exclusively via:
- `.embeddedskills/config.json`: reading each skill's project configuration
- `.embeddedskills/state.json`: reading and writing runtime states
- Subprocesses invoking underlying skill scripts
