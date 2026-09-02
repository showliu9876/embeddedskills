# Embedded Skill Reference Template

## 1. Common Characteristics of These Skills

Although targeting different tools, skills in this repository converge on the same implementation model:

### 1.1 Three-Layer Configuration + PATH

Jointly resolving runtime environment across these layers:

1. CLI explicit arguments
2. `skill/config.json`
3. `<workspace>/.embeddedskills/config.json`
4. `<workspace>/.embeddedskills/state.json`
5. System `PATH`
6. Default values

Key principles:

- Tool paths prioritize: `CLI > skill/config.json > PATH > default command name`
- Project parameters prioritize: `CLI > .embeddedskills/config.json > state.json > default / error`
- Artifact paths prioritize: `CLI > .embeddedskills/config.json > state.json > default / error`

### 1.2 Unified Runtime Layer

Most skills include a `*_runtime.py` responsible for:

- Reading/writing environment-level config
- Reading/writing project-level config
- Reading/writing state files
- Normalizing paths
- Standardizing result outputs
- Tracking parameter sources
- Parameter resolution helpers

Typical common functions:

- `load_local_config`
- `load_project_config`
- `save_project_config`
- `load_workspace_state`
- `update_state_entry`
- `resolve_tool_param`
- `resolve_project_param`
- `resolve_runtime_param`
- `resolve_artifact_param`
- `make_result`
- `make_timing`
- `parameter_context`

### 1.3 Unified Result Format

Almost all scripts return structured JSON with consistent core fields:

```json
{
  "status": "ok",
  "action": "build",
  "summary": "Execution successful",
  "details": {},
  "context": {},
  "artifacts": {},
  "metrics": {},
  "state": {},
  "timing": {}
}
```

Streaming output commands additionally use JSON Lines with:

- `source`
- `channel_type`
- `stream_type`
- `timestamp`

### 1.4 Separation of Project Configuration and State

Common constraints:

- `.embeddedskills/config.json` stores "long-term reusable project defaults"
- `.embeddedskills/state.json` stores "run records of the most recent successful execution"
- Upon success, usually:
  - Writes confirmed project parameters back to `.embeddedskills/config.json`
  - Writes most recent execution info back to `.embeddedskills/state.json`

### 1.5 Clear Entry Script Responsibilities

Each entry script basically follows the same steps:

1. Parse CLI arguments
2. Load local config, project config, and state
3. Resolve parameters using runtime helpers
4. Validate required arguments
5. Invoke underlying tools
6. Parse output
7. Write back config/state
8. Return standard JSON

### 1.6 Consistent Documentation Structure

Each skill typically contains:

- `SKILL.md`
- `README.md`
- `config.example.json`
- `scripts/`
- `references/`
- `templates/` (if needed)

---

## 2. Recommended Directory Structure

When adding a new skill, it is recommended to directly use this directory skeleton:

```text
your-skill/
├── SKILL.md
├── README.md
├── config.example.json
├── scripts/
│   ├── your_skill_runtime.py
│   ├── your_skill_exec.py
│   ├── your_skill_scan.py
│   └── your_skill_observe.py
├── references/
│   └── common_devices.json
└── templates/
    └── sample.txt
```

Notes:

- `runtime.py` is mandatory
- `exec.py` handles main command entries
- `scan.py` handles discovery/scanning
- Split other scripts by scenario; do not stuff all logic into one file

---

## 3. runtime.py Template

Below is the recommended skeleton, a minimal version converged from the repository's mainstream implementations:

```python
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


STATE_DIR_NAME = ".embeddedskills"
STATE_FILE_NAME = "state.json"
PROJECT_CONFIG_FILE_NAME = "config.json"
SKILL_NAME = "your-skill"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def is_missing(value: Any) -> bool:
    return value is None or value == ""


def default_config_path(script_file: str) -> Path:
    return Path(script_file).resolve().parents[1] / "config.json"


def load_json_file(path: str | Path) -> dict:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_json_file(path: str | Path, data: dict) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def workspace_root(workspace: str | None = None) -> Path:
    if not is_missing(workspace):
        return Path(str(workspace)).expanduser().resolve()
    return Path.cwd().resolve()


def normalize_path(value: str | None) -> str:
    if is_missing(value):
        return ""
    return str(Path(str(value)).expanduser().resolve())


def load_local_config(script_file: str | None = None) -> dict:
    if not script_file:
        return {}
    return load_json_file(default_config_path(script_file))


def load_project_config(workspace: str | None = None) -> dict:
    ws = workspace_root(workspace)
    config_file = ws / STATE_DIR_NAME / PROJECT_CONFIG_FILE_NAME
    data = load_json_file(config_file)
    return data.get(SKILL_NAME, {})


def save_project_config(workspace: str | None = None, values: dict | None = None) -> None:
    if values is None:
        values = {}
    ws = workspace_root(workspace)
    config_file = ws / STATE_DIR_NAME / PROJECT_CONFIG_FILE_NAME
    data = load_json_file(config_file)
    data[SKILL_NAME] = {**(data.get(SKILL_NAME, {})), **values}
    save_json_file(config_file, data)


def load_workspace_state(workspace: str | None = None) -> dict:
    return load_json_file(workspace_root(workspace) / STATE_DIR_NAME / STATE_FILE_NAME)


def save_workspace_state(state: dict, workspace: str | None = None) -> Path:
    file_path = workspace_root(workspace) / STATE_DIR_NAME / STATE_FILE_NAME
    save_json_file(file_path, state)
    return file_path


def get_state_entry(state: dict | None, key: str) -> dict:
    if not isinstance(state, dict):
        return {}
    value = state.get(key, {})
    return value if isinstance(value, dict) else {}


def update_state_entry(category: str, record: dict, workspace: str | None = None) -> dict:
    state = load_workspace_state(workspace)
    state[category] = {**record, "timestamp": record.get("timestamp") or now_iso()}
    file_path = save_workspace_state(state, workspace)
    return {
        "workspace": str(workspace_root(workspace)),
        "file": str(file_path),
        "updated_keys": [category],
        category: state[category],
    }


def _first_resolved(mapping: dict, keys: list[str]) -> tuple[Any, str | None]:
    for key in keys:
        value = mapping.get(key)
        if not is_missing(value):
            return value, key
    return None, None


def normalize_command_value(value: str | None) -> str:
    if is_missing(value):
        return ""
    candidate = str(value).strip()
    expanded = Path(candidate).expanduser()
    if expanded.exists():
        return str(expanded.resolve())
    resolved = shutil.which(candidate)
    if resolved:
        return normalize_path(resolved)
    return candidate


def resolve_path_candidate(candidates: list[str] | tuple[str, ...] | None) -> tuple[str, str]:
    for candidate in candidates or []:
        if is_missing(candidate):
            continue
        resolved = shutil.which(str(candidate))
        if resolved:
            return normalize_path(resolved), f"path:{candidate}"
    return "", ""


def resolve_tool_param(name: str, cli_value: Any, *, local_config: dict | None = None, local_keys: list[str] | None = None, path_candidates: list[str] | tuple[str, ...] | None = None, default: Any = None, required: bool = False) -> tuple[Any, str]:
    if not is_missing(cli_value):
        value = normalize_command_value(str(cli_value))
        source = "cli"
    else:
        value = None
        source = ""
        if local_config and local_keys:
            value, key = _first_resolved(local_config, local_keys)
            if not is_missing(value):
                value = normalize_command_value(str(value))
                source = f"config:{key}"
        if is_missing(value):
            value, source = resolve_path_candidate(path_candidates)
        if is_missing(value) and not is_missing(default):
            value = default
            source = f"default:{default}" if isinstance(default, str) else "default"
    if required and is_missing(value):
        raise ValueError(f"Missing required parameter: {name}")
    return value, source


def resolve_project_param(name: str, cli_value: Any, *, project_config: dict | None = None, project_keys: list[str] | None = None, state_record: dict | None = None, state_keys: list[str] | None = None, default: Any = None, required: bool = False, normalize_as_path: bool = False) -> tuple[Any, str]:
    if not is_missing(cli_value):
        value = cli_value
        source = "cli"
    else:
        value = None
        source = ""
        if project_config and project_keys:
            value, key = _first_resolved(project_config, project_keys)
            if not is_missing(value):
                source = f"project_config:{key}"
        if is_missing(value) and state_record and state_keys:
            value, key = _first_resolved(state_record, state_keys)
            if not is_missing(value):
                source = f"state:{key}"
        if is_missing(value) and not is_missing(default):
            value = default
            source = "default"
    if normalize_as_path and not is_missing(value):
        value = normalize_path(str(value))
    if required and is_missing(value):
        raise ValueError(f"Missing required parameter: {name}")
    return value, source


def resolve_runtime_param(name: str, cli_value: Any, *, project_config: dict | None = None, project_keys: list[str] | None = None, local_config: dict | None = None, local_keys: list[str] | None = None, state_record: dict | None = None, state_keys: list[str] | None = None, default: Any = None, required: bool = False, normalize_as_path: bool = False) -> tuple[Any, str]:
    if not is_missing(cli_value):
        value = cli_value
        source = "cli"
    else:
        value = None
        source = ""
        if project_config and project_keys:
            value, key = _first_resolved(project_config, project_keys)
            if not is_missing(value):
                source = f"project_config:{key}"
        if is_missing(value) and local_config and local_keys:
            value, key = _first_resolved(local_config, local_keys)
            if not is_missing(value):
                source = f"config:{key}"
        if is_missing(value) and state_record and state_keys:
            value, key = _first_resolved(state_record, state_keys)
            if not is_missing(value):
                source = f"state:{key}"
        if is_missing(value) and not is_missing(default):
            value = default
            source = "default"
    if normalize_as_path and not is_missing(value):
        value = normalize_path(str(value))
    if required and is_missing(value):
        raise ValueError(f"Missing required parameter: {name}")
    return value, source


def resolve_artifact_param(name: str, cli_value: Any, **kwargs) -> tuple[Any, str]:
    return resolve_project_param(name, cli_value, **kwargs)


def compact_dict(data: dict | None) -> dict:
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if v not in (None, "", [], {})}


def make_result(*, status: str, action: str, summary: str, details: dict | None = None, context: dict | None = None, artifacts: dict | None = None, metrics: dict | None = None, state: dict | None = None, timing: dict | None = None, error: dict | None = None) -> dict:
    result = {
        "status": status,
        "action": action,
        "summary": summary,
        "details": compact_dict(details),
    }
    if context:
        result["context"] = compact_dict(context)
    if artifacts:
        result["artifacts"] = compact_dict(artifacts)
    if metrics:
        result["metrics"] = compact_dict(metrics)
    if state:
        result["state"] = compact_dict(state)
    if timing:
        result["timing"] = compact_dict(timing)
    if error:
        result["error"] = compact_dict(error)
    return result


def make_timing(started_at: str, elapsed_ms: int | float) -> dict:
    return {"started_at": started_at, "finished_at": now_iso(), "elapsed_ms": int(elapsed_ms)}


def parameter_context(*, provider: str, workspace: str | None = None, parameter_sources: dict | None = None, config_path: str | None = None) -> dict:
    context = {"provider": provider, "workspace": str(workspace_root(workspace))}
    if parameter_sources:
        context["parameter_sources"] = compact_dict(parameter_sources)
    if not is_missing(config_path):
        context["config_path"] = normalize_path(str(config_path))
    return context
```

---

## 4. Main Entry Script Template

It is recommended to organize each entry script in this order:

```python
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from your_skill_runtime import (
    default_config_path,
    is_missing,
    load_json_file,
    load_local_config,
    load_project_config,
    load_workspace_state,
    make_result,
    make_timing,
    normalize_path,
    now_iso,
    output_json,
    parameter_context,
    resolve_artifact_param,
    resolve_project_param,
    resolve_runtime_param,
    resolve_tool_param,
    save_project_config,
    update_state_entry,
    workspace_root,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="your-skill main entry")
    parser.add_argument("action")
    parser.add_argument("--exe", default=None)
    parser.add_argument("--workspace", default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    started_at = now_iso()
    started_ts = time.time()
    workspace = workspace_root(args.workspace)
    config_path = normalize_path(args.config or str(default_config_path(__file__)))
    local_config = load_json_file(config_path)
    project_config = load_project_config(str(workspace))
    state = load_workspace_state(str(workspace))

    parameter_sources: dict[str, str] = {}
    try:
        exe, parameter_sources["exe"] = resolve_tool_param(
            "exe",
            args.exe,
            local_config=local_config,
            local_keys=["exe"],
            path_candidates=["tool", "tool.exe"],
            default="tool",
            required=True,
        )
    except ValueError as exc:
        result = make_result(
            status="error",
            action=args.action,
            summary=str(exc),
            context=parameter_context(
                provider="your-skill",
                workspace=str(workspace),
                parameter_sources=parameter_sources,
                config_path=config_path,
            ),
            error={"code": "missing_param", "message": str(exc)},
            timing=make_timing(started_at, (time.time() - started_ts) * 1000),
        )
        if args.as_json:
            output_json(result)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Execute tool invocation here
    raw_result = {"status": "ok", "summary": "Execution successful", "details": {"exe": exe}}

    if raw_result["status"] == "ok":
        save_project_config(str(workspace), {"some_confirmed_param": "value"})
        state_info = update_state_entry("last_action", {"action": args.action}, str(workspace))
        result = make_result(
            status="ok",
            action=args.action,
            summary=raw_result["summary"],
            details=raw_result.get("details"),
            context=parameter_context(
                provider="your-skill",
                workspace=str(workspace),
                parameter_sources=parameter_sources,
                config_path=config_path,
            ),
            state=state_info,
            timing=make_timing(started_at, (time.time() - started_ts) * 1000),
        )
    else:
        result = make_result(
            status="error",
            action=args.action,
            summary=raw_result["summary"],
            context=parameter_context(
                provider="your-skill",
                workspace=str(workspace),
                parameter_sources=parameter_sources,
                config_path=config_path,
            ),
            error=raw_result.get("error"),
            timing=make_timing(started_at, (time.time() - started_ts) * 1000),
        )

    if args.as_json:
        output_json(result)
    else:
        print(result["summary"])


if __name__ == "__main__":
    main()
```

---

## 5. config.example.json Template

### Environment-level Configuration

```json
{
  "exe": "tool",
  "gdb_exe": "/usr/bin/arm-none-eabi-gdb",
  "log_dir": "",
  "operation_mode": 1
}
```

Recommendations:

- Only place tool paths and local machine configs here
- Do not place project truth parameters here

### Project-level Configuration Example

```json
{
  "your-skill": {
    "project": "",
    "device": "",
    "interface": "",
    "speed": "",
    "log_dir": ".embeddedskills/logs/your-skill"
  }
}
```

---

## 6. SKILL.md Template

```md
---
name: your-skill
description: One-line description of capabilities
---

# your-skill

## Usage

Explain what this skill does.

## Configuration

### Environment-level Configuration (skill/config.json)

Used for tool paths and local machine parameters.

### Project-level Configuration (.embeddedskills/config.json)

Used for project default parameters.

### State File (.embeddedskills/state.json)

Used to save the most recent successful execution record.

## Parameter Resolution Precedence

- Tool paths: `CLI > skill/config.json > PATH > Default values`
- Project parameters: `CLI > .embeddedskills/config.json > state.json > Default values / Error`
- Artifact paths: `CLI > .embeddedskills/config.json > state.json > Default values / Error`

## Subcommands

### scan

```bash
python <skill-dir>/scripts/your_skill_scan.py --json
```

### exec

```bash
python <skill-dir>/scripts/your_skill_exec.py action --json
```

## Return Format

All scripts return JSON with base fields:

- `status`
- `action`
- `summary`
- `details`
- `context`
- `timing`

## Rules

- Do not automatically guess when key parameters are missing
- Single candidate can be auto-discovered and written back to project config
- Update `.embeddedskills/config.json` and `state.json` after successful execution
```

---

## 7. Minimal Checklist for Creating a New Skill

Before adding a new skill, confirm at least these items:

- Whether there is an independent `runtime.py`
- Whether environment-level config, project-level config, and state files are properly separated
- Whether system `PATH` is proactively probed
- Whether JSON output is standardized
- Whether config/state is written back upon success
- Whether parameter precedence is clearly documented in `SKILL.md`
- Whether writing local machine absolute paths into project config is avoided

---

## 8. Scenarios Suitable for Direct Reuse

This template is best suited for the following new skills:

- New flash backends
- New debugger backends
- New serial / CAN / network observation backends
- New build backends
- Any "CLI tool wrapper + project state management" skill

If it is a pure orchestration layer, refer to `workflow`; if it is a pure observation layer, refer to `serial / net / can`; if it is an integrated "build + artifact + debug" skill, refer to `gcc / keil / jlink / openocd / probe-rs`.
