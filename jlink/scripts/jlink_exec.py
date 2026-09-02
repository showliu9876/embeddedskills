"""J-Link device probing, flashing, memory read/write, register inspection, reset, and on-target debugging."""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Add runtime module path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from jlink_runtime import (
    JLINK_CANDIDATES,
    load_local_config,
    load_project_config,
    save_project_config,
    load_workspace_state,
    get_state_entry,
    update_state_entry,
    workspace_root,
    normalize_path,
    hidden_subprocess_kwargs,
    is_missing,
    resolve_tool_param,
)

# J-Link Commander command templates
TEMPLATES = {
    "info": "si {interface}\nspeed {speed}\nconnect\nsleep 200\nexit\n",
    "flash_hex": "si {interface}\nspeed {speed}\nconnect\nloadfile {file}\nr\ng\nexit\n",
    "flash_bin": "si {interface}\nspeed {speed}\nconnect\nloadbin {file},{address}\nr\ng\nexit\n",
    "read_mem": "si {interface}\nspeed {speed}\nconnect\nhalt\nmem{width} {address},{length}\nexit\n",
    "write_mem": "si {interface}\nspeed {speed}\nconnect\nhalt\nw{width} {address},{value}\nexit\n",
    "regs": "si {interface}\nspeed {speed}\nconnect\nhalt\nregs\nexit\n",
    "reset": "si {interface}\nspeed {speed}\nconnect\nr\ng\nexit\n",
    "halt": "si {interface}\nspeed {speed}\nconnect\nhalt\nregs\nexit\n",
    "go": "si {interface}\nspeed {speed}\nconnect\ng\nexit\n",
    "step": "si {interface}\nspeed {speed}\nconnect\nhalt\n{step_commands}regs\nexit\n",
    "run_to": "si {interface}\nspeed {speed}\nconnect\nSetBP {address}\ng\nsleep {timeout_ms}\nhalt\nregs\nexit\n",
}

# Error pattern matching
ERROR_PATTERNS = [
    (r"Cannot connect to target", "cannot_connect_target", "Cannot connect to target chip. Check wiring, power supply, and interface type."),
    (r"Could not find core", "core_not_found", "Could not find core. Confirm that device matches target chip."),
    (r"No J-Link found", "no_jlink_found", "No J-Link probe detected. Confirm USB connection and driver."),
    (r"Multiple J-Links found", "multiple_jlinks", "Multiple J-Link probes detected. Specify serial number via --serial-no."),
    (r"Could not open file", "file_not_found", "Could not open firmware file. Confirm that the path is correct."),
    (r"Unknown device", "unknown_device", "Unknown chip device model. Confirm --device parameter."),
    (r"VTarget too low", "vtarget_low", "Target voltage too low. Check target board power supply."),
]


def build_jlink_cmd(exe: str, device: str, script_path: str, serial_no: str = "") -> list:
    """Build J-Link Commander command line."""
    cmd = [exe, "-NoGui", "1", "-ExitOnError", "1", "-AutoConnect", "1"]
    cmd.extend(["-Device", device])
    if serial_no:
        cmd.extend(["-SelectEmuBySN", serial_no])
    cmd.extend(["-CommandFile", script_path])
    return cmd


def parse_registers(stdout: str) -> dict:
    """Parse register values from JLink output."""
    registers = {}
    # Match "REG = HEXVALUE" or "REG= HEXVALUE" format
    reg_lines = re.findall(r"(\w+)\s*=\s*([0-9A-Fa-f]{8})", stdout)
    if reg_lines:
        registers = {name: f"0x{val}" for name, val in reg_lines}
    return registers


def parse_pc(stdout: str) -> str:
    """Extract PC value from output."""
    m = re.search(r"PC\s*=\s*([0-9A-Fa-f]{8})", stdout)
    return f"0x{m.group(1)}" if m else ""


def parse_output(stdout: str, action: str) -> dict:
    """Parse J-Link Commander output and extract key information."""
    result = {"raw": stdout}

    # Check error patterns
    for pattern, code, message in ERROR_PATTERNS:
        if re.search(pattern, stdout, re.IGNORECASE):
            return {"error_code": code, "error_message": message, "raw": stdout}

    # info: extract firmware version and target info
    if action == "info":
        fw = re.search(r"Firmware:\s+(.+)", stdout)
        sn = re.search(r"S/N:\s+(\d+)", stdout)
        vtarget = re.search(r"VTref=(\d+\.\d+)V", stdout)
        device_match = re.search(r"Device \"(.+?)\" selected", stdout)
        if fw:
            result["firmware"] = fw.group(1).strip()
        if sn:
            result["serial_no"] = sn.group(1).strip()
        if vtarget:
            result["vtarget_v"] = float(vtarget.group(1))
        if device_match:
            result["device"] = device_match.group(1)

    # flash: extract flashing info
    elif action == "flash":
        speed = re.search(r"Downloading\s+\d+\s+bytes?\s.*?(\d+\.\d+)\s*KB/s", stdout)
        if speed:
            result["speed_kbps"] = float(speed.group(1))
        if "O.K." in stdout or "Verify successful" in stdout or "Download verified successfully" in stdout:
            result["verified"] = True

    # read-mem: extract memory data
    elif action == "read-mem":
        mem_lines = re.findall(r"^([0-9A-Fa-f]{8}) = (.+)$", stdout, re.MULTILINE)
        if mem_lines:
            result["memory"] = []
            for addr, data in mem_lines:
                cleaned = data.strip()
                result["memory"].append({"address": f"0x{addr}", "data": cleaned})

    # regs / halt: extract register values
    elif action in ("regs", "halt"):
        regs = parse_registers(stdout)
        if regs:
            result["registers"] = regs

    # step: extract executed instructions and registers
    elif action == "step":
        # Match step output: ADDR: OPCODE INSTRUCTION
        instructions = re.findall(
            r"^([0-9A-Fa-f]{8}):\s+([0-9A-Fa-f ]+?)\s{2,}(.+)$", stdout, re.MULTILINE
        )
        if instructions:
            result["steps"] = []
            for addr, opcode, instr in instructions:
                result["steps"].append({
                    "address": f"0x{addr}",
                    "opcode": opcode.strip(),
                    "instruction": instr.strip(),
                })
        regs = parse_registers(stdout)
        if regs:
            result["registers"] = regs

    # run-to: extract breakpoint hit status and registers
    elif action == "run-to":
        m = re.search(r"Breakpoint set @ addr 0x([0-9A-Fa-f]+)\s*\(Handle = (\d+)\)", stdout)
        if m:
            result["bp_address"] = f"0x{m.group(1)}"
            result["bp_handle"] = int(m.group(2))
        elif "Could not set" in stdout:
            return {"error_code": "bp_set_failed", "error_message": "Breakpoint set failed; hardware breakpoint slots may be full", "raw": stdout}
        regs = parse_registers(stdout)
        if regs:
            result["registers"] = regs
        # Determine if breakpoint was hit (PC == breakpoint address)
        pc = parse_pc(stdout)
        if m and pc:
            bp_addr = f"0x{m.group(1)}"
            result["bp_hit"] = pc.upper() == bp_addr.upper()

    return result


def run_jlink(exe: str, device: str, action: str, interface: str = "SWD",
              speed: str = "4000", serial_no: str = "", file: str = "",
              address: str = "", length: str = "256", value: str = "",
              width: str = "32", step_count: int = 1,
              timeout_ms: str = "2000") -> dict:
    """Execute JLink Commander commands."""
    start_time = time.time()

    # Select template
    if action == "flash":
        if file.lower().endswith(".bin"):
            if not address:
                return {
                    "status": "error",
                    "action": action,
                    "error": {"code": "missing_address", "message": ".bin file requires flash address via --address"},
                }
            template = TEMPLATES["flash_bin"]
        else:
            template = TEMPLATES["flash_hex"]
    else:
        template_key = action.replace("-", "_")
        if template_key in TEMPLATES:
            template = TEMPLATES[template_key]
        else:
            return {
                "status": "error",
                "action": action,
                "error": {"code": "unknown_action", "message": f"Unknown subcommand: {action}"},
            }

    # width mapping
    width_map = {"8": "8", "16": "16", "32": "32"}
    w = width_map.get(width, "32")

    # step command: generate multiple step instructions
    step_commands = ""
    if action == "step":
        step_commands = "".join(["step\n" for _ in range(step_count)])

    # Render command script
    script_content = template.format(
        interface=interface, speed=speed, file=file,
        address=address, length=length, value=value, width=w,
        step_commands=step_commands, timeout_ms=timeout_ms,
    )

    # Write to temporary file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jlink", delete=False, encoding="utf-8") as f:
        f.write(script_content)
        script_path = f.name

    try:
        if not os.path.isfile(exe):
            return {
                "status": "error",
                "action": action,
                "error": {"code": "exe_not_found", "message": f"J-Link Commander (JLinkExe) not found: {exe}"},
            }

        if file and not os.path.isfile(file):
            return {
                "status": "error",
                "action": action,
                "error": {"code": "file_not_found", "message": f"Firmware file not found: {file}"},
            }

        cmd = build_jlink_cmd(exe, device, script_path, serial_no)

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace",
                **hidden_subprocess_kwargs()
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "action": action,
                "error": {"code": "timeout", "message": "JLinkExe execution timed out (120s)"},
            }
        except Exception as e:
            return {
                "status": "error",
                "action": action,
                "error": {"code": "exec_error", "message": str(e)},
            }

        elapsed_ms = int((time.time() - start_time) * 1000)
        parsed = parse_output(proc.stdout, action)

        if "error_code" in parsed:
            return {
                "status": "error",
                "action": action,
                "error": {"code": parsed["error_code"], "message": parsed["error_message"]},
                "details": {"device": device, "elapsed_ms": elapsed_ms, "errorlevel": proc.returncode},
            }

        # Build summary
        summary_map = {
            "info": "Probe successful",
            "flash": "Flash successful",
            "read-mem": "Memory read successful",
            "write-mem": "Memory write successful",
            "regs": "Registers read successful",
            "reset": "Reset successful",
            "halt": f"Halted, PC={parse_pc(proc.stdout)}",
            "go": "Resumed execution",
            "step": f"Stepped {step_count} time(s), PC={parse_pc(proc.stdout)}",
            "run-to": f"Ran to breakpoint, PC={parse_pc(proc.stdout)}",
        }
        summary = summary_map.get(action, "Execution successful")

        # Supplement run-to summary
        if action == "run-to" and "bp_hit" in parsed:
            if parsed["bp_hit"]:
                summary = f"Breakpoint hit @ {parsed['bp_address']}, PC={parse_pc(proc.stdout)}"
            else:
                summary = f"Timed out without hitting breakpoint @ {parsed.get('bp_address', '?')}, current PC={parse_pc(proc.stdout)}"

        details = {
            "device": device,
            "interface": interface,
            "speed_khz": int(speed),
            "elapsed_ms": elapsed_ms,
            "errorlevel": proc.returncode,
        }
        if serial_no:
            details["serial_no"] = serial_no

        # Merge parsed results
        for k, v in parsed.items():
            if k != "raw":
                details[k] = v

        # Determine status: non-zero returncode may just be a warning, evaluate based on output
        if proc.returncode != 0 and "error_code" not in parsed:
            if action == "flash" and parsed.get("verified"):
                status = "ok"
            else:
                status = "error"
                summary = f"Execution returned non-zero exit code: {proc.returncode}"
        else:
            status = "ok"

        return {
            "status": status,
            "action": action,
            "summary": summary,
            "details": details,
        }
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


def output_json(data: dict):
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=2))


ALL_ACTIONS = [
    "info", "flash", "read-mem", "write-mem", "regs", "reset",
    "halt", "go", "step", "run-to",
]


def resolve_device_params(args):
    """Resolve exe/device/interface/speed/serial_no parameters.

    Priority:
    - exe / serial_no: CLI > machine-level configuration
    - device / interface / speed: CLI > project configuration > state.json > defaults
    """
    workspace = workspace_root(args.workspace)
    local_config = load_local_config(__file__)
    project_config = load_project_config(str(workspace))
    state = load_workspace_state(str(workspace))

    # Get historical values from state
    last_flash = get_state_entry(state, "last_flash")
    last_debug = get_state_entry(state, "last_debug")

    # device: CLI > project config > state > error
    device = args.device
    device_source = "cli"
    if is_missing(device):
        device = project_config.get("device")
        device_source = "project_config"
    if is_missing(device):
        device = last_flash.get("device") or last_debug.get("device")
        device_source = "state"

    # interface: CLI > project config > state > default SWD
    interface = args.interface
    interface_source = "cli"
    if is_missing(interface):
        interface = project_config.get("interface")
        interface_source = "project_config"
    if is_missing(interface):
        interface = last_flash.get("interface") or last_debug.get("interface")
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
        speed = last_flash.get("speed") or last_debug.get("speed")
        speed_source = "state"
    if is_missing(speed):
        speed = "4000"
        speed_source = "default"

    # exe: CLI > machine-level config > PATH > common install directories
    exe, exe_source = resolve_tool_param(
        "exe",
        args.exe,
        local_config=local_config,
        local_keys=["exe"],
        path_candidates=JLINK_CANDIDATES,
    )

    # serial_no: CLI > machine-level config > state
    serial_no = args.serial_no
    serial_no_source = "cli"
    if is_missing(serial_no):
        serial_no = local_config.get("serial_no", "")
        serial_no_source = "config" if not is_missing(serial_no) else ""
    if is_missing(serial_no):
        serial_no = last_flash.get("serial_no") or last_debug.get("serial_no") or ""
        serial_no_source = "state" if not is_missing(serial_no) else ""

    return {
        "exe": exe,
        "exe_source": exe_source,
        "device": device,
        "device_source": device_source,
        "interface": interface,
        "interface_source": interface_source,
        "speed": speed,
        "speed_source": speed_source,
        "serial_no": serial_no,
        "serial_no_source": serial_no_source,
    }


def main():
    parser = argparse.ArgumentParser(description="J-Link device probe/flash/memory read-write/registers/reset/on-target debugging")
    parser.add_argument("action", choices=ALL_ACTIONS)
    parser.add_argument("--exe", default="", help="J-Link Commander path (Linux: JLinkExe)")
    parser.add_argument("--device", default=None, help="Target chip model (e.g. STM32F407VG)")
    parser.add_argument("--interface", default=None, help="Debug interface")
    parser.add_argument("--speed", default=None, help="Debug speed in kHz")
    parser.add_argument("--serial-no", default="", help="Probe serial number")
    parser.add_argument("--file", default="", help="Firmware file path (for flash)")
    parser.add_argument("--address", default="", help="Address (for flash .bin / read-mem / write-mem / bp-set)")
    parser.add_argument("--length", default="256", help="Read length (for read-mem)")
    parser.add_argument("--value", default="", help="Value to write (for write-mem)")
    parser.add_argument("--width", default="32", choices=["8", "16", "32"], help="Data width")
    parser.add_argument("--count", type=int, default=1, help="Number of steps (for step)")
    parser.add_argument("--timeout-ms", default="2000", help="Timeout in milliseconds to wait for breakpoint hit in run-to")
    parser.add_argument("--workspace", default=None, help="Workspace root directory, defaults to current directory")
    parser.add_argument("--json", action="store_true", dest="as_json")

    args = parser.parse_args()

    # Parse parameters
    params = resolve_device_params(args)
    workspace = workspace_root(args.workspace)

    # Check if device was provided
    if is_missing(params["device"]):
        result = {
            "status": "error", "action": args.action,
            "error": {"code": "missing_device", "message": "--device chip model must be provided or configured via .embeddedskills/config.json"},
        }
        if args.as_json:
            output_json(result)
        else:
            print(f"Error: {result['error']['message']}", file=sys.stderr)
        sys.exit(1)

    # Parameter validation
    if args.action == "flash" and not args.file:
        result = {
            "status": "error", "action": "flash",
            "error": {"code": "missing_file", "message": "flash requires firmware file path via --file"},
        }
        if args.as_json:
            output_json(result)
        else:
            print(f"Error: {result['error']['message']}", file=sys.stderr)
        sys.exit(1)

    if args.action == "write-mem" and (not args.address or not args.value):
        result = {
            "status": "error", "action": "write-mem",
            "error": {"code": "missing_params", "message": "write-mem requires --address and --value"},
        }
        if args.as_json:
            output_json(result)
        else:
            print(f"Error: {result['error']['message']}", file=sys.stderr)
        sys.exit(1)

    if args.action == "read-mem" and not args.address:
        result = {
            "status": "error", "action": "read-mem",
            "error": {"code": "missing_address", "message": "read-mem requires --address"},
        }
        if args.as_json:
            output_json(result)
        else:
            print(f"Error: {result['error']['message']}", file=sys.stderr)
        sys.exit(1)

    if args.action == "run-to" and not args.address:
        result = {
            "status": "error", "action": "run-to",
            "error": {"code": "missing_address", "message": "run-to requires breakpoint address via --address"},
        }
        if args.as_json:
            output_json(result)
        else:
            print(f"Error: {result['error']['message']}", file=sys.stderr)
        sys.exit(1)

    result = run_jlink(
        exe=params["exe"],
        device=params["device"],
        action=args.action,
        interface=params["interface"],
        speed=params["speed"],
        serial_no=params["serial_no"],
        file=args.file,
        address=args.address,
        length=args.length,
        value=args.value,
        width=args.width,
        step_count=args.count,
        timeout_ms=args.timeout_ms,
    )

    # Write confirmed parameters back to project config upon successful execution
    if result.get("status") == "ok":
        save_project_config(str(workspace), {
            "device": params["device"],
            "interface": params["interface"],
            "speed": params["speed"],
        })
        # Update state.json as well
        if args.action in ("flash", "reset", "halt", "go", "step", "run-to", "info"):
            state_action = "last_flash" if args.action == "flash" else "last_debug"
            update_state_entry(
                state_action,
                {
                    "provider": "jlink",
                    "action": args.action,
                    "device": params["device"],
                    "interface": params["interface"],
                    "speed": params["speed"],
                    "serial_no": params["serial_no"] or "",
                },
                str(workspace),
            )

    if args.as_json:
        # Add parameter sources info
        if "details" not in result:
            result["details"] = {}
        result["details"]["parameter_sources"] = {
            "exe": params["exe_source"],
            "device": params["device_source"],
            "interface": params["interface_source"],
            "speed": params["speed_source"],
            "serial_no": params["serial_no_source"],
        }
        output_json(result)
    else:
        if result["status"] == "ok":
            print(f"[{args.action}] {result.get('summary', 'Success')}")
            details = result.get("details", {})
            if "registers" in details:
                # Display only core registers
                core_regs = ["PC", "R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7",
                             "R8", "R9", "R10", "R11", "R12", "MSP", "PSP", "XPSR"]
                for name in core_regs:
                    if name in details["registers"]:
                        print(f"  {name:>5s} = {details['registers'][name]}")
            if "steps" in details:
                for s in details["steps"]:
                    print(f"  {s['address']}: {s['opcode']:16s} {s['instruction']}")
            if "memory" in details:
                for m in details["memory"]:
                    print(f"  {m['address']}: {m['data']}")
            if "bp_hit" in details:
                hit = "Hit" if details["bp_hit"] else "Missed (timed out)"
                print(f"  Breakpoint: {details.get('bp_address', '?')} — {hit}")
        else:
            err = result.get("error", {})
            print(f"[{args.action}] failed — {err.get('message', 'Unknown error')}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
