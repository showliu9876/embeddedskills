"""Tests for the read-only `workflow probe` action."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import workflow_run  # noqa: E402

JLINK_CFG = {"jlink": {"device": "Cortex-A9", "interface": "JTAG", "speed": "4000"}}
OPENOCD_CFG = {"openocd": {"interface": "interface/jlink.cfg", "target": "target/stm32f4x.cfg"}}
PROBE_RS_CFG = {"probe-rs": {"chip": "STM32F407VG", "protocol": "swd"}}


@pytest.fixture()
def captured(monkeypatch):
    seen = {}

    def fake_run_json(cmd, workdir):
        seen["cmd"] = cmd
        seen["workdir"] = workdir
        return {"status": "ok", "summary": "Probe successful", "details": {}}

    monkeypatch.setattr(workflow_run, "run_json", fake_run_json)
    return seen


def script_and_action(cmd):
    return Path(cmd[1]).name, cmd[2]


def test_jlink_probe_runs_jlink_info_with_configured_device(captured, tmp_path):
    result = workflow_run.probe_target(tmp_path, JLINK_CFG, None)
    cmd = captured["cmd"]
    assert script_and_action(cmd) == ("jlink_exec.py", "info")
    assert cmd[cmd.index("--device") + 1] == "Cortex-A9"
    assert cmd[cmd.index("--interface") + 1] == "JTAG"
    assert cmd[cmd.index("--speed") + 1] == "4000"
    assert cmd[cmd.index("--workspace") + 1] == str(tmp_path)
    assert "--json" in cmd
    assert result["details"]["backend"] == "jlink"


def test_openocd_probe_runs_openocd_probe(captured, tmp_path):
    workflow_run.probe_target(tmp_path, OPENOCD_CFG, None)
    cmd = captured["cmd"]
    assert script_and_action(cmd) == ("openocd_run.py", "probe")
    assert cmd[cmd.index("--target") + 1] == "target/stm32f4x.cfg"


def test_probe_rs_probe_runs_probe_rs_info(captured, tmp_path):
    workflow_run.probe_target(tmp_path, PROBE_RS_CFG, None)
    cmd = captured["cmd"]
    assert script_and_action(cmd) == ("probe_rs_exec.py", "info")
    assert cmd[cmd.index("--chip") + 1] == "STM32F407VG"
    assert cmd[cmd.index("--protocol") + 1] == "swd"


def test_multiple_ready_backends_require_a_choice(captured, tmp_path):
    result = workflow_run.probe_target(tmp_path, {**JLINK_CFG, **PROBE_RS_CFG}, None)
    assert result["status"] == "error"
    assert result["error"]["code"] == "multiple_backend_candidates"
    assert "cmd" not in captured


def test_explicit_backend_wins(captured, tmp_path):
    workflow_run.probe_target(tmp_path, {**JLINK_CFG, **PROBE_RS_CFG}, "probe-rs")
    assert script_and_action(captured["cmd"])[0] == "probe_rs_exec.py"


def test_preferred_flash_backend_is_reused(captured, tmp_path):
    cfg = {**JLINK_CFG, **PROBE_RS_CFG, "workflow": {"preferred_flash": "jlink"}}
    workflow_run.probe_target(tmp_path, cfg, None)
    assert script_and_action(captured["cmd"])[0] == "jlink_exec.py"


def test_no_configured_backend_is_an_error(captured, tmp_path):
    result = workflow_run.probe_target(tmp_path, {}, None)
    assert result["error"]["code"] == "no_backend_available"


def test_cli_accepts_probe_action_and_does_not_write_state(tmp_path):
    cfg_dir = tmp_path / ".embeddedskills"
    cfg_dir.mkdir()
    (cfg_dir / "config.json").write_text(json.dumps({}))
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "workflow_run.py"), "probe", "--workspace", str(tmp_path), "--json"],
        capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"},
    )
    out = json.loads(proc.stdout)
    assert out["action"] == "probe"
    assert out["error"]["code"] == "no_backend_available"
    assert not (cfg_dir / "state.json").exists()
