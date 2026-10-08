---
name: herdr-exec
description: >-
  Show embeddedskills commands live in a shared Herdr pane. Whenever you run a script from the can, gcc,
  jlink, net, openocd, probe-rs, serial, ssh, terminal or workflow skills and HERDR_ENV=1, wrap the command
  with this skill's herdr_exec.sh so the user can watch exactly what runs. Output, stderr and exit code are
  returned unchanged; outside Herdr (or for disabled accounts) it simply runs the command directly.
  Also defines the default UART debug console in Herdr: a dedicated picocom pane with a log file.
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
  something is still running in it, an **idle pane labelled `embedded-skills` or `uart-console`** in the same
  workspace is reused (and relabelled) before a new pane is split. Panes without one of these labels — the
  user's own shells, other agents — and the caller's own pane are never reused.
- Each run shows `> [label] command`, the live output, and `= [label] exit=N (Ns)` in the pane.
- Runs are serialised with a lock, so parallel tool calls do not type into the same pane at once.
- **Nested calls** (a wrapped command that itself calls `herdr_exec.sh`, e.g. `workflow` → `jlink`) are
  detected through `HERDR_EXEC_TTY`, which the pane runner exports. They run inline — no lock, no new
  pane — and mirror their output, indented, to the same pane. (Without this, the inner call would wait
  for the outer call's lock forever.)
- `PATH`, `PYTHONPATH`, `VIRTUAL_ENV`, `CONDA_PREFIX`, `JLINK_BIN`, `JLINK_SN` and the caller's cwd are
  carried into the pane.

## UART debug console (default workflow)

When a debug session in Herdr needs the target's UART console, **do not** stream it through
`serial_monitor.py` in the shared `embedded-skills` pane, and **do not** use the `serial` mux.
Open a dedicated pane running `picocom` with a log file instead: the user gets an interactive console,
and the agent reads the log file without ever opening the serial port.

1. Check the port is free (`fuser /dev/ttyUSB0` prints nothing).
2. Open the console pane (use the project's port/baud from `.embeddedskills/config.json` → `serial`):

   ```bash
   log="$PWD/.embeddedskills/logs/serial/uart-$(date +%Y%m%d-%H%M%S).log"
   mkdir -p "$(dirname "$log")"
   pane="$(.claude/skills/herdr-exec/scripts/herdr_exec.sh --get-pane uart-console)"
   herdr pane run "$pane" "picocom -b 115200 --imap lfcrlf --logfile $log /dev/ttyUSB0"
   ```

   `--get-pane` reuses an idle managed pane (or splits one) and labels it `uart-console`. The log path is
   absolute because a reused pane may have a different cwd.

   `--imap lfcrlf` is needed because firmware often prints bare `\n`: without it the
   pane shows a "staircase". Strip `\r` when parsing the log (`tr -d '\r'`).

   Tell the user the pane name and the log path. They exit picocom with `Ctrl-A Ctrl-X`.
3. Read the console from the log file (`tail`, `grep`). `herdr pane read <pane> --lines N` also works,
   but the log file has the full history.
4. **Sending to the target**: type into the console with `herdr pane send-text <pane> "<text>"`, and only
   after the user approved that specific input. picocom stays the only writer, and the user sees what was sent.
5. While the console pane is open, **do not run any `serial_*.py` script on the same port**: pyserial does
   not honour picocom's `flock`, so both would read the port and split the data (symptoms: garbled lines
   and `device reports readiness to read but returned no data`).
6. **Per-line host timestamps** (picocom's log has none): ask the user to close the console, run one
   `serial_monitor.py --port <port> --timestamp --timeout <sec>` capture directly on the port, then reopen
   the console.

Do not start `serial_mux.py`. Everything it offers is covered above with fewer moving parts, and it is
currently broken with the skill scripts: `state.json` stores `real_port` as a relative path
(`../../dev/ttyUSB0`), so `serial_monitor.py`/`serial_log.py` do not recognise the running mux and open the
real port directly, competing with the mux. Reconsider only if the console must run outside
Herdr, or a long capture needs both timestamps and an uninterrupted console — and fix that bug first.

## Pane hygiene (before opening any pane)

- Always get panes through `herdr_exec.sh` (`--label` for commands, `--get-pane <label>` for an
  interactive pane such as the UART console). Both reuse an idle managed pane first; never call
  `herdr pane split` directly.
- A reused pane keeps its position, size and cwd. If a task genuinely needs a pane with different
  parameters (another split direction or size, a different tab, a fresh terminal), do **not** split yet:
  list the idle managed panes (`herdr pane list` + `herdr pane get` label + `process-info`), **ask the user
  whether they may be closed**, and only after they agree close them (`herdr pane close <id>`) and open the
  new one. Never close a pane without that answer.

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
