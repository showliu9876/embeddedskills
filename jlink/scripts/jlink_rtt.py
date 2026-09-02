"""J-Link RTT log reader."""

from __future__ import annotations

import argparse
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from jlink_runtime import (  # noqa: E402
    JLINK_GDBSERVER_CANDIDATES,
    JLINK_RTT_CANDIDATES,
    default_config_path,
    emit_stream_record,
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


def start_gdbserver(
    gdbserver_exe: str,
    device: str,
    interface: str = "SWD",
    speed: str = "4000",
    serial_no: str = "",
    rtt_port: int = 0,
) -> subprocess.Popen:
    cmd = [
        gdbserver_exe,
        "-device",
        device,
        "-if",
        interface,
        "-speed",
        speed,
        "-noir",
        "-LocalhostOnly",
        "-nologtofile",
        "-singlerun",
    ]
    if serial_no:
        cmd.extend(["-select", f"USB={serial_no}"])
    if rtt_port:
        cmd.extend(["-RTTTelnetPort", str(rtt_port)])
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **hidden_subprocess_kwargs(new_process_group=True),
    )


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
        if "Waiting for GDB connection" in line or "Connected to target" in line or "J-Link is connected" in line:
            return True, "\n".join(captured)
        if "Cannot connect" in line or "Could not connect" in line:
            return False, "\n".join(captured)
    return False, "\n".join(captured)


def start_rtt_client(rtt_exe: str, rtt_port: int = 19021) -> subprocess.Popen:
    cmd = [rtt_exe]
    if rtt_port:
        cmd.extend(["-LocalEcho", "Off", "-RTTTelnetPort", str(rtt_port)])
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **hidden_subprocess_kwargs(),
    )


def cleanup(procs: list[subprocess.Popen]) -> None:
    for proc in procs:
        if not proc:
            continue
        try:
            if proc.poll() is None:
                if sys.platform == "win32":
                    proc.terminate()
                else:
                    proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            pass

        if proc.poll() is None:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    **hidden_subprocess_kwargs(),
                )
            else:
                proc.kill()


def start_stream_reader(stream) -> queue.Queue:
    line_queue: queue.Queue = queue.Queue()

    def _reader() -> None:
        try:
            for line in iter(stream.readline, ""):
                line_queue.put(line)
        finally:
            line_queue.put(None)

    threading.Thread(target=_reader, daemon=True).start()
    return line_queue


def _state_lookup(state: dict) -> dict:
    last_debug = get_state_entry(state, "last_debug")
    last_flash = get_state_entry(state, "last_flash")
    return {
        "device": last_debug.get("device") or last_flash.get("device"),
        "serial_no": last_debug.get("serial_no") or last_flash.get("serial_no"),
        "interface": last_debug.get("interface") or last_flash.get("interface"),
        "speed": last_debug.get("speed") or last_flash.get("speed"),
    }


def resolve_device_params(args, project_config: dict, state_lookup: dict) -> dict:
    """Resolve device/interface/speed parameters, priority: CLI > project config > state.json > default"""
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


def main() -> None:
    parser = argparse.ArgumentParser(description="J-Link RTT log reader")
    parser.add_argument("--device", default=None, help="Target chip model")
    parser.add_argument("--gdbserver-exe", default=None, help="J-Link GDB Server path (Linux: JLinkGDBServerCLExe)")
    parser.add_argument("--rtt-exe", default=None, help="J-Link RTT Client path (Linux: JLinkRTTClient)")
    parser.add_argument("--interface", default=None, help="Debug interface")
    parser.add_argument("--speed", default=None, help="Debug speed in kHz")
    parser.add_argument("--serial-no", default=None, help="Probe serial number")
    parser.add_argument("--channel", type=int, default=0, help="RTT channel")
    parser.add_argument("--rtt-port", type=int, default=None, help="RTT Telnet port")
    parser.add_argument("--duration", type=float, default=0, help="Duration to read in seconds, 0=run continuously")
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

    # Resolve device/interface/speed parameters
    dev_params = resolve_device_params(args, project_config, state_lookup)

    parameter_sources: dict[str, str] = {}
    try:
        # device from project config or state
        device = dev_params["device"]
        parameter_sources["device"] = dev_params["device_source"]
        if is_missing(device):
            raise ValueError("Missing required parameter: device")

        gdbserver_exe, parameter_sources["gdbserver_exe"] = resolve_tool_param(
            "gdbserver_exe",
            args.gdbserver_exe,
            local_config=config,
            local_keys=["gdbserver_exe"],
            path_candidates=JLINK_GDBSERVER_CANDIDATES,
            required=True,
        )
        rtt_exe, parameter_sources["rtt_exe"] = resolve_tool_param(
            "rtt_exe",
            args.rtt_exe,
            local_config=config,
            local_keys=["rtt_exe"],
            path_candidates=JLINK_RTT_CANDIDATES,
            required=True,
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
        rtt_port, parameter_sources["rtt_port"] = resolve_param(
            "rtt_port",
            args.rtt_port,
            config=config,
            config_keys=["rtt_telnet_port"],
        )
    except ValueError as exc:
        result = make_result(
            status="error",
            action="rtt",
            summary=str(exc),
            details={},
            context=parameter_context(provider="jlink", workspace=str(workspace), parameter_sources=parameter_sources, config_path=config_path),
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
            action="rtt",
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

    if not os.path.isfile(rtt_exe):
        message = f"J-Link RTT Client (JLinkRTTClient) not found: {rtt_exe}"
        result = make_result(
            status="error",
            action="rtt",
            summary=message,
            details={},
            context=parameter_context(provider="jlink", workspace=str(workspace), parameter_sources=parameter_sources, config_path=config_path),
            error={"code": "rtt_exe_not_found", "message": message},
            timing=make_timing(started_at, (time.time() - started_ts) * 1000),
        )
        if args.as_json:
            output_json(result)
        else:
            print(f"Error: {message}", file=sys.stderr)
        sys.exit(1)

    rtt_port_value = int(rtt_port or 19021)
    procs: list[subprocess.Popen] = []
    try:
        if not args.as_json:
            print("Starting JLinkGDBServerCL ...", file=sys.stderr, flush=True)

        gdb_proc = start_gdbserver(
            gdbserver_exe=gdbserver_exe,
            device=device,
            interface=interface or "SWD",
            speed=speed or "4000",
            serial_no=serial_no or "",
            rtt_port=rtt_port_value,
        )
        procs.append(gdb_proc)

        ready, server_output = wait_gdbserver_ready(gdb_proc)
        if not ready:
            result = make_result(
                status="error",
                action="rtt",
                summary="RTT service failed to start",
                details={"device": device, "server_output": server_output},
                context=parameter_context(provider="jlink", workspace=str(workspace), parameter_sources=parameter_sources, config_path=config_path),
                error={"code": "gdbserver_failed", "message": server_output or "GDB Server failed to start or connection timed out"},
                timing=make_timing(started_at, (time.time() - started_ts) * 1000),
            )
            if args.as_json:
                output_json(result)
            else:
                print(f"Error: {result['error']['message']}", file=sys.stderr)
            sys.exit(1)

        state_info = update_state_entry(
            "last_observe",
            {
                "provider": "jlink",
                "action": "rtt",
                "device": device,
                "interface": interface or "SWD",
                "speed": speed or "4000",
                "serial_no": serial_no or "",
                "channel_type": "rtt",
                "stream_type": "text",
                "source": "jlink",
            },
            str(workspace),
        )
        # Write confirmed parameters back to project configuration
        save_project_config(str(workspace), {
            "device": device,
            "interface": interface or "SWD",
            "speed": speed or "4000",
        })

        if not args.as_json:
            print("GDB Server ready, starting RTT Client ...", file=sys.stderr, flush=True)

        rtt_proc = start_rtt_client(rtt_exe, rtt_port_value)
        procs.append(rtt_proc)
        line_queue = start_stream_reader(rtt_proc.stdout)

        if not args.as_json:
            print("RTT output started (Ctrl+C to exit):", file=sys.stderr, flush=True)
            print("-" * 40, file=sys.stderr, flush=True)

        while True:
            if args.duration > 0 and (time.time() - started_ts) >= args.duration:
                break
            try:
                line = line_queue.get(timeout=0.1)
            except queue.Empty:
                if rtt_proc.poll() is not None:
                    break
                continue
            if line is None:
                if rtt_proc.poll() is not None:
                    break
                continue

            stripped = line.strip()
            if (
                stripped.startswith("###RTT Client:")
                or stripped.startswith("SEGGER J-Link")
                or stripped.startswith("Process:")
                or stripped == ""
                or stripped.startswith("***")
                or stripped.startswith("---")
            ):
                continue

            emit_stream_record(
                source="jlink",
                channel_type="rtt",
                text=line,
                as_json=args.as_json,
                stream_type="text",
                channel=args.channel,
                extra={"device": device},
            )

    except KeyboardInterrupt:
        if not args.as_json:
            print("\nStopped RTT reading", file=sys.stderr, flush=True)
    finally:
        cleanup(procs)


if __name__ == "__main__":
    main()
