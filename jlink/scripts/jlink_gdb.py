"""J-Link one-shot source-level GDB debugging."""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from jlink_gdb_common import build_gdb_commands, parse_gdb_output, run_gdb_commands  # noqa: E402
from jlink_runtime import (  # noqa: E402
    ARM_GDB_CANDIDATES,
    JLINK_GDBSERVER_CANDIDATES,
    build_artifacts,
    default_config_path,
    get_state_entry,
    hidden_subprocess_kwargs,
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
    resolve_param,
    resolve_tool_param,
    save_project_config,
    update_state_entry,
    workspace_root,
)


ALL_COMMANDS = [
    "run",
    "backtrace",
    "locals",
    "break",
    "continue",
    "next",
    "step",
    "finish",
    "until",
    "frame",
    "print",
    "watch",
    "disassemble",
    "threads",
    "crash-report",
]


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("", 0))
        return sock.getsockname()[1]


def start_gdbserver(
    gdbserver_exe: str,
    device: str,
    interface: str = "SWD",
    speed: str = "4000",
    serial_no: str = "",
    gdb_port: int = 0,
) -> tuple[subprocess.Popen, int]:
    if not gdb_port:
        gdb_port = find_free_port()

    cmd = [
        gdbserver_exe,
        "-device",
        device,
        "-if",
        interface,
        "-speed",
        speed,
        "-port",
        str(gdb_port),
        "-noir",
        "-LocalhostOnly",
        "-nologtofile",
        "-singlerun",
    ]
    if serial_no:
        cmd.extend(["-select", f"USB={serial_no}"])

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **hidden_subprocess_kwargs(new_process_group=True),
    )
    return proc, gdb_port


def wait_gdbserver_ready(proc: subprocess.Popen, timeout: int = 15) -> tuple[bool, str]:
    started = time.time()
    captured: list[str] = []
    while time.time() - started < timeout:
        if proc.poll() is not None:
            captured.append(proc.stderr.read())
            return False, "\n".join(line for line in captured if line).strip()
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.1)
            continue
        captured.append(line.strip())
        if "Waiting for GDB connection" in line or "Connected to target" in line:
            return True, "\n".join(captured)
        if "Cannot connect" in line or "Could not connect" in line:
            return False, "\n".join(captured)
    return False, "\n".join(captured)


def cleanup(procs: list[subprocess.Popen]) -> None:
    for proc in procs:
        if proc and proc.poll() is None:
            try:
                if sys.platform == "win32":
                    proc.terminate()
                else:
                    proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                proc.kill()


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--gdbserver-exe", default=None, help="J-Link GDB Server path (Linux: JLinkGDBServerCLExe)")
    parser.add_argument("--gdb-exe", default=None, help="arm-none-eabi-gdb path")
    parser.add_argument("--device", default=None, help="chip model")
    parser.add_argument("--elf", default=None, help="ELF file path")
    parser.add_argument("--interface", default=None, help="debug interface")
    parser.add_argument("--speed", default=None, help="debug speed in kHz")
    parser.add_argument("--serial-no", default=None, help="probe serial number")
    parser.add_argument("--gdb-port", type=int, default=0, help="GDB port, 0 = auto")
    parser.add_argument("--config", default=None, help="skill config.json path")
    parser.add_argument("--workspace", default=None, help="workspace root, defaults to cwd")
    parser.add_argument("--json", action="store_true", dest="as_json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="J-Link GDB Server debugging")
    sub = parser.add_subparsers(dest="command")
    for name in ALL_COMMANDS:
        sub_parser = sub.add_parser(name, help=f"GDB {name}")
        add_common_args(sub_parser)
        if name == "run":
            sub_parser.add_argument("--commands", nargs="+", required=True, help="GDB command sequence")
        elif name in {"break", "frame", "print", "watch"}:
            sub_parser.add_argument("--expr", required=True, help="expression or argument")
        elif name in {"until", "disassemble"}:
            sub_parser.add_argument("--expr", default=None, help="expression or argument")
    return parser


def _state_lookup(state: dict) -> dict:
    last_build = get_state_entry(state, "last_build")
    last_flash = get_state_entry(state, "last_flash")
    last_debug = get_state_entry(state, "last_debug")
    artifacts = last_build.get("artifacts", {})
    return {
        "device": last_debug.get("device") or last_flash.get("device"),
        "elf_file": last_build.get("debug_file") or last_build.get("elf_file") or artifacts.get("debug_file"),
        "debug_file": last_build.get("debug_file") or artifacts.get("debug_file"),
        "serial_no": last_debug.get("serial_no") or last_flash.get("serial_no"),
        "interface": last_debug.get("interface") or last_flash.get("interface"),
        "speed": last_debug.get("speed") or last_flash.get("speed"),
    }


def resolve_device_params(args, project_config: dict, state_lookup: dict) -> dict:
    """Resolve device/interface/speed. Priority: CLI > project config > state.json > default"""
    # device: CLI > project config > state > error
    device = args.device
    device_source = "cli"
    if is_missing(device):
        device = project_config.get("device")
        device_source = "project_config"
    if is_missing(device):
        device = state_lookup.get("device")
        device_source = "state"

    # interface: CLI > project config > state > default SWD
    interface = args.interface
    interface_source = "cli"
    if is_missing(interface):
        interface = project_config.get("interface")
        interface_source = "project_config"
    if is_missing(interface):
        interface = state_lookup.get("interface")
        interface_source = "state"
    if is_missing(interface):
        interface = "SWD"
        interface_source = "default"

    # speed: CLI > project config > state > default 4000
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

    return {
        "device": device,
        "device_source": device_source,
        "interface": interface,
        "interface_source": interface_source,
        "speed": speed,
        "speed_source": speed_source,
    }


def _summary(command: str, parsed: dict) -> str:
    if command == "continue" and parsed.get("timed_out"):
        return "continue executed, target did not stop within the timeout window"
    if command == "backtrace" and parsed.get("frames"):
        return f"backtrace complete, frames={len(parsed['frames'])}"
    if command == "locals" and parsed.get("variables"):
        return f"locals complete, variables={len(parsed['variables'])}"
    if command == "threads" and parsed.get("threads"):
        return f"threads complete, threads={len(parsed['threads'])}"
    if command == "print" and parsed.get("value"):
        return f"print complete, value={parsed['value']}"
    return f"gdb {command} complete"


def _metrics(parsed: dict) -> dict:
    metrics: dict[str, int] = {}
    if parsed.get("frames"):
        metrics["frames"] = len(parsed["frames"])
    if parsed.get("variables"):
        metrics["variables"] = len(parsed["variables"])
    if parsed.get("registers"):
        metrics["registers"] = len(parsed["registers"])
    if parsed.get("threads"):
        metrics["threads"] = len(parsed["threads"])
    if parsed.get("disassembly"):
        metrics["instructions"] = len(parsed["disassembly"])
    return metrics


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    started_at = now_iso()
    started_ts = time.time()
    workspace = workspace_root(args.workspace)
    config_path = normalize_path(args.config or str(default_config_path(__file__)))
    config = load_json_file(config_path)
    state = load_workspace_state(str(workspace))
    state_lookup = _state_lookup(state)
    project_config = load_project_config(str(workspace))

    # Resolve device/interface/speed parameters
    dev_params = resolve_device_params(args, project_config, state_lookup)

    parameter_sources: dict[str, str] = {}
    try:
        gdbserver_exe, parameter_sources["gdbserver_exe"] = resolve_tool_param(
            "gdbserver_exe",
            args.gdbserver_exe,
            local_config=config,
            local_keys=["gdbserver_exe"],
            path_candidates=JLINK_GDBSERVER_CANDIDATES,
            required=True,
        )
        gdb_exe, parameter_sources["gdb_exe"] = resolve_tool_param(
            "gdb_exe",
            args.gdb_exe,
            local_config=config,
            local_keys=["gdb_exe"],
            path_candidates=ARM_GDB_CANDIDATES,
            install_dir_candidates=(),
            required=True,
        )
        # Resolve device from project config or state
        device = dev_params["device"]
        parameter_sources["device"] = dev_params["device_source"]
        if is_missing(device):
            raise ValueError("missing required parameter: device")

        elf_file, parameter_sources["elf"] = resolve_param(
            "elf",
            args.elf,
            config=config,
            config_keys=["default_elf"],
            state_record=state_lookup,
            state_keys=["elf_file", "debug_file"],
            normalize_as_path=True,
            workspace=str(workspace),
        )
        interface = dev_params["interface"]
        parameter_sources["interface"] = dev_params["interface_source"]
        speed = dev_params["speed"]
        parameter_sources["speed"] = dev_params["speed_source"]
        serial_no, parameter_sources["serial_no"] = resolve_param(
            "serial_no",
            args.serial_no,
            config=config,
            config_keys=["serial_no"],
            state_record=state_lookup,
            state_keys=["serial_no"],
        )
    except ValueError as exc:
        result = make_result(
            status="error",
            action=args.command,
            summary=str(exc),
            details={},
            context=parameter_context(
                provider="jlink",
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

    if not os.path.isfile(gdbserver_exe):
        message = f"J-Link GDB Server (JLinkGDBServerCLExe) not found: {gdbserver_exe}"
        result = make_result(
            status="error",
            action=args.command,
            summary=message,
            details={},
            context=parameter_context(provider="jlink", workspace=str(workspace), parameter_sources=parameter_sources, config_path=config_path),
            error={"code": "gdbserver_not_found", "message": message},
            timing=make_timing(started_at, (time.time() - started_ts) * 1000),
        )
        if args.as_json:
            output_json(result)
        else:
            print(f"Error: {message}", file=sys.stderr)
        sys.exit(1)

    if not os.path.isfile(gdb_exe):
        message = f"arm-none-eabi-gdb not found: {gdb_exe}"
        result = make_result(
            status="error",
            action=args.command,
            summary=message,
            details={},
            context=parameter_context(provider="jlink", workspace=str(workspace), parameter_sources=parameter_sources, config_path=config_path),
            error={"code": "gdb_not_found", "message": message},
            timing=make_timing(started_at, (time.time() - started_ts) * 1000),
        )
        if args.as_json:
            output_json(result)
        else:
            print(f"Error: {message}", file=sys.stderr)
        sys.exit(1)

    procs: list[subprocess.Popen] = []
    try:
        gdb_proc, gdb_port = start_gdbserver(
            gdbserver_exe=gdbserver_exe,
            device=device,
            interface=interface or "SWD",
            speed=speed or "4000",
            serial_no=serial_no or "",
            gdb_port=args.gdb_port,
        )
        procs.append(gdb_proc)

        ready, server_output = wait_gdbserver_ready(gdb_proc)
        if not ready:
            result = make_result(
                status="error",
                action=args.command,
                summary="GDB Server failed to start",
                details={"device": device, "server_output": server_output},
                context=parameter_context(
                    provider="jlink",
                    workspace=str(workspace),
                    parameter_sources=parameter_sources,
                    config_path=config_path,
                ),
                error={"code": "gdbserver_failed", "message": server_output or "GDB Server failed to start"},
                timing=make_timing(started_at, (time.time() - started_ts) * 1000),
            )
            if args.as_json:
                output_json(result)
            else:
                print(f"[gdb-{args.command}] failed — {result['error']['message']}", file=sys.stderr)
            sys.exit(1)

        try:
            if args.command == "run":
                gdb_commands = list(args.commands)
            else:
                gdb_commands = build_gdb_commands(args.command, getattr(args, "expr", None))
        except ValueError as exc:
            result = make_result(
                status="error",
                action=args.command,
                summary=str(exc),
                details={},
                context=parameter_context(
                    provider="jlink",
                    workspace=str(workspace),
                    parameter_sources=parameter_sources,
                    config_path=config_path,
                ),
                error={"code": "invalid_args", "message": str(exc)},
                timing=make_timing(started_at, (time.time() - started_ts) * 1000),
            )
            if args.as_json:
                output_json(result)
            else:
                print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

        gdb_result = run_gdb_commands(gdb_exe, elf_file or "", f"localhost:{gdb_port}", gdb_commands)
        elapsed_ms = (time.time() - started_ts) * 1000
        if gdb_result["status"] == "timeout" and args.command == "continue":
            parsed = parse_gdb_output(gdb_result.get("stdout", ""), args.command)
            parsed["timed_out"] = True
            artifacts = build_artifacts(debug_file=elf_file)
            state_info = update_state_entry(
                "last_debug",
                {
                    "provider": "jlink",
                    "action": args.command,
                    "device": device,
                    "interface": interface or "SWD",
                    "speed": speed or "4000",
                    "serial_no": serial_no or "",
                    "debug_file": elf_file or "",
                    "artifacts": artifacts,
                },
                str(workspace),
            )
            save_project_config(str(workspace), {
                "device": device,
                "interface": interface or "SWD",
                "speed": speed or "4000",
            })
            result = make_result(
                status="ok",
                action=args.command,
                summary=_summary(args.command, parsed),
                details={
                    "device": device,
                    "gdb_port": gdb_port,
                    "commands": gdb_commands,
                    "output": parsed.get("output", ""),
                    "server_output": server_output,
                    "returncode": gdb_result.get("returncode", 0),
                    **{key: value for key, value in parsed.items() if key != "output"},
                },
                context=parameter_context(
                    provider="jlink",
                    workspace=str(workspace),
                    parameter_sources=parameter_sources,
                    config_path=config_path,
                ),
                artifacts=artifacts,
                metrics=_metrics(parsed),
                state=state_info,
                next_actions=["target is running again; run halt/backtrace/run again to stop it"],
                timing=make_timing(started_at, elapsed_ms),
            )
        elif gdb_result["status"] == "error" or gdb_result["status"] == "timeout":
            result = make_result(
                status="error",
                action=args.command,
                summary="GDB execution failed",
                details={"device": device, "gdb_port": gdb_port},
                context=parameter_context(
                    provider="jlink",
                    workspace=str(workspace),
                    parameter_sources=parameter_sources,
                    config_path=config_path,
                ),
                artifacts=build_artifacts(debug_file=elf_file),
                error={"code": "gdb_error", "message": gdb_result.get("error", gdb_result.get("stderr", "GDB execution failed"))},
                timing=make_timing(started_at, elapsed_ms),
            )
        else:
            parsed = parse_gdb_output(gdb_result["stdout"], args.command)
            artifacts = build_artifacts(debug_file=elf_file)
            state_info = update_state_entry(
                "last_debug",
                {
                    "provider": "jlink",
                    "action": args.command,
                    "device": device,
                    "interface": interface or "SWD",
                    "speed": speed or "4000",
                    "serial_no": serial_no or "",
                    "debug_file": elf_file or "",
                    "artifacts": artifacts,
                },
                str(workspace),
            )
            # Write the confirmed params back to project config
            save_project_config(str(workspace), {
                "device": device,
                "interface": interface or "SWD",
                "speed": speed or "4000",
            })
            result = make_result(
                status="ok",
                action=args.command,
                summary=_summary(args.command, parsed),
                details={
                    "device": device,
                    "gdb_port": gdb_port,
                    "commands": gdb_commands,
                    "output": parsed.get("output", ""),
                    "server_output": server_output,
                    "returncode": gdb_result.get("returncode", 0),
                    **{key: value for key, value in parsed.items() if key != "output"},
                },
                context=parameter_context(
                    provider="jlink",
                    workspace=str(workspace),
                    parameter_sources=parameter_sources,
                    config_path=config_path,
                ),
                artifacts=artifacts,
                metrics=_metrics(parsed),
                state=state_info,
                next_actions=["can continue reusing device/debug_file from last_debug"],
                timing=make_timing(started_at, elapsed_ms),
            )

        if args.as_json:
            output_json(result)
        elif result["status"] == "ok":
            print(f"[gdb-{args.command}] {result['summary']}")
            output = result.get("details", {}).get("output", "")
            if output:
                print(output)
        else:
            print(f"[gdb-{args.command}] failed — {result['error']['message']}", file=sys.stderr)
            sys.exit(1)
    finally:
        cleanup(procs)


if __name__ == "__main__":
    main()
