"""Tests for herdr_exec.sh using a stub `herdr` binary that simulates panes with plain subprocesses."""

import json
import os
import stat
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "herdr_exec.sh"

# Stub herdr: records every call in $STUB_LOG and runs `pane run` commands in the background,
# which is what a real pane does from the caller's point of view.
STUB_HERDR = textwrap.dedent(r"""\
    #!/usr/bin/env bash
    set -u
    echo "$*" >> "$STUB_LOG"
    state="$STUB_DIR"
    case "$1 $2" in
      "pane split")
        n=$(( $(cat "$state/count" 2>/dev/null || echo 0) + 1 ))
        echo "$n" > "$state/count"
        echo "w9:p$n" >> "$state/panes"
        printf '{"result":{"pane":{"pane_id":"w9:p%s"}}}\n' "$n" ;;
      "pane get")
        grep -qx "$3" "$state/panes" 2>/dev/null || { echo '{"error":"not found"}' >&2; exit 1; }
        label=null; [ -f "$state/label_$3" ] && label="\"$(cat "$state/label_$3")\""
        printf '{"result":{"pane":{"pane_id":"%s","label":%s}}}\n' "$3" "$label" ;;
      "pane list")
        ids=$(sed 's/.*/{"pane_id":"&"}/' "$state/panes" 2>/dev/null | paste -sd, -)
        printf '{"result":{"panes":[%s]}}\n' "$ids" ;;
      "pane process-info")
        name=bash; [ -f "$state/busy" ] || [ -f "$state/busy_$4" ] && name=python3
        printf '{"result":{"process_info":{"foreground_processes":[{"name":"%s"}]}}}\n' "$name" ;;
      "pane layout")
        printf '{"result":{"layout":{"panes":[{"pane_id":"w9:p0","rect":{"width":%s,"height":40}}]}}}\n' "${STUB_WIDTH:-200}" ;;
      "pane rename") echo "$4" > "$state/label_$3"; echo '{"result":{}}' ;;
      "pane run")
        bash -c "$4" > "$state/pane_output_$3.log" 2>&1 &
        echo '{"result":{}}' ;;
      *) echo "stub: unsupported $*" >&2; exit 2 ;;
    esac
""")


@pytest.fixture()
def env(tmp_path):
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    herdr = stub_bin / "herdr"
    herdr.write_text(STUB_HERDR)
    herdr.chmod(herdr.stat().st_mode | stat.S_IEXEC)
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir()
    e = {
        "PATH": f"{stub_bin}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "HERDR_ENV": "1",
        "HERDR_PANE_ID": "w9:p0",
        "HERDR_WORKSPACE_ID": "w9",
        "HERDR_EXEC_STATE_DIR": str(tmp_path / "state"),
        "HERDR_EXEC_DISABLED_USERS": "nobody-at-all",
        "STUB_LOG": str(tmp_path / "herdr_calls.log"),
        "STUB_DIR": str(stub_dir),
    }
    return {"env": e, "tmp": tmp_path, "stub_dir": stub_dir}


def run(env, *cmd, extra_env=None, timeout=30):
    e = dict(env["env"])
    if extra_env:
        e.update(extra_env)
    return subprocess.run(["bash", str(SCRIPT), *cmd], env=e, capture_output=True, text=True,
                          timeout=timeout, cwd=str(env["tmp"]))


def calls(env, prefix):
    log = Path(env["env"]["STUB_LOG"])
    lines = log.read_text().splitlines() if log.exists() else []
    return [line for line in lines if line.startswith(prefix)]


PRINT_CMD = ["--label", "t", "--", "python3", "-c",
             "import sys; print('out-line'); print('err-line', file=sys.stderr); sys.exit(3)"]


class TestFallback:
    def test_runs_directly_when_not_in_herdr(self, env):
        r = run(env, *PRINT_CMD, extra_env={"HERDR_ENV": ""})
        assert (r.returncode, r.stdout, r.stderr.strip()) == (3, "out-line\n", "err-line")
        assert calls(env, "pane") == []

    def test_runs_directly_for_disabled_user(self, env):
        me = subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()
        r = run(env, *PRINT_CMD, extra_env={"HERDR_EXEC_DISABLED_USERS": f"someone-else {me}"})
        assert r.returncode == 3 and r.stdout == "out-line\n"
        assert calls(env, "pane") == []

    def test_runs_directly_when_explicitly_disabled(self, env):
        r = run(env, *PRINT_CMD, extra_env={"HERDR_EXEC_DISABLE": "1"})
        assert r.returncode == 3
        assert calls(env, "pane") == []


class TestHerdrPane:
    def test_preserves_stdout_stderr_and_exit_code(self, env):
        r = run(env, *PRINT_CMD)
        assert r.returncode == 3
        assert r.stdout == "out-line\n"
        assert "err-line" in r.stderr
        assert len(calls(env, "pane run")) == 1

    def test_any_exit_code_is_returned_and_command_runs_once(self, env):
        counter = env["tmp"] / "runs"
        r = run(env, "--", "bash", "-c", f"echo x >> {counter}; exit 99")
        assert r.returncode == 99
        assert counter.read_text().count("x") == 1

    def test_json_stdout_stays_parseable(self, env):
        r = run(env, "--label", "j", "--", "python3", "-c", "import json; print(json.dumps({'status': 'ok'}))")
        assert json.loads(r.stdout) == {"status": "ok"}

    def test_reuses_the_same_pane(self, env):
        run(env, "--", "true")
        run(env, "--", "true")
        assert len(calls(env, "pane split")) == 1
        assert {c.split()[2] for c in calls(env, "pane run")} == {"w9:p1"}

    def test_creates_new_pane_when_shared_pane_is_gone(self, env):
        run(env, "--", "true")
        (env["stub_dir"] / "panes").write_text("")  # user closed the pane
        run(env, "--", "true")
        assert len(calls(env, "pane split")) == 2

    def test_creates_new_pane_when_shared_pane_is_busy(self, env):
        run(env, "--", "true")
        (env["stub_dir"] / "busy").write_text("1")
        run(env, "--", "true", extra_env={"HERDR_EXEC_IDLE_WAIT_MS": "0"})
        assert len(calls(env, "pane split")) == 2

    def test_split_direction_follows_caller_width(self, env):
        run(env, "--", "true", extra_env={"STUB_WIDTH": "200"})
        assert "--direction right" in calls(env, "pane split")[0]
        (env["stub_dir"] / "panes").write_text("")
        run(env, "--", "true", extra_env={"STUB_WIDTH": "100"})
        assert "--direction down" in calls(env, "pane split")[1]

    def test_split_keeps_focus_and_cwd(self, env):
        run(env, "--", "true")
        split = calls(env, "pane split")[0]
        assert "--no-focus" in split and f"--cwd {env['tmp']}" in split

    def test_arguments_with_spaces_and_quotes_survive(self, env):
        r = run(env, "--", "python3", "-c", "import sys; print(sys.argv[1:])", "a b", "it's", "$HOME")
        assert r.stdout.strip() == "['a b', \"it's\", '$HOME']"

    def test_timeout_returns_124_and_leaves_command_running(self, env):
        start = time.time()
        r = run(env, "--timeout-ms", "500", "--", "sleep", "5")
        assert r.returncode == 124
        assert time.time() - start < 4
        assert "still running" in r.stderr


def add_pane(env, pane, label=None, busy=False):
    """Simulate a pane that already exists in the workspace (e.g. left over from an earlier run)."""
    with open(env["stub_dir"] / "panes", "a") as f:
        f.write(pane + "\n")
    if label:
        (env["stub_dir"] / f"label_{pane}").write_text(label)
    if busy:
        (env["stub_dir"] / f"busy_{pane}").write_text("1")


class TestReuseIdlePane:
    def test_reuses_idle_managed_pane_instead_of_splitting(self, env):
        add_pane(env, "w9:p7", label="uart-console")
        r = run(env, "--", "true")
        assert r.returncode == 0
        assert calls(env, "pane split") == []
        assert {c.split()[2] for c in calls(env, "pane run")} == {"w9:p7"}
        assert (env["stub_dir"] / "label_w9:p7").read_text().strip() == "embedded-skills"

    def test_never_reuses_unlabelled_or_foreign_panes(self, env):
        add_pane(env, "w9:p5")                      # the user's own shell
        add_pane(env, "w9:p6", label="my-notes")    # labelled by the user
        run(env, "--", "true")
        assert len(calls(env, "pane split")) == 1
        assert not any(c.split()[2] in ("w9:p5", "w9:p6") for c in calls(env, "pane run"))

    def test_skips_busy_managed_pane(self, env):
        add_pane(env, "w9:p7", label="uart-console", busy=True)   # picocom still running
        run(env, "--", "true")
        assert len(calls(env, "pane split")) == 1

    def test_never_reuses_the_caller_pane(self, env):
        add_pane(env, "w9:p0", label="embedded-skills")
        run(env, "--", "true")
        assert len(calls(env, "pane split")) == 1

    def test_get_pane_reuses_idle_pane_and_relabels_it(self, env):
        add_pane(env, "w9:p7", label="embedded-skills")
        r = run(env, "--get-pane", "uart-console")
        assert (r.returncode, r.stdout.strip()) == (0, "w9:p7")
        assert calls(env, "pane split") == []
        assert (env["stub_dir"] / "label_w9:p7").read_text().strip() == "uart-console"

    def test_get_pane_creates_one_when_none_is_idle(self, env):
        r = run(env, "--get-pane", "uart-console")
        assert (r.returncode, r.stdout.strip()) == (0, "w9:p1")
        assert len(calls(env, "pane split")) == 1
        assert calls(env, "pane run") == []

    def test_get_pane_takes_over_shared_pane_so_next_run_does_not_wait_on_it(self, env):
        run(env, "--", "true")                                   # shared pane w9:p1
        assert run(env, "--get-pane", "uart-console").stdout.strip() == "w9:p1"
        (env["stub_dir"] / "busy_w9:p1").write_text("1")         # console now running in it
        start = time.time()
        run(env, "--", "true")
        assert time.time() - start < 2                           # no 3 s idle wait on the old pane
        assert len(calls(env, "pane split")) == 2

    def test_get_pane_outside_herdr_fails(self, env):
        r = run(env, "--get-pane", "uart-console", extra_env={"HERDR_ENV": ""})
        assert r.returncode == 1 and r.stdout == ""


class TestNested:
    """A wrapped command (e.g. workflow) that itself calls herdr_exec.sh must not deadlock."""

    def test_nested_call_runs_inline_and_mirrors_to_pane_tty(self, env):
        fake_tty = env["tmp"] / "pane_tty"
        fake_tty.write_text("")
        r = run(env, *PRINT_CMD, extra_env={"HERDR_EXEC_TTY": str(fake_tty)})
        assert (r.returncode, r.stdout) == (3, "out-line\n")
        assert "err-line" in r.stderr
        assert calls(env, "pane") == []
        shown = fake_tty.read_text()
        assert "> [t]" in shown and "out-line" in shown and "err-line" in shown and "exit=3" in shown

    def test_outer_and_inner_wrapper_do_not_deadlock(self, env):
        inner = f"bash {SCRIPT} --label inner -- echo inner-out"
        start = time.time()
        r = run(env, "--label", "outer", "--timeout-ms", "20000", "--", "bash", "-c", inner, timeout=25)
        assert r.returncode == 0
        assert r.stdout.strip() == "inner-out"
        assert time.time() - start < 10
        assert len(calls(env, "pane split")) == 1


class TestUsage:
    def test_missing_command_is_usage_error(self, env):
        r = run(env, "--label", "x", "--")
        assert r.returncode == 2

    def test_get_pane_without_label_is_usage_error(self, env):
        r = run(env, "--get-pane")
        assert r.returncode == 2

    def test_bad_timeout_is_usage_error(self, env):
        r = run(env, "--timeout-ms", "soon", "--", "true")
        assert r.returncode == 2
