"""probe-rs basic operations and wrapper commands."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from probe_rs_runtime import (
    build_artifacts,
    default_config_path,
    get_state_entry,
    hidden_subprocess_kwargs,
    is_missing,
    load_json_file,
    load_project_config,
    load_workspace_state,
    make_result,
    make_timing,
    normalize_path,
    now_iso,
    output_json,
    parameter_context,
    resolve_probe_rs_exe,
    save_project_config,
    update_state_entry,
    workspace_root,
)


ALL_ACTIONS = ["list", "info", "flash", "erase", "reset", "read-mem", "write-mem", "attach", "run"]

ERROR_PATTERNS = [
    (r"no probes were found", "no_probe_found", "No debug probe detected. Check USB connection and driver."),
    (r"multiple probes were found", "multiple_probes", "Multiple probes detected. Specify explicitly via --probe."),
    (r"chip.*not found", "chip_not_found", "Target chip description not found. Check --chip configuration."),
    (r"failed to open probe", "probe_open_failed", "Failed to open debug probe. Check probe occupancy, driver, and USB connection."),
    (r"failed to open the debug probe", "probe_open_failed", "Failed to open debug probe. Check probe occupancy, driver, and USB connection."),
    (r"error while probing target", "probe_open_failed", "Failed to open debug probe. Check probe occupancy, driver, and USB connection."),
    (r"unexpected answer to command", "probe_protocol_error", "Unexpected response from probe. Check firmware, driver, and link stability."),
    (r"failed to attach", "attach_failed", "Failed to attach to target. Check power supply, wiring, and chip model."),
    (r"permission denied", "permission_denied", "Permission denied accessing debug probe. Check driver and permissions."),
    (r"address.*out of bounds", "address_out_of_range", "Access address out of bounds. Check address and data width."),
    (r"timed out", "timeout", "Operation timed out. Check connection and speed configuration."),
]


def infer_binary_format(file_path: str) -> str:
    suffix = Path(file_path).suffix.lower()
    if suffix == ".bin":
        return "bin"
    if suffix in {".hex", ".ihex"}:
        return "hex"
    if suffix == ".uf2":
        return "uf2"
    return "elf"


def parse_output(text: str, action: str) -> dict:
    parsed = {"raw": text}
    for pattern, code, message in ERROR_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return {"error_code": code, "error_message": message, "raw": text}

    if action == "list":
        probes = []
        for line in text.splitlines():
            item = line.strip()
            if not item or item.lower().startswith("the following debug probes were found"):
                continue
            probes.append(item)
        if probes:
            parsed["probes"] = probes
    elif action == "read-mem":
        words = re.findall(r"\b[0-9a-fA-F]{2,16}\b", text)
        if words:
            parsed["words"] = words
    elif action == "info":
        chip_match = re.search(r"chip[:=]\s*([^\r\n]+)", text, re.IGNORECASE)
        probe_match = re.search(r"probe[:=]\s*([^\r\n]+)", text, re.IGNORECASE)
        if chip_match:
            parsed["chip"] = chip_match.group(1).strip()
        if probe_match:
            parsed["probe"] = probe_match.group(1).strip()
    return parsed


def _summary(action: str, parsed: dict, fallback: str) -> str:
    if action == "list" and parsed.get("probes"):
        return f"Found {len(parsed['probes'])} debug probe(s)"
    if action == "flash":
        return "Flash successful"
    if action == "erase":
        return "Erase successful"
    if action == "reset":
        return "Target reset"
    if action == "read-mem" and parsed.get("words"):
        return f"Read {len(parsed['words'])} memory word(s)"
    if action == "write-mem":
        return "Memory write successful"
    return fallback


def normalize_write_values(value_text: str) -> list[str]:
    values = [item.strip() for item in re.split(r"[\s,]+", value_text) if item.strip()]
    if not values:
        raise ValueError("write-mem requires --value")

    normalized: list[str] = []
    for value in values:
        lowered = value.lower()
        if lowered.startswith(("0x", "0o", "0b")):
            normalized.append(value)
            continue
        if re.fullmatch(r"[0-9a-fA-F]+", value) and (value.startswith("0") or re.search(r"[a-fA-F]", value)):
            normalized.append(f"0x{value}")
            continue
        normalized.append(value)
    return normalized


def _state_lookup(state: dict) -> dict:
    last_build = get_state_entry(state, "last_build")
    last_flash = get_state_entry(state, "last_flash")
    last_debug = get_state_entry(state, "last_debug")
    artifacts = last_build.get("artifacts", {})
    return {
        "chip": last_debug.get("chip") or last_flash.get("chip"),
        "probe": last_debug.get("probe") or last_flash.get("probe"),
        "protocol": last_debug.get("protocol") or last_flash.get("protocol"),
        "speed": last_debug.get("speed") or last_flash.get("speed"),
        "connect_under_reset": last_debug.get("connect_under_reset") or last_flash.get("connect_under_reset"),
        "elf_file": last_build.get("debug_file") or artifacts.get("debug_file"),
        "flash_file": last_build.get("flash_file") or artifacts.get("flash_file"),
    }


def resolve_probe_params(args, config: dict, project_config: dict, state_lookup: dict, workspace: str) -> tuple[dict, dict]:
    parameter_sources: dict[str, str] = {}

    exe, parameter_sources["exe"] = resolve_probe_rs_exe(args.exe, config)

    chip = args.chip
    chip_source = "cli"
    if is_missing(chip):
        chip = project_config.get("chip")
        chip_source = "project_config"
    if is_missing(chip):
        chip = state_lookup.get("chip")
        chip_source = "state"
    parameter_sources["chip"] = chip_source

    protocol = args.protocol
    protocol_source = "cli"
    if is_missing(protocol):
        protocol = project_config.get("protocol")
        protocol_source = "project_config"
    if is_missing(protocol):
        protocol = state_lookup.get("protocol")
        protocol_source = "state"
    if is_missing(protocol):
        protocol = "swd"
        protocol_source = "default"
    parameter_sources["protocol"] = protocol_source

    probe = args.probe
    probe_source = "cli"
    if is_missing(probe):
        probe = project_config.get("probe")
        probe_source = "project_config"
    if is_missing(probe):
        probe = state_lookup.get("probe")
        probe_source = "state"
    parameter_sources["probe"] = probe_source

    speed = args.speed
    speed_source = "cli"
    if is_missing(speed):
        speed = project_config.get("speed")
        speed_source = "project_config"
    if is_missing(speed):
        speed = state_lookup.get("speed")
        speed_source = "state"
    if is_missing(speed):
        speed = "4000"
        speed_source = "default"
    parameter_sources["speed"] = speed_source

    connect_under_reset = args.connect_under_reset
    connect_source = "cli" if args.connect_under_reset else ""
    if not connect_under_reset:
        value = project_config.get("connect_under_reset")
        if value is not None:
            connect_under_reset = bool(value)
            connect_source = "project_config"
    if not connect_under_reset:
        value = state_lookup.get("connect_under_reset")
        if value is not None:
            connect_under_reset = bool(value)
            connect_source = "state"
    if not connect_source:
        connect_source = "default"
    parameter_sources["connect_under_reset"] = connect_source

    file_path = args.file
    file_source = "cli"
    if is_missing(file_path) and args.action == "flash":
        file_path = state_lookup.get("flash_file")
        file_source = "state"
    if is_missing(file_path) and args.action in {"run", "attach"}:
        file_path = state_lookup.get("elf_file")
        file_source = "state"
    if not is_missing(file_path):
        file_path = normalize_path(str(file_path))
    parameter_sources["file"] = file_source

    return (
        {
            "exe": exe,
            "chip": chip,
            "protocol": protocol,
            "probe": probe,
            "speed": str(speed),
            "connect_under_reset": bool(connect_under_reset),
            "file": file_path,
            "workspace": workspace,
        },
        parameter_sources,
    )


def build_probe_args(params: dict, *, require_chip: bool = True) -> list[str]:
    args = ["--non-interactive"]
    if require_chip:
        if is_missing(params["chip"]):
            raise ValueError("Missing required parameter: chip")
        args.extend(["--chip", params["chip"]])
    if params.get("protocol"):
        args.extend(["--protocol", str(params["protocol"]).lower()])
    if params.get("probe"):
        args.extend(["--probe", params["probe"]])
    if params.get("speed"):
        args.extend(["--speed", str(params["speed"])])
    if params.get("connect_under_reset"):
        args.append("--connect-under-reset")
    return args


def build_command(action: str, params: dict, args) -> list[str]:
    exe = params["exe"]
    if action == "list":
        return [exe, "list"]
    if action == "info":
        return [exe, "info", *build_probe_args(params)]
    if action == "reset":
        return [exe, "reset", *build_probe_args(params)]
    if action == "erase":
        return [exe, "erase", *build_probe_args(params)]
    if action == "read-mem":
        return [exe, "read", *build_probe_args(params), args.width, args.address, args.length]
    if action == "write-mem":
        return [exe, "write", *build_probe_args(params), args.width, args.address, *normalize_write_values(args.value)]
    if action == "flash":
        if is_missing(params["file"]):
            raise ValueError("flash requires firmware file path via --file")
        if not os.path.isfile(params["file"]):
            raise ValueError(f"Firmware file not found: {params['file']}")
        fmt = infer_binary_format(params["file"])
        cmd = [exe, "download", *build_probe_args(params), "--binary-format", fmt]
        if args.chip_erase:
            cmd.append("--chip-erase")
        if args.verify:
            cmd.append("--verify")
        if fmt == "bin":
            if not args.address:
                raise ValueError(".bin file requires flash address via --address")
            cmd.extend(["--base-address", args.address])
        cmd.append(params["file"])
        return cmd
    if action in {"attach", "run"}:
        cmd = [exe, action, *build_probe_args(params)]
        if params.get("file"):
            cmd.append(params["file"])
        return cmd
    raise ValueError(f"Unknown action: {action}")


def run_command(action: str, cmd: list[str], duration: float = 0) -> dict:
    started = time.time()
    try:
        if action in {"attach", "run"} and duration > 0:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                **hidden_subprocess_kwargs(new_process_group=True),
            )
            time.sleep(duration)
            if proc.poll() is None:
                proc.terminate()
            stdout, stderr = proc.communicate(timeout=5)
        else:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120 if action not in {"attach", "run"} else None,
                **hidden_subprocess_kwargs(),
            )
            stdout, stderr = proc.stdout, proc.stderr
        returncode = proc.returncode
    except FileNotFoundError:
        return {"status": "error", "action": action, "error": {"code": "exe_not_found", "message": f"probe-rs not found or not in PATH: {cmd[0]}"}}
    except subprocess.TimeoutExpired:
        return {"status": "error", "action": action, "error": {"code": "timeout", "message": "probe-rs execution timed out (120s)"}}
    except Exception as exc:
        return {"status": "error", "action": action, "error": {"code": "exec_error", "message": str(exc)}}

    elapsed_ms = int((time.time() - started) * 1000)
    combined = "\n".join(part for part in (stdout, stderr) if part)
    parsed = parse_output(combined, action)
    if "error_code" in parsed:
        return {
            "status": "error",
            "action": action,
            "error": {"code": parsed["error_code"], "message": parsed["error_message"]},
            "details": {"elapsed_ms": elapsed_ms, "returncode": returncode},
        }

    status = "ok"
    if returncode != 0 and action not in {"attach", "run"}:
        status = "error"
    return {
        "status": status,
        "action": action,
        "summary": _summary(action, parsed, f"{action} complete"),
        "details": {"elapsed_ms": elapsed_ms, "returncode": returncode, **{k: v for k, v in parsed.items() if k != "raw"}, "output": combined},
        "error": None if status == "ok" else {"code": "nonzero_exit", "message": combined or f"{action} failed"},
    }


def state_payload(action: str, params: dict) -> tuple[str, dict] | None:
    payload = {
        "provider": "probe-rs",
        "action": action,
        "chip": params["chip"] or "",
        "probe": params["probe"] or "",
        "protocol": params["protocol"],
        "speed": params["speed"],
        "connect_under_reset": params["connect_under_reset"],
    }
    if action == "flash":
        payload["flash_file"] = params["file"] or ""
        payload["artifacts"] = build_artifacts(flash_file=params["file"])
        return "last_flash", payload
    if action in {"reset", "read-mem", "write-mem", "info"}:
        return "last_debug", payload
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="probe-rs basic operations wrapper")
    parser.add_argument("action", choices=ALL_ACTIONS)
    parser.add_argument("--exe", default=None, help="probe-rs executable path or command name")
    parser.add_argument("--chip", default=None, help="Target chip model")
    parser.add_argument("--protocol", default=None, choices=["swd", "jtag"], help="Debug protocol")
    parser.add_argument("--probe", default=None, help="Probe selector in VID:PID[:Serial] format")
    parser.add_argument("--speed", default=None, help="Debug speed in kHz")
    parser.add_argument("--connect-under-reset", action="store_true", help="Connect under reset")
    parser.add_argument("--file", default=None, help="Firmware or ELF file path")
    parser.add_argument("--address", default="", help="Address (for flash .bin / read-mem / write-mem)")
    parser.add_argument("--length", default="64", help="Read length")
    parser.add_argument("--value", default="", help="Value to write")
    parser.add_argument("--width", default="b32", choices=["b8", "b16", "b32", "b64"], help="Read/write bit width")
    parser.add_argument("--duration", type=float, default=0, help="Duration to run in seconds for attach/run, 0 to wait for command exit")
    parser.add_argument("--verify", action="store_true", help="Verify after flashing")
    parser.add_argument("--chip-erase", action="store_true", help="Full chip erase before flashing")
    parser.add_argument("--config", default=None, help="Path to skill config.json")
    parser.add_argument("--workspace", default=None, help="Workspace root directory, defaults to current directory")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    started_at = now_iso()
    started_ts = time.time()
    workspace = workspace_root(args.workspace)
    config_path = normalize_path(args.config or str(default_config_path(__file__)))
    config = load_json_file(config_path)
    state = load_workspace_state(str(workspace))
    state_lookup = _state_lookup(state)
    project_config = load_project_config(str(workspace))

    params, parameter_sources = resolve_probe_params(args, config, project_config, state_lookup, str(workspace))

    if args.action != "list" and is_missing(params["chip"]):
        result = make_result(
            status="error",
            action=args.action,
            summary="Missing required parameter: chip",
            context=parameter_context(provider="probe-rs", workspace=str(workspace), parameter_sources=parameter_sources, config_path=config_path),
            error={"code": "missing_chip", "message": "--chip must be provided or configured in the probe-rs section of .embeddedskills/config.json"},
            timing=make_timing(started_at, (time.time() - started_ts) * 1000),
        )
        if args.as_json:
            output_json(result)
        else:
            print(f"Error: {result['error']['message']}", file=sys.stderr)
        sys.exit(1)

    try:
        cmd = build_command(args.action, params, args)
    except ValueError as exc:
        result = make_result(
            status="error",
            action=args.action,
            summary=str(exc),
            context=parameter_context(provider="probe-rs", workspace=str(workspace), parameter_sources=parameter_sources, config_path=config_path),
            error={"code": "invalid_args", "message": str(exc)},
            timing=make_timing(started_at, (time.time() - started_ts) * 1000),
        )
        if args.as_json:
            output_json(result)
        else:
            print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    raw_result = run_command(args.action, cmd, args.duration)
    elapsed_ms = (time.time() - started_ts) * 1000
    if raw_result.get("status") == "ok":
        save_project_config(str(workspace), {
            "chip": params["chip"] or "",
            "protocol": params["protocol"],
            "probe": params["probe"] or "",
            "speed": params["speed"],
            "connect_under_reset": params["connect_under_reset"],
        })
        state_info = {}
        state_entry = state_payload(args.action, params)
        if state_entry:
            state_key, payload = state_entry
            state_info = update_state_entry(state_key, payload, str(workspace))
        result = make_result(
            status="ok",
            action=args.action,
            summary=raw_result.get("summary", f"{args.action} complete"),
            details={
                "chip": params["chip"] or "",
                "probe": params["probe"] or "",
                "protocol": params["protocol"],
                "speed": params["speed"],
                "command": cmd,
                **(raw_result.get("details") or {}),
            },
            context=parameter_context(provider="probe-rs", workspace=str(workspace), parameter_sources=parameter_sources, config_path=config_path),
            artifacts=build_artifacts(flash_file=params["file"] if args.action == "flash" else "", debug_file=params["file"] if args.action in {"attach", "run"} else ""),
            state=state_info,
            next_actions=["Can continue with gdb or rtt observation based on probe-rs"] if args.action in {"flash", "info"} else None,
            timing=make_timing(started_at, elapsed_ms),
        )
    else:
        result = make_result(
            status="error",
            action=args.action,
            summary=(raw_result.get("error") or {}).get("message", f"{args.action} failed"),
            details={
                "chip": params["chip"] or "",
                "probe": params["probe"] or "",
                "protocol": params["protocol"],
                "speed": params["speed"],
                "command": cmd,
                **(raw_result.get("details") or {}),
            },
            context=parameter_context(provider="probe-rs", workspace=str(workspace), parameter_sources=parameter_sources, config_path=config_path),
            error=raw_result.get("error"),
            timing=make_timing(started_at, elapsed_ms),
        )

    if args.as_json:
        output_json(result)
    elif result["status"] == "ok":
        print(f"[probe-rs {args.action}] {result['summary']}")
        output = result.get("details", {}).get("output", "")
        if output:
            print(output)
    else:
        print(f"[probe-rs {args.action}] failed — {result['error']['message']}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
