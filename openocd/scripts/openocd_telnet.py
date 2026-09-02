"""OpenOCD Telnet debug commands.

Connect to OpenOCD Telnet port via socket to execute online debugging commands:
halt / resume / step / reg / read-mem / write-mem / bp / rbp / run-to
"""

import argparse
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

# Add runtime module path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from openocd_runtime import (
    hidden_subprocess_kwargs,
    load_project_config,
    save_project_config,
    load_workspace_state,
    get_state_entry,
    workspace_root,
    is_missing,
)


# ── OpenOCD server startup (reuses openocd_gdb.py pattern) ──────────────────

def build_openocd_cmd(exe: str, board: str = "", interface: str = "", target: str = "",
                      search: str = "", adapter_speed: str = "", transport: str = "",
                      gdb_port: int = 3333, telnet_port: int = 4444) -> list:
    """Build OpenOCD command line."""
    cmd = [exe]
    if search:
        cmd.extend(["-s", search])
    if board:
        cmd.extend(["-f", board])
    else:
        if interface:
            cmd.extend(["-f", interface])
        if target:
            cmd.extend(["-f", target])
    if adapter_speed:
        cmd.extend(["-c", f"adapter speed {adapter_speed}"])
    if transport:
        cmd.extend(["-c", f"transport select {transport}"])
    cmd.extend(["-c", f"gdb_port {gdb_port}"])
    cmd.extend(["-c", f"telnet_port {telnet_port}"])
    return cmd


def start_openocd_server(cmd: list) -> subprocess.Popen:
    """Start OpenOCD process."""
    popen_kwargs = hidden_subprocess_kwargs()
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    if popen_kwargs.get("creationflags"):
        creationflags |= popen_kwargs["creationflags"]
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        startupinfo=popen_kwargs.get("startupinfo"),
    )


def wait_server_ready(proc: subprocess.Popen, telnet_port: int, timeout: int = 15) -> tuple:
    """Wait for OpenOCD to become ready, returning (ready, errors)."""
    start = time.time()
    errors = []
    ready = False
    while time.time() - start < timeout:
        if proc.poll() is not None:
            remaining = proc.stderr.read()
            for line in remaining.splitlines():
                if "Error:" in line:
                    errors.append(line.strip())
            return False, errors
        line = proc.stderr.readline()
        if not line:
            time.sleep(0.1)
            continue
        line = line.strip()
        if "Error:" in line:
            errors.append(line)
        if f"Listening on port {telnet_port}" in line or "listening on" in line.lower():
            ready = True
            break

    if not ready:
        return False, errors

    critical_keywords = [
        "open failed", "init mode failed", "no device found",
        "cannot connect", "error connecting dp", "examination failed",
        "failed to read memory", "failed to write memory",
        "cannot read idr", "polling failed",
    ]
    critical_errors = [e for e in errors if any(k in e.lower() for k in critical_keywords)]
    if critical_errors:
        return False, critical_errors
    return True, errors


def cleanup_proc(proc: subprocess.Popen):
    """Clean up OpenOCD process."""
    if proc and proc.poll() is None:
        try:
            if sys.platform == "win32":
                proc.terminate()
            else:
                proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            proc.kill()


# ── Telnet connection layer ──────────────────────────────────────────────

class TelnetConnection:
    """Connect to OpenOCD Telnet interface via raw socket."""

    def __init__(self, host: str = "localhost", port: int = 4444, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self._buf = b""

    @staticmethod
    def _strip_iac(data: bytes) -> bytes:
        """Filter Telnet IAC negotiation bytes and NUL characters."""
        clean = bytearray()
        i = 0
        while i < len(data):
            b = data[i]
            if b == 0xff and i + 2 < len(data):
                i += 3  # Skip IAC + cmd + option
            elif b == 0x00:
                i += 1  # Skip NUL
            else:
                clean.append(b)
                i += 1
        return bytes(clean)

    def connect(self, retries: int = 3, retry_delay: float = 0.5):
        """Connect to Telnet port with retry support."""
        for i in range(retries):
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(self.timeout)
                self.sock.connect((self.host, self.port))
                # Read initial prompt
                self._read_until_prompt()
                return
            except (ConnectionRefusedError, OSError):
                if self.sock:
                    self.sock.close()
                    self.sock = None
                if i < retries - 1:
                    time.sleep(retry_delay)
        raise ConnectionError(f"Cannot connect to OpenOCD Telnet port {self.host}:{self.port}")

    def send(self, command: str) -> str:
        """Send command and return response text."""
        if not self.sock:
            raise ConnectionError("Not connected")
        self.sock.sendall((command + "\n").encode("utf-8"))
        return self._read_until_prompt()

    def _read_until_prompt(self) -> str:
        """Read data until '> ' prompt appears."""
        while True:
            # Filter IAC and NUL, then decode
            clean = self._strip_iac(self._buf)
            decoded = clean.decode("utf-8", errors="replace")
            # OpenOCD prompt: "\r\n> " or "\r> " or trailing "> "
            prompt_pos = decoded.rfind("\n> ")
            if prompt_pos == -1:
                prompt_pos = decoded.rfind("\r> ")
            if prompt_pos == -1 and decoded.endswith("> "):
                prompt_pos = len(decoded) - 2
            if prompt_pos >= 0:
                response = decoded[:prompt_pos]
                self._buf = b""
                # Strip command echo (first line is typically the sent command itself)
                lines = response.split("\n")
                if lines:
                    lines = [l.rstrip("\r") for l in lines]
                return "\n".join(lines).strip()
            try:
                chunk = self.sock.recv(4096)
                if not chunk:
                    clean = self._strip_iac(self._buf)
                    response = clean.decode("utf-8", errors="replace")
                    self._buf = b""
                    return response.strip()
                self._buf += chunk
            except socket.timeout:
                clean = self._strip_iac(self._buf)
                response = clean.decode("utf-8", errors="replace")
                self._buf = b""
                return response.strip()

    def close(self):
        if self.sock:
            try:
                self.sock.sendall(b"shutdown\n")
                time.sleep(0.2)
            except OSError:
                pass
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None


# ── Output parsing ──────────────────────────────────────────────────

def parse_reg_single(raw: str) -> dict:
    """Parse single register query result: 'regname (/bits): 0xVALUE' or 'regname 0xVALUE'."""
    result = {}
    # Format 1: pc (/32): 0x080009dc
    m = re.search(r"(\w+)\s+\(/\d+\):\s*(0x[0-9a-fA-F]+)", raw)
    if m:
        result[m.group(1)] = m.group(2)
        return result
    # Format 2: pc 0x080009dc (get_reg format)
    m = re.search(r"(\w+)\s+(0x[0-9a-fA-F]+)", raw)
    if m:
        result[m.group(1)] = m.group(2)
    return result


def parse_reg_response(raw: str) -> dict:
    """Parse reg command output (all registers)."""
    registers = {}
    # reg output format after halt: (N) regname (/bits): 0xVALUE
    for m in re.finditer(r"\(\d+\)\s+(\S+)\s+\(/\d+\):\s*(0x[0-9a-fA-F]+)", raw):
        registers[m.group(1)] = m.group(2)
    # Fallback format: regname (/bits): 0xVALUE (no index)
    if not registers:
        for m in re.finditer(r"(\w+)\s+\(/\d+\):\s*(0x[0-9a-fA-F]+)", raw):
            registers[m.group(1)] = m.group(2)
    return registers


def parse_mem_response(raw: str) -> list:
    """Parse memory read output: 0xADDR: DATA DATA ..."""
    memory = []
    for m in re.finditer(r"(0x[0-9a-fA-F]+)\s*:\s*([0-9a-fA-F ]+)", raw):
        addr = m.group(1)
        data = m.group(2).strip()
        memory.append({"address": addr, "data": data})
    return memory


def has_command_error(raw: str) -> bool:
    """Identify failure semantics in OpenOCD Telnet responses."""
    lowered = raw.lower()
    keywords = [
        "error:",
        "failed",
        "not halted",
        "context restore failed",
        "target not halted",
        "timed out",
        "unknown command",
    ]
    return any(keyword in lowered for keyword in keywords)


# ── Main logic ────────────────────────────────────────────────────

def output_json(data: dict):
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False, indent=2), flush=True)


ALL_ACTIONS = ["halt", "resume", "step", "reg", "read-mem", "write-mem", "bp", "rbp", "run-to"]


def resolve_openocd_params(args, project_config: dict, state_lookup: dict) -> dict:
    """Resolve OpenOCD project-level parameters, priority: CLI > project configuration > state.json"""
    # board: CLI > project configuration > state
    board = args.board
    board_source = "cli"
    if is_missing(board):
        board = project_config.get("board")
        board_source = "project_config"
    if is_missing(board):
        board = state_lookup.get("board")
        board_source = "state"

    # interface: CLI > project configuration > state
    interface = args.interface
    interface_source = "cli"
    if is_missing(interface):
        interface = project_config.get("interface")
        interface_source = "project_config"
    if is_missing(interface):
        interface = state_lookup.get("interface")
        interface_source = "state"

    # target: CLI > project configuration > state
    target = args.target
    target_source = "cli"
    if is_missing(target):
        target = project_config.get("target")
        target_source = "project_config"
    if is_missing(target):
        target = state_lookup.get("target")
        target_source = "state"

    # adapter_speed: CLI > project configuration > state
    adapter_speed = args.adapter_speed
    adapter_speed_source = "cli"
    if is_missing(adapter_speed):
        adapter_speed = project_config.get("adapter_speed")
        adapter_speed_source = "project_config"
    if is_missing(adapter_speed):
        adapter_speed = state_lookup.get("adapter_speed")
        adapter_speed_source = "state"

    # transport: CLI > project configuration > state
    transport = args.transport
    transport_source = "cli"
    if is_missing(transport):
        transport = project_config.get("transport")
        transport_source = "project_config"
    if is_missing(transport):
        transport = state_lookup.get("transport")
        transport_source = "state"

    return {
        "board": board,
        "board_source": board_source,
        "interface": interface,
        "interface_source": interface_source,
        "target": target,
        "target_source": target_source,
        "adapter_speed": adapter_speed,
        "adapter_speed_source": adapter_speed_source,
        "transport": transport,
        "transport_source": transport_source,
    }


def main():
    parser = argparse.ArgumentParser(description="OpenOCD Telnet debug commands")
    parser.add_argument("action", choices=ALL_ACTIONS)
    parser.add_argument("--exe", default="openocd", help="openocd path")
    parser.add_argument("--board", default=None, help="board configuration file")
    parser.add_argument("--interface", default=None, help="interface configuration file")
    parser.add_argument("--target", default=None, help="target configuration file")
    parser.add_argument("--search", default="", help="extra configuration script search directory")
    parser.add_argument("--adapter-speed", default=None, help="adapter speed in kHz")
    parser.add_argument("--transport", default=None, choices=["", "swd", "jtag"], help="transport protocol")
    parser.add_argument("--gdb-port", type=int, default=3333, help="GDB port")
    parser.add_argument("--telnet-port", type=int, default=4444, help="Telnet port")
    parser.add_argument("--address", default="", help="address (for read-mem/write-mem/bp/rbp/run-to)")
    parser.add_argument("--length", type=int, default=16, help="read length (for read-mem, number of width items)")
    parser.add_argument("--value", default="", help="write value (for write-mem)")
    parser.add_argument("--width", default="32", choices=["8", "16", "32"], help="data width")
    parser.add_argument("--count", type=int, default=1, help="step count (for step)")
    parser.add_argument("--timeout-ms", type=int, default=2000, help="run-to wait timeout in milliseconds")
    parser.add_argument("--bp-length", type=int, default=2, help="breakpoint length (for bp, Thumb=2/ARM=4)")
    parser.add_argument("--workspace", default=None, help="workspace root directory, defaults to current directory")
    parser.add_argument("--json", action="store_true", dest="as_json")

    args = parser.parse_args()

    # Resolve project-level parameters
    workspace = workspace_root(args.workspace)
    project_config = load_project_config(str(workspace))
    state = load_workspace_state(str(workspace))
    state_lookup = {
        "board": get_state_entry(state, "last_debug").get("board") or get_state_entry(state, "last_flash").get("board"),
        "interface": get_state_entry(state, "last_debug").get("interface") or get_state_entry(state, "last_flash").get("interface"),
        "target": get_state_entry(state, "last_debug").get("target") or get_state_entry(state, "last_flash").get("target"),
        "adapter_speed": get_state_entry(state, "last_debug").get("adapter_speed") or get_state_entry(state, "last_flash").get("adapter_speed"),
        "transport": get_state_entry(state, "last_debug").get("transport") or get_state_entry(state, "last_flash").get("transport"),
    }
    oc_params = resolve_openocd_params(args, project_config, state_lookup)

    # Use resolved parameters
    board = oc_params["board"]
    interface = oc_params["interface"]
    target = oc_params["target"]
    adapter_speed = oc_params["adapter_speed"]
    transport = oc_params["transport"]

    # Parameter validation
    if not board and not interface and not target:
        result = {
            "status": "error", "action": args.action,
            "error": {"code": "missing_config", "message": "Must provide --board or --interface + --target, or configure via .embeddedskills/config.json"},
        }
        if args.as_json:
            output_json(result)
        else:
            print(f"Error: {result['error']['message']}", file=sys.stderr, flush=True)
        sys.exit(1)

    if args.action in ("read-mem", "write-mem", "bp", "rbp", "run-to") and not args.address:
        result = {
            "status": "error", "action": args.action,
            "error": {"code": "missing_address", "message": f"{args.action} requires --address"},
        }
        if args.as_json:
            output_json(result)
        else:
            print(f"Error: {result['error']['message']}", file=sys.stderr, flush=True)
        sys.exit(1)

    if args.action == "write-mem" and not args.value:
        result = {
            "status": "error", "action": args.action,
            "error": {"code": "missing_value", "message": "write-mem requires --value"},
        }
        if args.as_json:
            output_json(result)
        else:
            print(f"Error: {result['error']['message']}", file=sys.stderr, flush=True)
        sys.exit(1)

    # Build OpenOCD command and start
    cmd = build_openocd_cmd(
        exe=args.exe, board=board or "", interface=interface or "", target=target or "",
        search=args.search, adapter_speed=adapter_speed or "", transport=transport or "",
        gdb_port=args.gdb_port, telnet_port=args.telnet_port,
    )

    proc = None
    telnet = None
    try:
        proc = start_openocd_server(cmd)
        ready, errors = wait_server_ready(proc, args.telnet_port)

        if not ready:
            error_msg = "; ".join(errors) if errors else "OpenOCD failed to start or timed out"
            result = {
                "status": "error", "action": args.action,
                "error": {"code": "server_failed", "message": error_msg},
            }
            if args.as_json:
                output_json(result)
            else:
                print(f"Error: {error_msg}", file=sys.stderr, flush=True)
            sys.exit(1)

        # Connect Telnet
        telnet = TelnetConnection(port=args.telnet_port)
        telnet.connect()

        # Execute debug command
        result = execute_action(telnet, args)

        # Write confirmed parameters back to project config upon successful execution
        if result.get("status") == "ok":
            save_project_config(str(workspace), {
                "board": board or "",
                "interface": interface or "",
                "target": target or "",
                "adapter_speed": adapter_speed or "",
                "transport": transport or "",
            })

        if args.as_json:
            output_json(result)
        else:
            print_result(result, args.action)

    except FileNotFoundError:
        result = {
            "status": "error", "action": args.action,
            "error": {"code": "exe_not_found", "message": f"openocd does not exist or is not in PATH: {args.exe}"},
        }
        if args.as_json:
            output_json(result)
        else:
            print(f"Error: {result['error']['message']}", file=sys.stderr, flush=True)
        sys.exit(1)
    except ConnectionError as e:
        result = {
            "status": "error", "action": args.action,
            "error": {"code": "telnet_connect_failed", "message": str(e)},
        }
        if args.as_json:
            output_json(result)
        else:
            print(f"Error: {result['error']['message']}", file=sys.stderr, flush=True)
        sys.exit(1)
    finally:
        if telnet:
            telnet.close()
        if proc:
            cleanup_proc(proc)


def execute_action(telnet: TelnetConnection, args) -> dict:
    """Execute Telnet debug command according to action."""
    action = args.action
    start_time = time.time()

    if action == "halt":
        telnet.send("halt")
        time.sleep(0.1)
        # halt status info is output to stderr rather than Telnet response, requiring separate query
        pc_raw = telnet.send("reg pc")
        xpsr_raw = telnet.send("reg xpsr")
        msp_raw = telnet.send("reg msp")
        pc_regs = parse_reg_single(pc_raw)
        xpsr_regs = parse_reg_single(xpsr_raw)
        msp_regs = parse_reg_single(msp_raw)
        parsed = {"halted": True, **pc_regs, **xpsr_regs, **msp_regs}
        pc = parsed.get("pc", "?")
        return {
            "status": "ok", "action": "halt",
            "summary": f"Halted, PC={pc}",
            "details": parsed,
        }

    elif action == "resume":
        raw = telnet.send("resume")
        lowered = raw.lower()
        if "not halted" in lowered and "context restore failed" in lowered:
            return {
                "status": "ok", "action": "resume",
                "summary": "Target is already running",
                "details": {"response": raw, "already_running": True},
            }
        if has_command_error(raw):
            return {
                "status": "error", "action": "resume",
                "error": {"code": "resume_failed", "message": raw or "resume execution failed"},
            }
        return {
            "status": "ok", "action": "resume",
            "summary": "Running resumed",
            "details": {"response": raw},
        }

    elif action == "step":
        count = args.count
        steps = []
        for i in range(count):
            telnet.send("step")
            time.sleep(0.15)
            pc_raw = telnet.send("reg pc")
            pc_regs = parse_reg_single(pc_raw)
            pc = pc_regs.get("pc", "?")
            steps.append({"step": i + 1, "pc": pc})
        last_pc = steps[-1]["pc"] if steps else "?"
        return {
            "status": "ok", "action": "step",
            "summary": f"Stepped {count} time(s), PC={last_pc}",
            "details": {"steps": steps, "pc": last_pc},
        }

    elif action == "reg":
        # Ensure target is halted
        telnet.send("halt")
        time.sleep(0.1)
        # OpenOCD reg (list all) does not show values; query core registers individually
        core_reg_names = [
            "r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7",
            "r8", "r9", "r10", "r11", "r12", "sp", "lr", "pc",
            "xpsr", "msp", "psp", "primask", "basepri", "faultmask", "control",
        ]
        registers = {}
        for name in core_reg_names:
            raw = telnet.send(f"reg {name}")
            parsed = parse_reg_single(raw)
            registers.update(parsed)
        return {
            "status": "ok", "action": "reg",
            "summary": f"Read {len(registers)} registers",
            "details": {"registers": registers},
        }

    elif action == "read-mem":
        width_cmd = {"8": "mdb", "16": "mdh", "32": "mdw"}
        cmd = f"{width_cmd[args.width]} {args.address} {args.length}"
        raw = telnet.send(cmd)
        memory = parse_mem_response(raw)
        return {
            "status": "ok", "action": "read-mem",
            "summary": f"Read {args.length} x {args.width}bit @ {args.address}",
            "details": {"width": int(args.width), "memory": memory},
        }

    elif action == "write-mem":
        width_cmd = {"8": "mwb", "16": "mwh", "32": "mww"}
        cmd = f"{width_cmd[args.width]} {args.address} {args.value}"
        raw = telnet.send(cmd)
        # Check for errors
        if has_command_error(raw):
            return {
                "status": "error", "action": "write-mem",
                "error": {"code": "write_failed", "message": raw},
            }
        return {
            "status": "ok", "action": "write-mem",
            "summary": f"Written {args.value} @ {args.address} ({args.width}bit)",
            "details": {"address": args.address, "value": args.value, "width": int(args.width)},
        }

    elif action == "bp":
        cmd = f"bp {args.address} {args.bp_length} hw"
        raw = telnet.send(cmd)
        if has_command_error(raw):
            return {
                "status": "error", "action": "bp",
                "error": {"code": "bp_set_failed", "message": f"Breakpoint set failed: {raw}"},
            }
        return {
            "status": "ok", "action": "bp",
            "summary": f"Breakpoint set @ {args.address}",
            "details": {"address": args.address, "length": args.bp_length, "type": "hw"},
        }

    elif action == "rbp":
        cmd = f"rbp {args.address}"
        raw = telnet.send(cmd)
        if has_command_error(raw):
            return {
                "status": "error", "action": "rbp",
                "error": {"code": "bp_remove_failed", "message": f"Breakpoint remove failed: {raw}"},
            }
        return {
            "status": "ok", "action": "rbp",
            "summary": f"Breakpoint removed @ {args.address}",
            "details": {"address": args.address},
        }

    elif action == "run-to":
        # Set breakpoint -> resume -> wait -> halt -> check PC -> remove breakpoint
        telnet.send("halt")
        time.sleep(0.1)
        bp_raw = telnet.send(f"bp {args.address} {args.bp_length} hw")
        if has_command_error(bp_raw):
            return {
                "status": "error", "action": "run-to",
                "error": {"code": "bp_set_failed", "message": f"Breakpoint set failed: {bp_raw}"},
            }

        resume_raw = telnet.send("resume")
        if has_command_error(resume_raw):
            telnet.send(f"rbp {args.address}")
            return {
                "status": "error", "action": "run-to",
                "error": {"code": "resume_failed", "message": f"run-to resume failed: {resume_raw}"},
            }
        timeout_s = args.timeout_ms / 1000.0
        time.sleep(timeout_s)

        telnet.send("halt")
        time.sleep(0.1)
        pc_raw = telnet.send("reg pc")
        pc_regs = parse_reg_single(pc_raw)
        pc = pc_regs.get("pc", "")

        # Remove breakpoint
        telnet.send(f"rbp {args.address}")

        # Determine if hit (compare PC and breakpoint address)
        bp_hit = False
        if pc:
            bp_hit = int(pc, 16) == int(args.address, 16)

        if bp_hit:
            summary = f"Breakpoint hit @ {args.address}, PC={pc}"
        else:
            summary = f"Timed out without hitting breakpoint @ {args.address}, current PC={pc}"

        return {
            "status": "ok", "action": "run-to",
            "summary": summary,
            "details": {
                "bp_address": args.address,
                "bp_hit": bp_hit,
                "timeout_ms": args.timeout_ms,
                "pc": pc,
            },
        }

    return {"status": "error", "action": action, "error": {"code": "unknown_action", "message": f"Unknown action: {action}"}}


def print_result(result: dict, action: str):
    """Human-readable output in non-JSON mode."""
    if result["status"] == "ok":
        print(f"[{action}] {result.get('summary', 'Success')}", flush=True)
        details = result.get("details", {})

        if "registers" in details and action == "reg":
            core_regs = ["r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7",
                         "r8", "r9", "r10", "r11", "r12", "sp", "lr", "pc",
                         "xPSR", "msp", "psp", "primask", "control"]
            regs = details["registers"]
            for name in core_regs:
                if name in regs:
                    print(f"  {name:>10s} = {regs[name]}", flush=True)

        if "memory" in details:
            for m in details["memory"]:
                print(f"  {m['address']}: {m['data']}", flush=True)

        if "steps" in details:
            for s in details["steps"]:
                print(f"  step {s['step']}: PC={s['pc']}", flush=True)

        if "bp_hit" in details:
            hit = "Hit" if details["bp_hit"] else "Miss (timed out)"
            print(f"  Breakpoint: {details.get('bp_address', '?')} - {hit}", flush=True)
    else:
        err = result.get("error", {})
        print(f"[{action}] Failed - {err.get('message', 'Unknown error')}", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
