#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any


STATE_DIR_NAME = ".embeddedskills"
STATE_FILE_NAME = "state.json"
SKILL_NAME = "terminal"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def workspace_root(workspace: str | None = None) -> Path:
    if workspace:
        return Path(workspace).expanduser().resolve()
    return Path.cwd().resolve()


def state_path(workspace: str | None = None) -> Path:
    return workspace_root(workspace) / STATE_DIR_NAME / STATE_FILE_NAME


def logs_dir(workspace: str | None = None) -> Path:
    return workspace_root(workspace) / STATE_DIR_NAME / "logs" / SKILL_NAME


def workspace_relative(path: Path, workspace: str | None = None) -> str:
    ws = workspace_root(workspace)
    try:
        return Path(os.path.relpath(path.resolve(), ws)).as_posix()
    except ValueError:
        return str(path)


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state(workspace: str | None = None) -> dict[str, Any]:
    return load_json_file(state_path(workspace))


def save_state(workspace: str | None, state: dict[str, Any]) -> None:
    save_json_file(state_path(workspace), state)


def sessions_from_state(workspace: str | None = None) -> dict[str, Any]:
    state = load_state(workspace)
    sessions = state.get("terminal_sessions", {})
    return sessions if isinstance(sessions, dict) else {}


def update_session(workspace: str | None, session_id: str, record: dict[str, Any]) -> None:
    state = load_state(workspace)
    sessions = state.setdefault("terminal_sessions", {})
    sessions[session_id] = record
    save_state(workspace, state)


def remove_session(workspace: str | None, session_id: str) -> None:
    state = load_state(workspace)
    sessions = state.get("terminal_sessions", {})
    if isinstance(sessions, dict) and session_id in sessions:
        del sessions[session_id]
        save_state(workspace, state)


def json_result(status: str, action: str, summary: str = "", **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"status": status, "action": action}
    if summary:
        result["summary"] = summary
    result.update(extra)
    return result


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def error_result(action: str, code: str, message: str, **details: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if details:
        payload["details"] = details
    return json_result("error", action, error=payload)


def sanitize_session_id(value: str | None, backend: str) -> str:
    if value:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
        return cleaned.strip("-") or f"{backend}-{int(time.time())}"
    return f"{backend}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def find_free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def encode_spec(spec: dict[str, Any]) -> str:
    raw = json.dumps(spec, ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_spec(encoded: str) -> dict[str, Any]:
    raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
    return json.loads(raw.decode("utf-8"))


class OutputBuffer:
    def __init__(self, max_bytes: int = 1024 * 1024) -> None:
        self._data = bytearray()
        self._lock = threading.Lock()
        self._max_bytes = max_bytes

    def append(self, data: bytes) -> None:
        if not data:
            return
        with self._lock:
            self._data.extend(data)
            if len(self._data) > self._max_bytes:
                del self._data[: len(self._data) - self._max_bytes]

    def drain(self) -> bytes:
        with self._lock:
            data = bytes(self._data)
            self._data.clear()
            return data

    def has_data(self) -> bool:
        with self._lock:
            return bool(self._data)


class ProcessTransport:
    def __init__(self, argv: list[str], cwd: str | None = None) -> None:
        self.argv = argv
        self.cwd = cwd
        self.proc: subprocess.Popen[bytes] | None = None

    def open(self, buffer: OutputBuffer) -> None:
        flags = 0
        kwargs: dict[str, Any] = {}
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            kwargs["start_new_session"] = True
        self.proc = subprocess.Popen(
            self.argv,
            cwd=self.cwd or None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            creationflags=flags,
            **kwargs,
        )
        threading.Thread(target=self._reader, args=(buffer,), daemon=True).start()

    def _reader(self, buffer: OutputBuffer) -> None:
        assert self.proc is not None
        assert self.proc.stdout is not None
        while True:
            chunk = self.proc.stdout.read(4096)
            if not chunk:
                break
            buffer.append(chunk)

    def write(self, data: bytes) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise RuntimeError("process stdin is not available")
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def status(self) -> dict[str, Any]:
        if self.proc is None:
            return {"alive": False}
        code = self.proc.poll()
        return {"alive": code is None, "pid": self.proc.pid, "exit_code": code}

    def close(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class SerialTransport:
    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec
        self.ser: Any = None
        self._closed = threading.Event()

    def open(self, buffer: OutputBuffer) -> None:
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("pyserial is required: python -m pip install pyserial") from exc
        self.ser = serial.Serial(
            port=self.spec["port"],
            baudrate=int(self.spec.get("baudrate") or 115200),
            bytesize=int(self.spec.get("bytesize") or 8),
            parity=str(self.spec.get("parity") or "N").upper()[0],
            stopbits=float(self.spec.get("stopbits") or 1),
            timeout=0.1,
        )
        threading.Thread(target=self._reader, args=(buffer,), daemon=True).start()

    def _reader(self, buffer: OutputBuffer) -> None:
        while not self._closed.is_set():
            try:
                chunk = self.ser.read(4096)
            except Exception as exc:
                buffer.append(f"\n[serial read error] {exc}\n".encode("utf-8", errors="replace"))
                break
            if chunk:
                buffer.append(chunk)

    def write(self, data: bytes) -> None:
        if self.ser is None:
            raise RuntimeError("serial port is not open")
        self.ser.write(data)
        self.ser.flush()

    def status(self) -> dict[str, Any]:
        return {"alive": bool(self.ser and self.ser.is_open), "port": self.spec.get("port")}

    def close(self) -> None:
        self._closed.set()
        if self.ser is not None and self.ser.is_open:
            self.ser.close()


class TerminalServer:
    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec
        self.buffer = OutputBuffer()
        self.stop_event = threading.Event()
        self.transport = self._create_transport(spec)

    def _create_transport(self, spec: dict[str, Any]) -> Any:
        backend = spec["backend"]
        if backend == "serial":
            return SerialTransport(spec)
        if backend == "ssh":
            cmd = ["ssh", "-tt"]
            if spec.get("accept_new_host_key"):
                cmd.extend(["-o", "StrictHostKeyChecking=accept-new"])
            if spec.get("known_hosts_file"):
                cmd.extend(["-o", f"UserKnownHostsFile={spec['known_hosts_file']}"])
            cmd.append(spec["host"])
            return ProcessTransport(cmd)
        if backend == "local":
            shell = spec.get("shell")
            if shell:
                cmd = [shell]
            elif os.name == "nt":
                cmd = ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass"]
            else:
                cmd = [os.environ.get("SHELL") or "/bin/sh"]
            return ProcessTransport(cmd, cwd=spec.get("cwd"))
        raise RuntimeError(f"unsupported backend: {backend}")

    def open(self) -> None:
        self.transport.open(self.buffer)

    def close(self) -> None:
        self.transport.close()

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        command = request.get("command")
        if command == "status":
            return json_result("ok", "status", "session online", details={**self.spec, **self.transport.status()})
        if command == "read":
            timeout = float(request.get("timeout") or 0)
            deadline = time.monotonic() + max(0.0, timeout)
            while not self.buffer.has_data() and time.monotonic() < deadline:
                time.sleep(0.05)
            data = self.buffer.drain()
            encoding = request.get("encoding") or self.spec.get("encoding") or "utf-8"
            text = data.decode(encoding, errors="replace")
            return json_result(
                "ok",
                "read",
                f"read {len(data)} bytes",
                details={"session": self.spec["session_id"], "bytes": len(data), "text": text},
            )
        if command == "send":
            data = request.get("data", "")
            payload = bytes.fromhex(data) if request.get("hex") else str(data).encode(request.get("encoding") or "utf-8")
            self.transport.write(payload)
            return json_result(
                "ok",
                "send",
                f"wrote {len(payload)} bytes",
                details={"session": self.spec["session_id"], "bytes": len(payload)},
            )
        if command == "stop":
            self.stop_event.set()
            return json_result("ok", "stop", "session stopped", details={"session": self.spec["session_id"]})
        return error_result("request", "unknown_command", f"unknown command: {command}")


def serve(spec: dict[str, Any]) -> int:
    server = TerminalServer(spec)
    server.open()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", int(spec["tcp_port"])))
        sock.listen(8)
        sock.settimeout(0.2)
        while not server.stop_event.is_set():
            try:
                conn, _addr = sock.accept()
            except socket.timeout:
                continue
            with conn:
                request = read_socket_json(conn)
                try:
                    response = server.handle(request)
                except Exception as exc:
                    response = error_result("request", "request_failed", str(exc))
                conn.sendall(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")
    server.close()
    return 0


def read_socket_json(conn: socket.socket) -> dict[str, Any]:
    chunks: list[bytes] = []
    while True:
        data = conn.recv(65536)
        if not data:
            break
        chunks.append(data)
        if b"\n" in data:
            break
    raw = b"".join(chunks).split(b"\n", 1)[0]
    return json.loads(raw.decode("utf-8"))


def request_session(record: dict[str, Any], payload: dict[str, Any], timeout: float = 3.0) -> dict[str, Any]:
    try:
        with socket.create_connection(("127.0.0.1", int(record["tcp_port"])), timeout=timeout) as sock:
            sock.sendall(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
            chunks: list[bytes] = []
            while True:
                data = sock.recv(65536)
                if not data:
                    break
                chunks.append(data)
                if b"\n" in data:
                    break
        raw = b"".join(chunks).split(b"\n", 1)[0]
        return json.loads(raw.decode("utf-8"))
    except OSError as exc:
        return error_result("request", "session_unreachable", "session unreachable, may have exited", reason=str(exc))


def command_start(args: argparse.Namespace) -> dict[str, Any]:
    session_id = sanitize_session_id(args.name, args.backend)
    sessions = sessions_from_state(args.workspace)
    if session_id in sessions:
        return error_result("start", "session_exists", f"session already exists: {session_id}")

    if args.backend == "serial" and not args.port:
        return error_result("start", "missing_port", "--port is required for serial backend")
    if args.backend == "ssh" and not args.host:
        return error_result("start", "missing_host", "--host is required for ssh backend")
    if args.backend == "ssh" and shutil.which("ssh") is None:
        return error_result("start", "ssh_not_found", "OpenSSH client ssh not found")

    tcp_port = find_free_tcp_port()
    log_dir = logs_dir(args.workspace)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{session_id}.log"
    spec = {
        "session_id": session_id,
        "backend": args.backend,
        "tcp_port": tcp_port,
        "encoding": args.encoding or ("mbcs" if args.backend == "local" and os.name == "nt" else "utf-8"),
        "started_at": now_iso(),
    }
    if args.backend == "serial":
        spec.update({
            "port": args.port,
            "baudrate": args.baudrate,
            "bytesize": args.bytesize,
            "parity": args.parity,
            "stopbits": args.stopbits,
        })
    elif args.backend == "ssh":
        spec.update({
            "host": args.host,
            "accept_new_host_key": args.accept_new_host_key,
            "known_hosts_file": args.known_hosts_file,
        })
    elif args.backend == "local":
        spec.update({"shell": args.shell, "cwd": str(Path(args.cwd).resolve()) if args.cwd else None})

    cmd = [sys.executable, str(Path(__file__).resolve()), "_serve", encode_spec(spec)]
    creationflags = 0
    popen_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True
    with log_file.open("ab") as log:
        proc = subprocess.Popen(
            cmd,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            **popen_kwargs,
        )

    record = {**spec, "pid": proc.pid, "log_file": workspace_relative(log_file, args.workspace)}
    for _ in range(30):
        time.sleep(0.1)
        response = request_session(record, {"command": "status"}, timeout=0.2)
        if response.get("status") == "ok":
            update_session(args.workspace, session_id, record)
            return json_result("ok", "start", f"started {args.backend} session: {session_id}", details=record)
        if proc.poll() is not None:
            break
    return error_result("start", "start_failed", "failed to start background terminal session", log_file=str(log_file))


def command_list(args: argparse.Namespace) -> dict[str, Any]:
    sessions = sessions_from_state(args.workspace)
    items = []
    for session_id, record in sessions.items():
        response = request_session(record, {"command": "status"}, timeout=0.2)
        items.append({
            "session": session_id,
            "alive": response.get("status") == "ok",
            "record": record,
            "status": response.get("details", {}),
        })
    return json_result("ok", "list", f"found {len(items)} session(s)", details={"sessions": items})


def command_status(args: argparse.Namespace) -> dict[str, Any]:
    record = sessions_from_state(args.workspace).get(args.session)
    if not record:
        return error_result("status", "session_not_found", f"session not found: {args.session}")
    return request_session(record, {"command": "status"}, timeout=args.timeout)


def command_send(args: argparse.Namespace) -> dict[str, Any]:
    record = sessions_from_state(args.workspace).get(args.session)
    if not record:
        return error_result("send", "session_not_found", f"session not found: {args.session}")
    data = args.data
    if args.hex:
        if args.crlf:
            data += " 0d 0a"
        elif args.lf:
            data += " 0a"
    elif args.crlf:
        data += "\r\n"
    elif args.lf:
        data += "\n"
    payload = {"command": "send", "data": data, "hex": args.hex, "encoding": args.encoding or record.get("encoding")}
    return request_session(record, payload, timeout=args.timeout)


def command_read(args: argparse.Namespace) -> dict[str, Any]:
    record = sessions_from_state(args.workspace).get(args.session)
    if not record:
        return error_result("read", "session_not_found", f"session not found: {args.session}")
    payload = {"command": "read", "timeout": args.timeout, "encoding": args.encoding or record.get("encoding")}
    return request_session(record, payload, timeout=max(1.0, args.timeout + 1.0))


def command_stop(args: argparse.Namespace) -> dict[str, Any]:
    record = sessions_from_state(args.workspace).get(args.session)
    if not record:
        return error_result("stop", "session_not_found", f"session not found: {args.session}")
    response = request_session(record, {"command": "stop"}, timeout=args.timeout)
    remove_session(args.workspace, args.session)
    return response


def command_attach(args: argparse.Namespace) -> int:
    record = sessions_from_state(args.workspace).get(args.session)
    if not record:
        print_json(error_result("attach", "session_not_found", f"session not found: {args.session}"))
        return 1
    stop_event = threading.Event()

    def reader() -> None:
        while not stop_event.is_set():
            response = request_session(record, {"command": "read", "timeout": 0.2, "encoding": args.encoding or record.get("encoding")}, timeout=1.0)
            text = response.get("details", {}).get("text", "") if response.get("status") == "ok" else ""
            if text:
                print(text, end="", flush=True)
            time.sleep(0.05)

    threading.Thread(target=reader, daemon=True).start()
    try:
        for line in sys.stdin:
            suffix = "\r\n" if args.crlf else "\n"
            request_session(record, {"command": "send", "data": line.rstrip("\r\n") + suffix, "encoding": args.encoding or record.get("encoding")})
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bidirectional interactive terminal session management")
    sub = parser.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start", help="Start background interactive session")
    p_start.add_argument("backend", choices=["serial", "ssh", "local"])
    p_start.add_argument("--name")
    p_start.add_argument("--workspace")
    p_start.add_argument("--encoding")
    p_start.add_argument("--port")
    p_start.add_argument("--baudrate", type=int, default=115200)
    p_start.add_argument("--bytesize", type=int, default=8)
    p_start.add_argument("--parity", default="none", choices=["none", "even", "odd", "mark", "space"])
    p_start.add_argument("--stopbits", type=float, default=1)
    p_start.add_argument("--host")
    p_start.add_argument("--accept-new-host-key", action="store_true")
    p_start.add_argument("--known-hosts-file")
    p_start.add_argument("--shell")
    p_start.add_argument("--cwd")

    p_list = sub.add_parser("list", help="List existing sessions")
    p_list.add_argument("--workspace")

    p_status = sub.add_parser("status", help="Query session status")
    p_status.add_argument("session")
    p_status.add_argument("--workspace")
    p_status.add_argument("--timeout", type=float, default=1.0)

    p_send = sub.add_parser("send", help="Send data to session")
    p_send.add_argument("session")
    p_send.add_argument("data")
    p_send.add_argument("--workspace")
    p_send.add_argument("--encoding")
    p_send.add_argument("--timeout", type=float, default=3.0)
    p_send.add_argument("--hex", action="store_true")
    p_send.add_argument("--crlf", action="store_true")
    p_send.add_argument("--lf", action="store_true")

    p_read = sub.add_parser("read", help="Read and drain output buffer")
    p_read.add_argument("session")
    p_read.add_argument("--workspace")
    p_read.add_argument("--encoding")
    p_read.add_argument("--timeout", type=float, default=0.0)

    p_attach = sub.add_parser("attach", help="Attach to session in foreground line mode")
    p_attach.add_argument("session")
    p_attach.add_argument("--workspace")
    p_attach.add_argument("--encoding")
    p_attach.add_argument("--crlf", action="store_true")

    p_stop = sub.add_parser("stop", help="Stop session")
    p_stop.add_argument("session")
    p_stop.add_argument("--workspace")
    p_stop.add_argument("--timeout", type=float, default=3.0)

    p_serve = sub.add_parser("_serve")
    p_serve.add_argument("spec")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "_serve":
        return serve(decode_spec(args.spec))
    if args.command == "attach":
        return command_attach(args)

    handlers = {
        "start": command_start,
        "list": command_list,
        "status": command_status,
        "send": command_send,
        "read": command_read,
        "stop": command_stop,
    }
    result = handlers[args.command](args)
    print_json(result)
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
