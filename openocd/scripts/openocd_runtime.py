"""openocd skill private runtime utilities."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from shutil import which
from typing import Any


STATE_DIR_NAME = ".embeddedskills"
STATE_FILE_NAME = "state.json"
PROJECT_CONFIG_FILE_NAME = "config.json"
SKILL_NAME = "openocd"

# Command names, Linux first, Windows names kept as fallback.
OPENOCD_CANDIDATES = ("openocd", "openocd.exe")
ARM_GDB_CANDIDATES = ("arm-none-eabi-gdb", "gdb-multiarch", "arm-none-eabi-gdb.exe")

# Standard OpenOCD script directories on Linux distributions.
OPENOCD_SCRIPTS_DIRS = (
    "/usr/share/openocd/scripts",
    "/usr/local/share/openocd/scripts",
    "/usr/share/openocd",
)


def resolve_path_candidate(candidates: tuple[str, ...] | list[str] | None) -> tuple[str, str]:
    """Probe PATH for the first available candidate command name."""
    for candidate in candidates or []:
        if not candidate:
            continue
        resolved = which(str(candidate))
        if resolved:
            return resolved, f"path:{candidate}"
    return "", ""


def resolve_openocd_scripts_dir() -> tuple[str, str]:
    """Locate the OpenOCD script tree at its standard Linux install prefixes."""
    for directory in OPENOCD_SCRIPTS_DIRS:
        path = Path(directory)
        if (path / "interface").is_dir() or (path / "target").is_dir():
            return str(path), f"install_dir:{path}"
    return "", ""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def default_config_path(script_file: str) -> Path:
    return Path(script_file).resolve().parents[1] / "config.json"


def load_local_config(script_file: str = "") -> dict:
    """Load skill/config.json (environment-level configuration)."""
    if script_file:
        config_path = default_config_path(script_file)
    else:
        # Try to infer path from call stack
        import inspect

        frame = inspect.currentframe()
        if frame and frame.f_back:
            caller_file = frame.f_back.f_globals.get("__file__", "")
            if caller_file:
                config_path = default_config_path(caller_file)
            else:
                config_path = Path(__file__).resolve().parents[1] / "config.json"
        else:
            config_path = Path(__file__).resolve().parents[1] / "config.json"
    return load_json_file(config_path)


def save_local_config(data: dict, script_file: str = "") -> None:
    """Save environment-level configuration to skill/config.json."""
    if script_file:
        config_path = default_config_path(script_file)
    else:
        config_path = Path(__file__).resolve().parents[1] / "config.json"
    save_json_file(config_path, data)


def load_project_config(workspace: str | None = None) -> dict:
    """Read project-level configuration for this skill from workspace/.embeddedskills/config.json.
    Args: workspace - workspace path, uses cwd if None.
    Returns: configuration dictionary corresponding to this skill.
    """
    ws_root = workspace_root(workspace)
    project_config_path = ws_root / STATE_DIR_NAME / PROJECT_CONFIG_FILE_NAME
    full_config = load_json_file(project_config_path)
    return full_config.get(SKILL_NAME, {})


def save_project_config(workspace: str | None = None, values: dict | None = None) -> None:
    """Write back project-level configuration to workspace/.embeddedskills/config.json.
    - Only update the configuration section for this skill without overwriting other skills.
    - Automatically create .embeddedskills/ if the directory does not exist.
    - skill_name is hardcoded as "openocd" in openocd_runtime.
    """
    if values is None:
        values = {}
    ws_root = workspace_root(workspace)
    project_config_path = ws_root / STATE_DIR_NAME / PROJECT_CONFIG_FILE_NAME

    # Read existing configuration (if present)
    full_config = load_json_file(project_config_path)
    if not isinstance(full_config, dict):
        full_config = {}

    # Only update this skill's configuration section
    full_config[SKILL_NAME] = {**(full_config.get(SKILL_NAME) or {}), **values}

    save_json_file(project_config_path, full_config)


def output_json(data: dict, *, indent: int = 2) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=indent), flush=True)


def is_missing(value: Any) -> bool:
    return value is None or value == ""


def normalize_path(value: str | None) -> str:
    if is_missing(value):
        return ""
    return str(Path(str(value)).expanduser().resolve())


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


def hidden_subprocess_kwargs() -> dict:
    if sys.platform != "win32":
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


def workspace_root(workspace: str | None = None) -> Path:
    if not is_missing(workspace):
        return Path(str(workspace)).expanduser().resolve()
    return Path.cwd().resolve()


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


def resolve_param(
    name: str,
    cli_value: Any,
    *,
    config: dict | None = None,
    config_keys: list[str] | None = None,
    state_record: dict | None = None,
    state_keys: list[str] | None = None,
    required: bool = False,
    normalize_as_path: bool = False,
) -> tuple[Any, str]:
    if not is_missing(cli_value):
        value = cli_value
        source = "cli"
    else:
        value = None
        source = ""
        if config and config_keys:
            value, config_key = _first_resolved(config, config_keys)
            if not is_missing(value):
                source = f"config:{config_key}"
        if is_missing(value) and state_record and state_keys:
            value, state_key = _first_resolved(state_record, state_keys)
            if not is_missing(value):
                source = f"state:{state_key}"
        if is_missing(value) and name == "exe":
            discovered, discovered_source = resolve_path_candidate(OPENOCD_CANDIDATES)
            if discovered:
                value = discovered
                source = discovered_source
            else:
                value = "openocd"
                source = "default:openocd"
        if is_missing(value) and name == "search":
            value, source = resolve_openocd_scripts_dir()
    if normalize_as_path and not is_missing(value):
        value = normalize_path(str(value))
    if required and is_missing(value):
        raise ValueError(f"Missing required parameter: {name}")
    return value, source


def compact_dict(data: dict | None) -> dict:
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if value not in (None, "", [], {})}


def build_artifacts(**paths: str) -> dict:
    return {key: normalize_path(str(value)) for key, value in paths.items() if not is_missing(value)}


def make_result(
    *,
    status: str,
    action: str,
    summary: str,
    details: dict | None = None,
    context: dict | None = None,
    artifacts: dict | None = None,
    metrics: dict | None = None,
    state: dict | None = None,
    next_actions: list[str] | None = None,
    timing: dict | None = None,
    error: dict | None = None,
) -> dict:
    result = {"status": status, "action": action, "summary": summary, "details": compact_dict(details)}
    optional = {
        "context": compact_dict(context),
        "artifacts": compact_dict(artifacts),
        "metrics": compact_dict(metrics),
        "state": compact_dict(state),
        "timing": compact_dict(timing),
    }
    for key, value in optional.items():
        if value:
            result[key] = value
    if next_actions:
        result["next_actions"] = [item for item in next_actions if item]
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


def emit_stream_record(*, source: str, channel_type: str, text: str, as_json: bool, stream_type: str = "text", channel: int | None = None, extra: dict | None = None) -> None:
    if as_json:
        record = {
            "timestamp": now_iso(),
            "source": source,
            "channel_type": channel_type,
            "stream_type": stream_type,
            "text": text.rstrip("\r\n"),
        }
        if channel is not None:
            record["channel"] = channel
        if extra:
            record.update(compact_dict(extra))
        print(json.dumps(record, ensure_ascii=False), flush=True)
    else:
        print(text, end="" if text.endswith(("\n", "\r")) else "\n", flush=True)
