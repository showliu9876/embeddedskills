"""workflow thin orchestration execution layer."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from workflow_runtime import (  # noqa: E402
    get_state_entry,
    hidden_subprocess_kwargs,
    load_effective_project_config,
    load_workspace_state,
    make_result,
    make_timing,
    now_iso,
    output_json,
    parameter_context,
    save_project_config,
    update_state_entry,
    workspace_root,
)


PYTHON_EXE = sys.executable


def _with_backend(result: dict, backend: str) -> dict:
    details = dict(result.get("details") or {})
    details["backend"] = backend
    result["details"] = details
    return result


def _workflow_state_key(action: str) -> str:
    return f"last_workflow_{action.replace('-', '_')}"


def _workflow_state_details(action: str, result: dict) -> dict:
    details = result.get("details") or {}
    if action in ("build", "observe"):
        return {"backend": details.get("backend"), "summary": result.get("summary", "")}
    if action == "build-flash":
        build = details.get("build") or {}
        flash = details.get("flash") or {}
        return {
            "summary": result.get("summary", ""),
            "build_backend": (build.get("details") or {}).get("backend"),
            "flash_backend": (flash.get("details") or {}).get("backend"),
        }
    if action == "build-debug":
        build = details.get("build") or {}
        debug = details.get("debug") or {}
        return {
            "summary": result.get("summary", ""),
            "build_backend": (build.get("details") or {}).get("backend"),
            "debug_backend": (debug.get("details") or {}).get("backend"),
        }
    return {"summary": result.get("summary", "")}


def discover_projects(root: Path) -> dict:
    return {
        "keil": sorted(str(path.resolve()) for path in root.rglob("*.uvprojx")),
        "gcc": sorted(str(path.parent.resolve()) for path in root.rglob("CMakePresets.json")),
        "eide": sorted(str(path.parents[1].resolve()) for path in root.rglob(".eide/eide.yml")),
    }


def _single_or_error(items: list[str], label: str) -> tuple[str | None, dict | None]:
    if len(items) == 1:
        return items[0], None
    if len(items) > 1:
        return None, {"code": "multiple_candidates", "message": f"Found multiple {label}, please specify explicitly in config or command", "candidates": items}
    return None, {"code": "not_found", "message": f"No available {label} found", "candidates": []}


def _is_openocd_ready(full_config: dict) -> bool:
    openocd_cfg = full_config.get("openocd", {})
    return bool(openocd_cfg.get("board") or (openocd_cfg.get("interface") and openocd_cfg.get("target")))


def _is_jlink_ready(full_config: dict) -> bool:
    return bool((full_config.get("jlink") or {}).get("device"))


def _is_probe_rs_ready(full_config: dict) -> bool:
    return bool((full_config.get("probe-rs") or {}).get("chip"))


def _select_backend(explicit: str | None, preferred: str | None, ready_backends: list[str], action: str) -> tuple[str | None, dict | None]:
    backend = explicit or preferred or "auto"
    if backend != "auto":
        return backend, None
    if len(ready_backends) == 1:
        return ready_backends[0], None
    if len(ready_backends) > 1:
        return None, {
            "code": "multiple_backend_candidates",
            "message": f"Multiple available backends exist for {action}, please specify explicitly via CLI or workflow.preferred_*",
            "candidates": ready_backends,
        }
    return None, {
        "code": "no_backend_available",
        "message": f"No available backend found for {action}, please configure jlink, openocd, or probe-rs",
        "candidates": [],
    }


def run_json(cmd: list[str], workdir: Path) -> dict:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(workdir),
        encoding="utf-8",
        errors="replace",
        **hidden_subprocess_kwargs(),
    )
    payload = (proc.stdout or proc.stderr).strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return {
            "status": "error",
            "action": "subprocess",
            "error": {"code": "invalid_json", "message": payload[-500:] or "Subprocess did not return JSON"},
        }


def select_build_backend(workflow_config: dict, discovery: dict, explicit: str | None) -> tuple[str | None, dict | None]:
    backend = explicit or workflow_config.get("preferred_build") or "auto"
    if backend != "auto":
        return backend, None
    candidates = [name for name in ("keil", "gcc", "eide") if discovery[name]]
    if len(candidates) == 1:
        return candidates[0], None
    if len(candidates) > 1:
        return None, {"code": "multiple_build_backends", "message": "Multiple build backends discovered (Keil/GCC/EIDE), please specify build backend explicitly", "candidates": candidates}
    return None, {"code": "no_build_backend", "message": "No buildable project found", "candidates": []}


def build_eide_project(workspace: Path, full_config: dict, discovery: dict) -> dict:
    eide_config = full_config.get("eide", {})
    project = eide_config.get("project")
    if not project:
        project, error = _single_or_error(discovery["eide"], "EIDE projects")
        if error:
            return {"status": "error", "action": "build", "error": error}

    config_name = eide_config.get("config")
    if not config_name:
        return {"status": "error", "action": "build", "error": {"code": "missing_config", "message": "Build config name must be configured in eide section of .embeddedskills/config.json"}}

    cmd = [
        PYTHON_EXE,
        str(ROOT_DIR / "eide" / "scripts" / "eide_build.py"),
        "build",
        "--workspace",
        str(workspace),
        "--project",
        project,
        "--config",
        config_name,
        "--json",
    ]
    log_dir = eide_config.get("log_dir")
    if log_dir:
        cmd.extend(["--log-dir", log_dir])
    return _with_backend(run_json(cmd, workspace), "eide")


def build_project(workspace: Path, full_config: dict, discovery: dict, backend: str | None) -> dict:
    workflow_config = full_config.get("workflow", {})
    selected, error = select_build_backend(workflow_config, discovery, backend)
    if error:
        return {"status": "error", "action": "build", "error": error}

    if selected == "keil":
        keil_config = full_config.get("keil", {})
        project = keil_config.get("project")
        if not project:
            project, error = _single_or_error(discovery["keil"], "Keil projects")
            if error:
                return {"status": "error", "action": "build", "error": error}
        cmd = [
            PYTHON_EXE,
            str(ROOT_DIR / "keil" / "scripts" / "keil_build.py"),
            "build",
            "--workspace",
            str(workspace),
            "--project",
            project,
            "--json",
        ]
        target = keil_config.get("target")
        uv4_exe = keil_config.get("uv4_exe")
        if target:
            cmd.extend(["--target", target])
        if uv4_exe:
            cmd.extend(["--uv4", uv4_exe])
        return _with_backend(run_json(cmd, workspace), selected)

    if selected == "eide":
        return build_eide_project(workspace, full_config, discovery)

    gcc_config = full_config.get("gcc", {})
    project = gcc_config.get("project")
    if not project:
        project, error = _single_or_error(discovery["gcc"], "GCC projects")
        if error:
            return {"status": "error", "action": "build", "error": error}
    preset = gcc_config.get("preset")
    if not preset:
        return {"status": "error", "action": "build", "error": {"code": "missing_preset", "message": "Preset must be configured in gcc section of .embeddedskills/config.json"}}
    cmd = [
        PYTHON_EXE,
        str(ROOT_DIR / "gcc" / "scripts" / "gcc_build.py"),
        "build",
        "--workspace",
        str(workspace),
        "--project",
        project,
        "--preset",
        preset,
        "--json",
    ]
    cmake_exe = gcc_config.get("cmake_exe")
    if cmake_exe:
        cmd.extend(["--cmake", cmake_exe])
    return _with_backend(run_json(cmd, workspace), selected)


def flash_project(workspace: Path, full_config: dict, state: dict, explicit: str | None) -> dict:
    workflow_config = full_config.get("workflow", {})
    selected, error = _select_backend(
        explicit,
        workflow_config.get("preferred_flash"),
        [name for name, ready in (("openocd", _is_openocd_ready(full_config)), ("jlink", _is_jlink_ready(full_config)), ("probe-rs", _is_probe_rs_ready(full_config))) if ready],
        "flash",
    )
    if error:
        return {"status": "error", "action": "flash", "error": error}

    last_build = get_state_entry(state, "last_build")
    artifacts = last_build.get("artifacts", {})
    flash_file = last_build.get("flash_file") or artifacts.get("flash_file")
    if not flash_file:
        return {"status": "error", "action": "flash", "error": {"code": "missing_last_build", "message": "last_build.flash_file not found, please run workflow build first"}}

    if selected == "openocd":
        openocd_cfg = full_config.get("openocd", {})
        cmd = [
            PYTHON_EXE,
            str(ROOT_DIR / "openocd" / "scripts" / "openocd_run.py"),
            "flash",
            "--workspace",
            str(workspace),
            "--file",
            flash_file,
            "--json",
        ]
        if openocd_cfg.get("board"):
            cmd.extend(["--board", openocd_cfg["board"]])
        if openocd_cfg.get("interface"):
            cmd.extend(["--interface", openocd_cfg["interface"]])
        if openocd_cfg.get("target"):
            cmd.extend(["--target", openocd_cfg["target"]])
        return _with_backend(run_json(cmd, workspace), "openocd")

    if selected == "jlink":
        jlink_cfg = full_config.get("jlink", {})
        if not jlink_cfg.get("device"):
            return {"status": "error", "action": "flash", "error": {"code": "missing_device", "message": "device must be configured in jlink section of .embeddedskills/config.json for jlink flash"}}
        cmd = [
            PYTHON_EXE,
            str(ROOT_DIR / "jlink" / "scripts" / "jlink_exec.py"),
            "flash",
            "--file",
            flash_file,
            "--device",
            jlink_cfg["device"],
            "--json",
        ]
        if jlink_cfg.get("interface"):
            cmd.extend(["--interface", jlink_cfg["interface"]])
        if jlink_cfg.get("speed"):
            cmd.extend(["--speed", str(jlink_cfg["speed"])])
        return _with_backend(run_json(cmd, workspace), "jlink")

    probe_rs_cfg = full_config.get("probe-rs", {})
    if not probe_rs_cfg.get("chip"):
        return {"status": "error", "action": "flash", "error": {"code": "missing_chip", "message": "chip must be configured in probe-rs section of .embeddedskills/config.json for probe-rs flash"}}
    cmd = [
        PYTHON_EXE,
        str(ROOT_DIR / "probe-rs" / "scripts" / "probe_rs_exec.py"),
        "flash",
        "--workspace",
        str(workspace),
        "--file",
        flash_file,
        "--chip",
        probe_rs_cfg["chip"],
        "--json",
    ]
    if probe_rs_cfg.get("protocol"):
        cmd.extend(["--protocol", probe_rs_cfg["protocol"]])
    if probe_rs_cfg.get("probe"):
        cmd.extend(["--probe", probe_rs_cfg["probe"]])
    if probe_rs_cfg.get("speed"):
        cmd.extend(["--speed", str(probe_rs_cfg["speed"])])
    if probe_rs_cfg.get("connect_under_reset"):
        cmd.append("--connect-under-reset")
    return _with_backend(run_json(cmd, workspace), "probe-rs")


def debug_project(workspace: Path, full_config: dict, state: dict, explicit: str | None) -> dict:
    workflow_config = full_config.get("workflow", {})
    selected, error = _select_backend(
        explicit,
        workflow_config.get("preferred_debug"),
        [name for name, ready in (("openocd", _is_openocd_ready(full_config)), ("jlink", _is_jlink_ready(full_config)), ("probe-rs", _is_probe_rs_ready(full_config))) if ready],
        "debug",
    )
    if error:
        return {"status": "error", "action": "build-debug", "error": error}

    last_build = get_state_entry(state, "last_build")
    artifacts = last_build.get("artifacts", {})
    debug_file = last_build.get("debug_file") or artifacts.get("debug_file")
    if not debug_file:
        return {"status": "error", "action": "build-debug", "error": {"code": "missing_last_build", "message": "last_build.debug_file not found, please run workflow build first"}}

    if selected == "openocd":
        openocd_cfg = full_config.get("openocd", {})
        cmd = [
            PYTHON_EXE,
            str(ROOT_DIR / "openocd" / "scripts" / "openocd_gdb.py"),
            "crash-report",
            "--workspace",
            str(workspace),
            "--elf",
            debug_file,
            "--json",
        ]
        if openocd_cfg.get("board"):
            cmd.extend(["--board", openocd_cfg["board"]])
        if openocd_cfg.get("interface"):
            cmd.extend(["--interface", openocd_cfg["interface"]])
        if openocd_cfg.get("target"):
            cmd.extend(["--target", openocd_cfg["target"]])
        if openocd_cfg.get("gdb_exe"):
            cmd.extend(["--gdb-exe", openocd_cfg["gdb_exe"]])
        return _with_backend(run_json(cmd, workspace), "openocd")

    if selected == "jlink":
        jlink_cfg = full_config.get("jlink", {})
        if not jlink_cfg.get("device"):
            return {"status": "error", "action": "build-debug", "error": {"code": "missing_device", "message": "device must be configured in jlink section of .embeddedskills/config.json for jlink gdb"}}
        cmd = [
            PYTHON_EXE,
            str(ROOT_DIR / "jlink" / "scripts" / "jlink_gdb.py"),
            "crash-report",
            "--workspace",
            str(workspace),
            "--elf",
            debug_file,
            "--device",
            jlink_cfg["device"],
            "--json",
        ]
        if jlink_cfg.get("interface"):
            cmd.extend(["--interface", jlink_cfg["interface"]])
        if jlink_cfg.get("speed"):
            cmd.extend(["--speed", str(jlink_cfg["speed"])])
        return _with_backend(run_json(cmd, workspace), "jlink")

    probe_rs_cfg = full_config.get("probe-rs", {})
    if not probe_rs_cfg.get("chip"):
        return {"status": "error", "action": "build-debug", "error": {"code": "missing_chip", "message": "chip must be configured in probe-rs section of .embeddedskills/config.json for probe-rs gdb"}}
    cmd = [
        PYTHON_EXE,
        str(ROOT_DIR / "probe-rs" / "scripts" / "probe_rs_gdb.py"),
        "crash-report",
        "--workspace",
        str(workspace),
        "--elf",
        debug_file,
        "--chip",
        probe_rs_cfg["chip"],
        "--json",
    ]
    if probe_rs_cfg.get("protocol"):
        cmd.extend(["--protocol", probe_rs_cfg["protocol"]])
    if probe_rs_cfg.get("probe"):
        cmd.extend(["--probe", probe_rs_cfg["probe"]])
    if probe_rs_cfg.get("speed"):
        cmd.extend(["--speed", str(probe_rs_cfg["speed"])])
    if probe_rs_cfg.get("connect_under_reset"):
        cmd.append("--connect-under-reset")
    return _with_backend(run_json(cmd, workspace), "probe-rs")


def observe_project(workspace: Path, full_config: dict, explicit: str | None) -> dict:
    workflow_config = full_config.get("workflow", {})
    selected, error = _select_backend(
        explicit,
        workflow_config.get("preferred_observe"),
        [name for name, ready in (("openocd", _is_openocd_ready(full_config)), ("jlink", _is_jlink_ready(full_config)), ("probe-rs", _is_probe_rs_ready(full_config))) if ready],
        "observe",
    )
    if error:
        return {"status": "error", "action": "observe", "error": error}

    if selected == "openocd":
        openocd_cfg = full_config.get("openocd", {})
        cmd = [
            PYTHON_EXE,
            str(ROOT_DIR / "openocd" / "scripts" / "openocd_semihosting.py"),
            "--workspace",
            str(workspace),
            "--json",
        ]
        if openocd_cfg.get("board"):
            cmd.extend(["--board", openocd_cfg["board"]])
        if openocd_cfg.get("interface"):
            cmd.extend(["--interface", openocd_cfg["interface"]])
        if openocd_cfg.get("target"):
            cmd.extend(["--target", openocd_cfg["target"]])
        return {"status": "ok", "action": "observe", "summary": "Generated openocd semihosting observation command", "details": {"command": cmd, "backend": "openocd"}}

    if selected == "jlink":
        jlink_cfg = full_config.get("jlink", {})
        if not jlink_cfg.get("device"):
            return {"status": "error", "action": "observe", "error": {"code": "missing_device", "message": "device must be configured in jlink section of .embeddedskills/config.json for jlink observation"}}
        cmd = [
            PYTHON_EXE,
            str(ROOT_DIR / "jlink" / "scripts" / "jlink_rtt.py"),
            "--workspace",
            str(workspace),
            "--device",
            jlink_cfg["device"],
            "--json",
        ]
        return {"status": "ok", "action": "observe", "summary": "Generated jlink RTT observation command", "details": {"command": cmd, "backend": "jlink"}}

    probe_rs_cfg = full_config.get("probe-rs", {})
    if not probe_rs_cfg.get("chip"):
        return {"status": "error", "action": "observe", "error": {"code": "missing_chip", "message": "chip must be configured in probe-rs section of .embeddedskills/config.json for probe-rs observation"}}
    cmd = [
        PYTHON_EXE,
        str(ROOT_DIR / "probe-rs" / "scripts" / "probe_rs_rtt.py"),
        "--workspace",
        str(workspace),
        "--chip",
        probe_rs_cfg["chip"],
        "--json",
    ]
    if probe_rs_cfg.get("protocol"):
        cmd.extend(["--protocol", probe_rs_cfg["protocol"]])
    if probe_rs_cfg.get("probe"):
        cmd.extend(["--probe", probe_rs_cfg["probe"]])
    if probe_rs_cfg.get("speed"):
        cmd.extend(["--speed", str(probe_rs_cfg["speed"])])
    if probe_rs_cfg.get("connect_under_reset"):
        cmd.append("--connect-under-reset")
    return {"status": "ok", "action": "observe", "summary": "Generated probe-rs RTT observation command", "details": {"command": cmd, "backend": "probe-rs"}}


def diagnose(workspace: Path, full_config: dict, discovery: dict, state: dict) -> dict:
    workflow_config = full_config.get("workflow", {})
    hints = []
    if not discovery["keil"] and not discovery["gcc"] and not discovery["eide"]:
        hints.append("No Keil, GCC, or EIDE project found in current workspace")
    if not get_state_entry(state, "last_build"):
        hints.append("last_build has not been generated yet; subsequent flash/debug cannot be chained automatically")
    if workflow_config.get("preferred_build") == "auto" and sum(1 for k in ("keil", "gcc", "eide") if discovery[k]) > 1:
        hints.append("Multiple build backends exist (Keil/GCC/EIDE); consider fixing preferred_build in workflow section of .embeddedskills/config.json")
    return {
        "status": "ok",
        "action": "diagnose",
        "summary": "Workflow diagnosis completed",
        "details": {
            "workspace": str(workspace),
            "discovery": discovery,
            "state": {
                "last_build": get_state_entry(state, "last_build"),
                "last_flash": get_state_entry(state, "last_flash"),
                "last_debug": get_state_entry(state, "last_debug"),
                "last_observe": get_state_entry(state, "last_observe"),
            },
            "hints": hints,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="workflow run")
    parser.add_argument("action", choices=["plan", "build", "build-flash", "build-debug", "observe", "diagnose"])
    parser.add_argument("--workspace", default=None, help="Workspace root directory, defaults to current directory")
    parser.add_argument("--config", default=None, help="workflow config.json path (deprecated, kept for compatibility)")
    parser.add_argument("--build-backend", choices=["auto", "keil", "gcc", "eide"], default=None)
    parser.add_argument("--flash-backend", choices=["auto", "jlink", "openocd", "probe-rs"], default=None)
    parser.add_argument("--debug-backend", choices=["auto", "jlink", "openocd", "probe-rs"], default=None)
    parser.add_argument("--observe-backend", choices=["auto", "jlink", "openocd", "probe-rs"], default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    started_at = now_iso()
    started_ts = time.time()
    workspace = workspace_root(args.workspace)
    try:
        full_config, config_path = load_effective_project_config(str(workspace), args.config)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        wrapped = make_result(
            status="error",
            action=args.action,
            summary=str(exc),
            context=parameter_context(provider="workflow", workspace=str(workspace)),
            error={"code": "invalid_config", "message": str(exc)},
            timing=make_timing(started_at, (time.time() - started_ts) * 1000),
        )
        if args.as_json:
            output_json(wrapped)
        else:
            print(f"[workflow {args.action}] {wrapped['summary']}")
        sys.exit(1)

    workflow_config = full_config.get("workflow", {})
    state = load_workspace_state(str(workspace))
    discovery = discover_projects(workspace)

    # Track practically used backends to write back to config on success
    used_backends = {}

    if args.action == "plan":
        cmd = [PYTHON_EXE, str(ROOT_DIR / "workflow" / "scripts" / "workflow_plan.py"), "--workspace", str(workspace), "--json"]
        if config_path:
            cmd.extend(["--config", config_path])
        result = run_json(cmd, workspace)
    elif args.action == "build":
        result = build_project(workspace, full_config, discovery, args.build_backend)
        if result.get("status") == "ok" and result.get("details", {}).get("backend"):
            used_backends["preferred_build"] = result["details"]["backend"]
    elif args.action == "build-flash":
        build_result = build_project(workspace, full_config, discovery, args.build_backend)
        if build_result.get("status") == "error":
            result = build_result
        else:
            if build_result.get("details", {}).get("backend"):
                used_backends["preferred_build"] = build_result["details"]["backend"]
            state = load_workspace_state(str(workspace))
            flash_result = flash_project(workspace, full_config, state, args.flash_backend)
            if flash_result.get("status") == "ok" and flash_result.get("details", {}).get("backend"):
                used_backends["preferred_flash"] = flash_result["details"]["backend"]
            result = {
                "status": flash_result.get("status", "error"),
                "action": "build-flash",
                "summary": "build-flash completed" if flash_result.get("status") == "ok" else flash_result.get("error", {}).get("message", "build-flash failed"),
                "details": {"build": build_result, "flash": flash_result},
            }
    elif args.action == "build-debug":
        build_result = build_project(workspace, full_config, discovery, args.build_backend)
        if build_result.get("status") == "error":
            result = build_result
        else:
            if build_result.get("details", {}).get("backend"):
                used_backends["preferred_build"] = build_result["details"]["backend"]
            state = load_workspace_state(str(workspace))
            debug_result = debug_project(workspace, full_config, state, args.debug_backend)
            if debug_result.get("status") == "ok" and debug_result.get("details", {}).get("backend"):
                used_backends["preferred_debug"] = debug_result["details"]["backend"]
            result = {
                "status": debug_result.get("status", "error"),
                "action": "build-debug",
                "summary": "build-debug completed" if debug_result.get("status") == "ok" else debug_result.get("error", {}).get("message", "build-debug failed"),
                "details": {"build": build_result, "debug": debug_result},
            }
    elif args.action == "observe":
        result = observe_project(workspace, full_config, args.observe_backend)
        if result.get("status") == "ok" and result.get("details", {}).get("backend"):
            used_backends["preferred_observe"] = result["details"]["backend"]
    else:
        result = diagnose(workspace, full_config, discovery, state)

    # Write confirmed preferred values back to .embeddedskills/config.json
    if used_backends:
        save_project_config(str(workspace), used_backends)

    # Update workflow's own runtime state to state.json without overwriting underlying skills' last_build/last_flash/last_debug/last_observe
    if result.get("status") == "ok" and args.action in ("build", "build-flash", "build-debug", "observe"):
        state_record = {
            "action": args.action,
            "timestamp": now_iso(),
        }
        state_details = _workflow_state_details(args.action, result)
        if state_details:
            state_record["details"] = state_details
        update_state_entry(_workflow_state_key(args.action), state_record, str(workspace))

    wrapped = make_result(
        status=result.get("status", "error"),
        action=args.action,
        summary=result.get("summary") or (result.get("error") or {}).get("message") or "workflow execution completed",
        details=result.get("details", {}),
        context=parameter_context(provider="workflow", workspace=str(workspace), config_path=config_path),
        error=result.get("error"),
        timing=make_timing(started_at, (time.time() - started_ts) * 1000),
    )

    if args.as_json:
        output_json(wrapped)
    else:
        print(f"[workflow {args.action}] {wrapped['summary']}")
        if wrapped.get("error"):
            sys.exit(1)


if __name__ == "__main__":
    main()
