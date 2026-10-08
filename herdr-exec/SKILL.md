---
name: herdr-exec
description: >-
  Show embeddedskills commands live in a shared Herdr pane. Whenever you run a script from the can, gcc,
  jlink, net, openocd, probe-rs, serial, ssh, terminal or workflow skills and HERDR_ENV=1, wrap the command
  with this skill's herdr_exec.sh so the user can watch exactly what runs. Output, stderr and exit code are
  returned unchanged; outside Herdr (or for disabled accounts) it simply runs the command directly.
---

# Herdr Exec — run embeddedskills commands in a visible Herdr pane

The user wants to **see every embedded tool command that actually runs**. When this agent is inside
Herdr (`HERDR_ENV=1`), commands from the skills below are executed in one shared sibling pane labelled
`embedded-skills` instead of invisibly in the agent's own shell.

Covered skills: `can`, `gcc`, `jlink`, `net`, `openocd`, `probe-rs`, `serial`, `ssh`, `terminal`, `workflow`.

## Rule

When you run any script under `.claude/skills/<covered-skill>/scripts/`, prefix it with the wrapper:

```bash
.claude/skills/herdr-exec/scripts/herdr_exec.sh --label <skill> -- <original command...>
```

Example:

```bash
.claude/skills/herdr-exec/scripts/herdr_exec.sh --label jlink -- \
  python3 .claude/skills/jlink/scripts/jlink_exec.py info --json
```

- Always prefix; do **not** check `HERDR_ENV` yourself. The wrapper decides and falls back to direct
  execution outside Herdr, when `HERDR_EXEC_DISABLE=1`, or for accounts in `HERDR_EXEC_DISABLED_USERS`.
- `workflow` already wraps its own sub-skill calls (`workflow_run.py` → `herdr_wrap()`); still wrap the
  top-level `workflow_run.py` call so the user sees it too.
- Treat the result exactly like the unwrapped command: stdout (e.g. `--json` output) on stdout, the
  command's stderr on stderr, and its exit code. The wrapper adds one `[herdr-exec] running in Herdr pane …`
  line on stderr.
- Exit code `124` means the command did not finish within `--timeout-ms` (default 600000). It keeps running
  in the pane; tell the user instead of re-running it.
- Long-running/streaming commands (RTT, serial monitor, SWO) occupy the pane until they exit; the next
  wrapped command then opens a new pane automatically.

## Behaviour

- One shared pane per Herdr workspace, created on first use with
  `herdr pane split --pane $HERDR_PANE_ID --direction right|down --cwd $PWD --no-focus`
  (right when the caller pane is ≥160 columns wide, otherwise down) and renamed `embedded-skills`.
  The user's focus never moves.
- The pane is reused while it exists and its foreground process is a shell. If the user closed it or
  something is still running in it, a new pane is created.
- Each run shows `> [label] command`, the live output, and `= [label] exit=N (Ns)` in the pane.
- Runs are serialised with a lock, so parallel tool calls do not type into the same pane at once.
- **Nested calls** (a wrapped command that itself calls `herdr_exec.sh`, e.g. `workflow` → `jlink`) are
  detected through `HERDR_EXEC_TTY`, which the pane runner exports. They run inline — no lock, no new
  pane — and mirror their output, indented, to the same pane. (Without this, the inner call would wait
  for the outer call's lock forever.)
- `PATH`, `PYTHONPATH`, `VIRTUAL_ENV`, `CONDA_PREFIX`, `JLINK_BIN`, `JLINK_SN` and the caller's cwd are
  carried into the pane.

## Safety

- **Commands in a Herdr pane are not confined by Claude Code's sandbox.** List every account that runs
  under a managed or stricter sandbox in `HERDR_EXEC_DISABLED_USERS` (space-separated) so it always runs
  directly. Never remove an account from that list to get around a managed sandbox.
- The wrapper only creates panes; it never closes panes, tabs or workspaces.

## Tests

```bash
uvx pytest -q -p no:cacheprovider .claude/skills/herdr-exec/tests
```

The tests use a stub `herdr` binary and do not touch the real Herdr session.
