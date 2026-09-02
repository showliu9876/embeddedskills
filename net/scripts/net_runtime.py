"""Private runtime utilities for the net skill."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parent.parent
SKILL_NAME = "net"
STATE_DIR_NAME = ".embeddedskills"
STATE_FILE_NAME = "state.json"
PROJECT_CONFIG_FILE = "config.json"

# Wireshark CLI install prefixes, Linux first, Windows kept as fallback.
TOOL_INSTALL_DIRS = [
    Path("/usr/bin"),
    Path("/usr/local/bin"),
    Path("/usr/sbin"),
    Path("/snap/bin"),
    Path(r"C:\Program Files\Wireshark"),
    Path(r"C:\Program Files (x86)\Wireshark"),
]

DEFAULT_TSHARK = "tshark"
DEFAULT_CAPINFOS = "capinfos"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def is_missing(value: Any) -> bool:
    return value is None or value == ""


def decode_text(data: bytes | str | None) -> str:
    """Robustly decode command output, compatible with mixed encodings from tools on Windows."""
    if data is None:
        return ""
    if isinstance(data, str):
        return data

    for encoding in ("utf-8", "gbk", "cp1252", sys.getdefaultencoding()):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def looks_like_ipv4(value: str) -> bool:
    return bool(re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", value))


def looks_like_ip(value: str) -> bool:
    return looks_like_ipv4(value) or (":" in value and bool(re.fullmatch(r"[0-9a-fA-F:]+(?:%\d+)?", value)))


def resolve_tool_path(configured: str | None, default_name: str) -> str:
    """Resolve tool path: configuration first, then PATH, then common installation directories."""
    candidates: list[str] = []
    if configured and configured.strip():
        candidates.append(configured.strip())
    candidates.append(default_name)

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)

        expanded = str(Path(candidate).expanduser())
        if Path(expanded).exists():
            return expanded

        resolved = shutil.which(candidate)
        if resolved:
            return resolved

    for base_dir in TOOL_INSTALL_DIRS:
        for name in (default_name, f"{default_name}.exe"):
            candidate_path = base_dir / name
            if candidate_path.exists():
                return str(candidate_path)

    return configured.strip() if configured and configured.strip() else default_name


def load_json_file(path: str | Path) -> dict:
    """Load JSON file, return empty dictionary if not found."""
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
    """Load skill/config.json (environment-level config)."""
    return load_json_file(SKILL_DIR / "config.json")


def save_local_config(data: dict) -> None:
    """Save environment-level config to skill/config.json."""
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
    file_path = workspace_root(workspace) / STATE_DIR_NAME / STATE_FILE_NAME
    save_json_file(file_path, state)
    return file_path


def update_state_entry(category: str, record: dict, workspace: str | None = None) -> dict:
    """Update state entry."""
    state = load_workspace_state(workspace)
    state[category] = {**record, "timestamp": record.get("timestamp") or now_iso()}
    file_path = save_workspace_state(state, workspace)
    return {
        "workspace": str(workspace_root(workspace)),
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
    """Unified parameter resolution, priority: CLI > local > project > state > default."""
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
    """Standardized result format."""
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


def check_tshark(exe: str = "tshark") -> bool:
    """Check whether tshark is available."""
    resolved_exe = resolve_tool_path(exe, DEFAULT_TSHARK)
    try:
        result = subprocess.run([resolved_exe, "--version"], capture_output=True, text=False, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def parse_tshark_interfaces(tshark_exe: str = "tshark") -> list[dict] | None:
    """Parse tshark -D output to get capture interface list."""
    resolved_exe = resolve_tool_path(tshark_exe, DEFAULT_TSHARK)
    try:
        result = subprocess.run(
            [resolved_exe, "-D"], capture_output=True, text=False, timeout=10
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    interfaces = []
    for line in decode_text(result.stdout).splitlines():
        line = line.strip()
        if not line:
            continue
        # Format: 1. \Device\NPF_{...} (description)
        m = re.match(r"(\d+)\.\s+(.+?)(?:\s+\((.+?)\))?\s*$", line)
        if m:
            interfaces.append({
                "index": int(m.group(1)),
                "device": m.group(2).strip(),
                "description": m.group(3).strip() if m.group(3) else "",
            })
    return interfaces


def parse_ipconfig() -> list[dict]:
    """Parse ipconfig /all output to get network interface information."""
    try:
        result = subprocess.run(
            ["ipconfig", "/all"], capture_output=True, text=True, encoding="gbk", errors="replace"
        )
    except FileNotFoundError:
        return []

    interfaces = []
    current = None
    current_label = ""

    for line in result.stdout.splitlines():
        # Adapter header line
        adapter_match = re.match(r"^(\S.*?)\s*\u9002\u914d\u5668\s+(.+?)\s*[:\uff1a]", line)
        if not adapter_match:
            adapter_match = re.match(r"^(\S.*?)\s+adapter\s+(.+?)\s*[:\uff1a]", line, re.IGNORECASE)
        if adapter_match:
            if current:
                interfaces.append(current)
            current = {
                "type": adapter_match.group(1).strip(),
                "name": adapter_match.group(2).strip(),
                "description": "",
                "mac": "",
                "ipv4": "",
                "ipv4_list": [],
                "subnet": "",
                "subnet_list": [],
                "gateway": "",
                "gateway_list": [],
                "dhcp": "",
                "status": "up",
            }
            current_label = ""
            continue

        if current is None:
            continue

        line_stripped = line.strip()
        key, sep, value = line_stripped.partition(":")
        if not sep:
            key, sep, value = line_stripped.partition("\uff1a")
        key = key.strip()
        value = value.strip()
        continuation_value = value if sep else line_stripped

        if re.match(r"(\u5a92\u4f53\u72b6\u6001|Media State)", line_stripped, re.IGNORECASE):
            if "\u65ad\u5f00" in line_stripped or "disconnected" in line_stripped.lower():
                current["status"] = "down"
            current_label = ""
        elif re.match(r"(\u63cf\u8ff0|Description)", line_stripped, re.IGNORECASE):
            current["description"] = value
            current_label = ""
        elif re.match(r"(\u7269\u7406\u5730\u5740|Physical Address)", line_stripped, re.IGNORECASE):
            current["mac"] = value
            current_label = ""
        elif re.match(r"(IPv4 \u5730\u5740|IPv4 Address)", line_stripped, re.IGNORECASE):
            ipv4 = re.sub(r"\(.*?\)", "", value).strip()
            if looks_like_ipv4(ipv4):
                current["ipv4_list"].append(ipv4)
                current["ipv4"] = current["ipv4_list"][0]
            current_label = "ipv4"
        elif re.match(r"(\u5b50\u7f51\u63a9\u7801|Subnet Mask)", line_stripped, re.IGNORECASE):
            if looks_like_ipv4(value):
                current["subnet_list"].append(value)
                current["subnet"] = current["subnet_list"][0]
            current_label = "subnet"
        elif re.match(r"(\u9ed8\u8ba4\u7f51\u5173|Default Gateway)", line_stripped, re.IGNORECASE):
            if looks_like_ip(value):
                current["gateway_list"].append(value)
                current["gateway"] = current["gateway_list"][0]
            current_label = "gateway"
        elif re.match(r"DHCP", line_stripped, re.IGNORECASE) and ("\u5df2\u542f\u7528" in line_stripped or "Yes" in line_stripped):
            current["dhcp"] = "enabled"
            current_label = ""
        elif current_label == "gateway" and line.startswith(" ") and looks_like_ip(continuation_value):
            current["gateway_list"].append(continuation_value)
        elif current_label == "ipv4" and line.startswith(" ") and looks_like_ipv4(continuation_value):
            ipv4 = re.sub(r"\(.*?\)", "", continuation_value).strip()
            if ipv4:
                current["ipv4_list"].append(ipv4)
        elif current_label == "subnet" and line.startswith(" ") and looks_like_ipv4(continuation_value):
            current["subnet_list"].append(continuation_value)
        elif current_label in {"ipv4", "subnet", "gateway"} and value == "" and key:
            # Avoid misidentifying the next line as a header
            current_label = ""

    for iface in interfaces + ([current] if current else []):
        if iface["ipv4_list"] and not iface["ipv4"]:
            iface["ipv4"] = iface["ipv4_list"][0]
        if iface["subnet_list"] and not iface["subnet"]:
            iface["subnet"] = iface["subnet_list"][0]
        if iface["gateway_list"] and not iface["gateway"]:
            iface["gateway"] = iface["gateway_list"][0]

    if current:
        interfaces.append(current)

    return interfaces


def get_net_config(
    cli_interface: str | None = None,
    cli_target: str | None = None,
    cli_capture_filter: str | None = None,
    cli_display_filter: str | None = None,
    cli_duration: int | None = None,
    cli_timeout_ms: int | None = None,
    cli_scan_ports: str | None = None,
    cli_capture_format: str | None = None,
    workspace: str | None = None,
) -> tuple[dict, dict]:
    """
    Get network configuration, resolving parameters by priority.
    Returns (config_dict, sources_dict).
    """
    local_cfg = load_local_config()
    proj_cfg = load_project_config(workspace)
    state = load_workspace_state(workspace)

    sources = {}

    # Resolve individual parameters
    interface, src = resolve_param(
        "interface", cli_interface,
        project_config=proj_cfg, project_keys=["interface"],
        state=state, state_keys=["last_net_interface"],
    )
    sources["interface"] = src or "unknown"

    target, src = resolve_param(
        "target", cli_target,
        project_config=proj_cfg, project_keys=["target"],
        state=state, state_keys=["last_net_target"],
    )
    sources["target"] = src or "unknown"

    capture_filter, src = resolve_param(
        "capture_filter", cli_capture_filter,
        project_config=proj_cfg, project_keys=["capture_filter"],
        state=state, state_keys=["last_capture_filter"],
        default="",
    )
    sources["capture_filter"] = src or "default"

    display_filter, src = resolve_param(
        "display_filter", cli_display_filter,
        project_config=proj_cfg, project_keys=["display_filter"],
        state=state, state_keys=["last_display_filter"],
        default="",
    )
    sources["display_filter"] = src or "default"

    duration, src = resolve_param(
        "duration", cli_duration,
        project_config=proj_cfg, project_keys=["duration"],
        state=state, state_keys=["last_duration"],
        default=30,
    )
    sources["duration"] = src or "default"

    timeout_ms, src = resolve_param(
        "timeout_ms", cli_timeout_ms,
        project_config=proj_cfg, project_keys=["timeout_ms"],
        state=state, state_keys=["last_timeout_ms"],
        default=1000,
    )
    sources["timeout_ms"] = src or "default"

    scan_ports, src = resolve_param(
        "scan_ports", cli_scan_ports,
        project_config=proj_cfg, project_keys=["scan_ports"],
        state=state, state_keys=["last_scan_ports"],
        default="",
    )
    sources["scan_ports"] = src or "default"

    capture_format, src = resolve_param(
        "capture_format", cli_capture_format,
        project_config=proj_cfg, project_keys=["capture_format"],
        state=state, state_keys=["last_capture_format"],
        default="pcapng",
    )
    sources["capture_format"] = src or "default"

    log_dir, src = resolve_param(
        "log_dir", None,
        project_config=proj_cfg, project_keys=["log_dir"],
        default=".embeddedskills/logs/net",
    )
    sources["log_dir"] = src or "default"

    # Get tool paths (environment-level configuration)
    tshark_exe = resolve_tool_path(local_cfg.get("tshark_exe"), DEFAULT_TSHARK)
    capinfos_exe = resolve_tool_path(local_cfg.get("capinfos_exe"), DEFAULT_CAPINFOS)

    config = {
        "interface": interface,
        "target": target,
        "capture_filter": capture_filter,
        "display_filter": display_filter,
        "duration": duration,
        "timeout_ms": timeout_ms,
        "scan_ports": scan_ports,
        "capture_format": capture_format,
        "log_dir": log_dir,
        "tshark_exe": tshark_exe,
        "capinfos_exe": capinfos_exe,
    }

    return config, sources


def output_json(data: dict, *, indent: int = 2) -> None:
    """Output JSON to stdout."""
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=indent), flush=True)
