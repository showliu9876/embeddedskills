"""J-Link SWO observation wrapper.

Notes:
- SWO CLI tool names and arguments vary a lot between J-Link releases.
- This script hardcodes no specific viewer; supply the full command via
  --viewer-cmd or the swo_command entry in config.json.
"""

from __future__ import annotations

import argparse
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from jlink_runtime import (  # noqa: E402
    JLINK_SWO_CANDIDATES,
    resolve_path_candidate,
    default_config_path,
    emit_stream_record,
    get_state_entry,
    hidden_subprocess_kwargs,
    load_json_file,
    load_project_config,
    load_workspace_state,
    make_result,
    make_timing,
    normalize_path,
    now_iso,
    output_json,
    parameter_context,
    update_state_entry,
    workspace_root,
)


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


def _find_swo_viewer(config: dict) -> str:
    """Locate the SWO viewer next to the J-Link Commander binary, then on PATH."""
    jlink_exe = config.get("exe", "")
    if jlink_exe:
        exe_path = Path(str(jlink_exe)).expanduser()
        for name in JLINK_SWO_CANDIDATES:
            viewer = exe_path.with_name(name)
            if viewer.exists():
                return str(viewer)

    viewer_path, _ = resolve_path_candidate(JLINK_SWO_CANDIDATES)
    return viewer_path


def _auto_viewer_cmd(config: dict, project_config: dict, state: dict) -> list[str]:
    viewer = _find_swo_viewer(config)
    if not viewer:
        return []

    last_debug = get_state_entry(state, "last_debug")
    last_flash = get_state_entry(state, "last_flash")
    device = project_config.get("device") or last_debug.get("device") or last_flash.get("device")
    if not device:
        return []

    # Supported arguments differ widely between JLinkSWOViewerCL releases.
    # Fall back to the safest minimal command (device only) so an incompatible
    # -itf/-speed does not fail the whole run.
    return [viewer, "-device", str(device)]


def main() -> None:
    parser = argparse.ArgumentParser(description="J-Link SWO output capture")
    parser.add_argument("--viewer-cmd", nargs="+", default=None, help="full SWO capture command, e.g. the JLinkSWOViewerCLExe invocation")
    parser.add_argument("--duration", type=float, default=0, help="capture duration in seconds, 0 = run until stopped")
    parser.add_argument("--workspace", default=None, help="workspace root, defaults to cwd")
    parser.add_argument("--config", default=None, help="skill config.json path")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args, passthrough = parser.parse_known_args()

    started_at = now_iso()
    started_ts = time.time()
    workspace = workspace_root(args.workspace)
    config_path = normalize_path(args.config or str(default_config_path(__file__)))
    config = load_json_file(config_path)
    project_config = load_project_config(str(workspace))
    state = load_workspace_state(str(workspace))
    viewer_cmd = list(args.viewer_cmd or config.get("swo_command") or _auto_viewer_cmd(config, project_config, state))
    viewer_cmd.extend(passthrough)

    if not viewer_cmd:
        message = "SWO viewer command missing, supply it via --viewer-cmd or jlink/config.json.swo_command"
        result = make_result(
            status="error",
            action="swo",
            summary=message,
            details={},
            context=parameter_context(provider="jlink", workspace=str(workspace), config_path=config_path),
            error={"code": "missing_viewer_cmd", "message": message},
            timing=make_timing(started_at, (time.time() - started_ts) * 1000),
        )
        if args.as_json:
            output_json(result)
        else:
            print(f"Error: {message}", file=sys.stderr)
        sys.exit(1)

    proc = None
    try:
        proc = subprocess.Popen(
            viewer_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(workspace),
            **hidden_subprocess_kwargs(),
        )
        line_queue = start_stream_reader(proc.stdout)
        update_state_entry(
            "last_observe",
            {
                "provider": "jlink",
                "action": "swo",
                "channel_type": "swo",
                "stream_type": "text",
                "source": "jlink",
            },
            str(workspace),
        )

        while True:
            if args.duration > 0 and (time.time() - started_ts) >= args.duration:
                break
            try:
                line = line_queue.get(timeout=0.1)
            except queue.Empty:
                if proc.poll() is not None:
                    break
                continue
            if line is None:
                if proc.poll() is not None:
                    break
                continue
            emit_stream_record(source="jlink", channel_type="swo", text=line, as_json=args.as_json, stream_type="text")

    except FileNotFoundError:
        message = f"failed to launch SWO viewer: {viewer_cmd[0]}"
        result = make_result(
            status="error",
            action="swo",
            summary=message,
            details={"viewer_cmd": viewer_cmd},
            context=parameter_context(provider="jlink", workspace=str(workspace), config_path=config_path),
            error={"code": "viewer_not_found", "message": message},
            timing=make_timing(started_at, (time.time() - started_ts) * 1000),
        )
        if args.as_json:
            output_json(result)
        else:
            print(f"Error: {message}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass
    finally:
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                pass
            if proc.poll() is None and sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    **hidden_subprocess_kwargs(),
                )
            elif proc.poll() is None:
                proc.kill()


if __name__ == "__main__":
    main()
