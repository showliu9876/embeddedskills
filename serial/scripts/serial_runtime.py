"""Serial skill private runtime utilities."""

from __future__ import annotations

import json
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parent.parent
SKILL_NAME = "serial"
STATE_DIR_NAME = ".embeddedskills"
STATE_FILE_NAME = "state.json"
PROJECT_CONFIG_FILE = "config.json"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def is_missing(value: Any) -> bool:
    return value is None or value == ""


def load_json_file(path: str | Path) -> dict:
    """Load JSON file, return empty dict if it does not exist."""
    file_path = Path(path)
    if not file_path.exists():
        return {}
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_json_file(path: str | Path, data: dict) -> None:
    """Save JSON file, automatically creating parent directories."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_local_config() -> dict:
    """Load skill/config.json (environment-level configuration)."""
    return load_json_file(SKILL_DIR / "config.json")


def save_local_config(data: dict) -> None:
    """Save environment-level configuration to skill/config.json."""
    save_json_file(SKILL_DIR / "config.json", data)


def workspace_root(workspace: str | None = None) -> Path:
    if not is_missing(workspace):
        return Path(str(workspace)).expanduser().resolve()
    return Path.cwd().resolve()


def load_project_config(workspace: str | None = None) -> dict:
    """Read project-level configuration for this skill from workspace/.embeddedskills/config.json."""
    proj_config = load_json_file(workspace_root(workspace) / STATE_DIR_NAME / PROJECT_CONFIG_FILE)
    return proj_config.get(SKILL_NAME, {})


def save_project_config(workspace: str | None = None, values: dict | None = None) -> None:
    """Write back project-level configuration, updating only this skill's section."""
    if values is None:
        return
    proj_path = workspace_root(workspace) / STATE_DIR_NAME / PROJECT_CONFIG_FILE
    proj_config = load_json_file(proj_path)
    proj_config[SKILL_NAME] = {**proj_config.get(SKILL_NAME, {}), **values}
    save_json_file(proj_path, proj_config)


def load_workspace_state(workspace: str | None = None) -> dict:
    """Read state from workspace/.embeddedskills/state.json."""
    return load_json_file(workspace_root(workspace) / STATE_DIR_NAME / STATE_FILE_NAME)


def save_workspace_state(state: dict, workspace: str | None = None) -> Path:
    """Save state."""
    ws = workspace_root(workspace)
    file_path = ws / STATE_DIR_NAME / STATE_FILE_NAME
    save_json_file(file_path, _serialize_state_value(state, ws))
    return file_path


def update_state_entry(category: str, record: dict, workspace: str | None = None) -> dict:
    """Update state entry."""
    ws = workspace_root(workspace)
    state = load_workspace_state(workspace)
    state[category] = _serialize_state_value({**record, "timestamp": record.get("timestamp") or now_iso()}, ws)
    file_path = save_workspace_state(state, workspace)
    return {
        "workspace": str(ws),
        "file": str(file_path),
        "updated_keys": [category],
        category: state[category],
    }


def normalize_path(value: str | None, base: str | Path | None = None) -> str:
    """Normalize path."""
    if is_missing(value):
        return ""
    path = Path(str(value)).expanduser()
    if base and not path.is_absolute():
        path = Path(base) / path
    return str(path.resolve()) if path.is_absolute() else str(path)


def _serialize_state_value(value: Any, workspace: Path) -> Any:
    if isinstance(value, dict):
        return {key: _serialize_state_value(item, workspace) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_state_value(item, workspace) for item in value]
    if not isinstance(value, str) or "://" in value:
        return value

    path = Path(value).expanduser()
    if not path.is_absolute():
        return value
    try:
        return Path(os.path.relpath(path.resolve(), workspace)).as_posix()
    except ValueError:
        return value


def _first_resolved(mapping: dict, keys: list[str]) -> tuple[Any, str | None]:
    for key in keys:
        value = mapping.get(key)
        if not is_missing(value):
            return value, key
    return None, None


def resolve_param(
    name: str,
    cli_value: Any = None,
    local_config: dict | None = None,
    local_keys: list[str] | None = None,
    project_config: dict | None = None,
    project_keys: list[str] | None = None,
    state: dict | None = None,
    state_keys: list[str] | None = None,
    default: Any = None,
) -> tuple[Any, str]:
    """Unified parameter resolution, priority: CLI > environment-level > project-level > state > default."""
    if not is_missing(cli_value):
        return cli_value, "cli"

    if local_config and local_keys:
        value, key = _first_resolved(local_config, local_keys)
        if not is_missing(value):
            return value, f"local:{key}"

    if project_config and project_keys:
        value, key = _first_resolved(project_config, project_keys)
        if not is_missing(value):
            return value, f"project:{key}"

    if state and state_keys:
        value, key = _first_resolved(state, state_keys)
        if not is_missing(value):
            return value, f"state:{key}"

    if not is_missing(default):
        return default, "default"

    return None, ""


def parameter_context(name: str, value: Any, source: str) -> dict:
    """Record parameter source."""
    return {"name": name, "value": value, "source": source}


def make_result(
    success: bool = True,
    action: str = "",
    summary: str = "",
    details: dict | None = None,
    error: dict | None = None,
) -> dict:
    """Unified result format."""
    result = {
        "status": "ok" if success else "error",
        "action": action,
        "summary": summary,
    }
    if details:
        result["details"] = details
    if error:
        result["error"] = error
    return result


def make_timing(start_time: float) -> dict:
    """Execution timing record."""
    elapsed = datetime.now().timestamp() - start_time
    return {
        "started_at": datetime.fromtimestamp(start_time).astimezone().isoformat(timespec="seconds"),
        "finished_at": now_iso(),
        "elapsed_ms": int(elapsed * 1000),
    }


def scan_serial_ports(filter_keyword: str | None = None) -> tuple[list[dict], str | None]:
    """Scan system serial ports, returning (ports, error)."""
    try:
        from serial.tools.list_ports import comports
    except ImportError:
        return [], "pyserial is not installed, please run: pip install pyserial"

    # Load VID/PID -> chip name mapping
    chip_map = {}
    try:
        common_devices_path = SKILL_DIR / "references" / "common_devices.json"
        data = json.loads(common_devices_path.read_text(encoding="utf-8"))
        for entry in data.get("usb_serial_chips", []):
            key = (entry["vid"].upper(), entry["pid"].upper())
            chip_map[key] = entry["name"]
    except Exception:
        pass

    ports = []
    for p in sorted(comports(), key=lambda x: x.device):
        vid = f"{p.vid:04X}" if p.vid else ""
        pid = f"{p.pid:04X}" if p.pid else ""
        chip_name = chip_map.get((vid, pid), "")

        info = {
            "port": p.device,
            "description": p.description or "",
            "vid": vid,
            "pid": pid,
            "chip": chip_name,
            "serial_number": p.serial_number or "",
            "location": p.location or "",
        }

        if filter_keyword:
            text = " ".join(str(v) for v in info.values()).lower()
            if filter_keyword.lower() not in text:
                continue

        ports.append(info)

    return ports, None


def get_serial_config(
    cli_port: str | None = None,
    cli_baudrate: int | None = None,
    cli_bytesize: int | None = None,
    cli_parity: str | None = None,
    cli_stopbits: int | None = None,
    cli_encoding: str | None = None,
    cli_timeout: float | None = None,
    workspace: str | None = None,
) -> tuple[dict, dict]:
    """
    Get serial port configuration, resolving parameters by priority.
    Returns (config_dict, sources_dict).
    """
    local_cfg = load_local_config()
    proj_cfg = load_project_config(workspace)
    state = load_workspace_state(workspace)

    sources = {}

    # Resolve individual parameters
    port, src = resolve_param(
        "port", cli_port,
        project_config=proj_cfg, project_keys=["port"],
        state=state, state_keys=["last_serial_port"],
    )
    sources["port"] = src or "unknown"

    baudrate, src = resolve_param(
        "baudrate", cli_baudrate,
        project_config=proj_cfg, project_keys=["baudrate"],
        state=state, state_keys=["last_baudrate"],
        default=115200,
    )
    sources["baudrate"] = src or "default"

    bytesize, src = resolve_param(
        "bytesize", cli_bytesize,
        project_config=proj_cfg, project_keys=["bytesize"],
        default=8,
    )
    sources["bytesize"] = src or "default"

    parity, src = resolve_param(
        "parity", cli_parity,
        project_config=proj_cfg, project_keys=["parity"],
        default="none",
    )
    sources["parity"] = src or "default"

    stopbits, src = resolve_param(
        "stopbits", cli_stopbits,
        project_config=proj_cfg, project_keys=["stopbits"],
        default=1,
    )
    sources["stopbits"] = src or "default"

    encoding, src = resolve_param(
        "encoding", cli_encoding,
        project_config=proj_cfg, project_keys=["encoding"],
        default="utf-8",
    )
    sources["encoding"] = src or "default"

    timeout, src = resolve_param(
        "timeout_sec", cli_timeout,
        project_config=proj_cfg, project_keys=["timeout_sec"],
        default=1.0,
    )
    sources["timeout_sec"] = src or "default"

    # If no port specified, attempt scan
    if is_missing(port):
        ports, err = scan_serial_ports()
        if err:
            return None, {"error": err}
        if len(ports) == 1:
            # Unique candidate, automatically save to config
            port = ports[0]["port"]
            sources["port"] = "auto_scan"
            save_project_config(workspace, {"port": port})
        elif len(ports) > 1:
            return None, {
                "error": "Found multiple serial ports, please specify one",
                "candidates": ports,
                "need_selection": True,
            }
        else:
            return None, {"error": "No available serial ports found"}

    log_dir, src = resolve_param(
        "log_dir", None,
        project_config=proj_cfg, project_keys=["log_dir"],
        default=".embeddedskills/logs/serial",
    )
    sources["log_dir"] = src or "default"

    config = {
        "port": port,
        "baudrate": baudrate,
        "bytesize": bytesize,
        "parity": parity,
        "stopbits": stopbits,
        "encoding": encoding,
        "timeout_sec": timeout,
        "log_dir": log_dir,
    }

    return config, sources


def is_mux_alive(mux_info: dict) -> bool:
    """Check if mux processes are alive."""
    for pid_key in ("tcp_pid", "pty_pid"):
        pid = mux_info.get(pid_key, 0)
        if not pid:
            return False
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return False
    return True


def get_mux_info(workspace: str | None = None) -> dict | None:
    """Get running mux connection information, or None if not running."""
    state = load_workspace_state(workspace)
    mux_info = state.get("serial_mux")
    if not mux_info:
        return None
    if not is_mux_alive(mux_info):
        state.pop("serial_mux", None)
        save_workspace_state(state, workspace)
        return None
    return mux_info


def _normalize_serial_port(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    if os.name == "nt":
        return os.path.normcase(text)
    if text.startswith("/"):
        return os.path.realpath(text)
    return text


def config_matches_mux(config: dict, mux_info: dict) -> bool:
    """Verify that current serial config and running mux point to the same serial port."""
    if _normalize_serial_port(config.get("port")) != _normalize_serial_port(mux_info.get("real_port")):
        return False

    checks = (
        ("baudrate", 115200),
        ("bytesize", 8),
        ("parity", "none"),
        ("stopbits", 1),
    )
    for key, default in checks:
        if str(config.get(key, default)).lower() != str(mux_info.get(key, default)).lower():
            return False
    return True


def get_matching_mux_info(config: dict, workspace: str | None = None) -> dict | None:
    """Return mux info only when mux matches the resolved serial configuration."""
    mux_info = get_mux_info(workspace)
    if mux_info and config_matches_mux(config, mux_info):
        return mux_info
    return None


def open_serial_port(config: dict, use_mux: bool = True):
    """Open serial port connection according to configuration.

    When mux is running and serial configuration matches, automatically connects
    to the TCP port via socket:// to allow concurrent serial access with minicom.
    When use_mux=False, skips mux detection and directly opens the real serial port.
    """
    import serial

    if use_mux:
        mux = get_matching_mux_info(config)
        if mux:
            url = f"socket://127.0.0.1:{mux['tcp_port']}"
            ser = serial.serial_for_url(url)
            ser.timeout = config.get("timeout_sec", 1.0)
            setattr(ser, "_serial_skill_using_mux", True)
            return ser

    PARITY_MAP = {"none": "N", "even": "E", "odd": "O", "mark": "M", "space": "S"}
    parity = PARITY_MAP.get(config.get("parity", "none"), "N")

    return serial.Serial(
        port=config["port"],
        baudrate=config["baudrate"],
        bytesize=config["bytesize"],
        parity=parity,
        stopbits=config["stopbits"],
        timeout=config["timeout_sec"],
    )


def output_json(data: dict, *, indent: int = 2) -> None:
    """Output JSON to stdout."""
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=indent), flush=True)

