"""Tests for routing workflow sub-skill calls through herdr-exec."""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import workflow_run  # noqa: E402

JLINK_CMD = [sys.executable, str(workflow_run.ROOT_DIR / "jlink" / "scripts" / "jlink_exec.py"), "info", "--json"]


def test_wraps_command_with_herdr_exec_inside_herdr(monkeypatch):
    monkeypatch.setenv("HERDR_ENV", "1")
    wrapped = workflow_run.herdr_wrap(JLINK_CMD)
    assert wrapped[:4] == ["bash", str(workflow_run.HERDR_EXEC), "--label", "jlink"]
    assert wrapped[4] == "--"
    assert wrapped[5:] == JLINK_CMD


def test_leaves_command_unchanged_outside_herdr(monkeypatch):
    monkeypatch.delenv("HERDR_ENV", raising=False)
    assert workflow_run.herdr_wrap(JLINK_CMD) == JLINK_CMD


def test_leaves_command_unchanged_when_herdr_exec_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.setattr(workflow_run, "HERDR_EXEC", tmp_path / "missing.sh")
    assert workflow_run.herdr_wrap(JLINK_CMD) == JLINK_CMD


def test_run_json_uses_wrapped_command(monkeypatch, tmp_path):
    seen = {}

    class Proc:
        stdout = '{"status": "ok"}'
        stderr = ""

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return Proc()

    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.setattr(workflow_run.subprocess, "run", fake_run)
    assert workflow_run.run_json(JLINK_CMD, tmp_path) == {"status": "ok"}
    assert seen["cmd"][1] == str(workflow_run.HERDR_EXEC)
