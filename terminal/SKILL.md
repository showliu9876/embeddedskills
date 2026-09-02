---
name: terminal
description: Bidirectional interactive terminal session tool for serial terminals, interactive SSH shells, local shells, device consoles, AT/CLI menus, and interactive debugging requiring persistent context. Trigger when the user mentions interactive terminals, serial terminals, SSH terminals, opening a shell, sending commands and reading output continuously, keeping sessions, post-login operations, or menu-driven command lines; also compatible with explicit /terminal calls.
---

# Terminal — Bidirectional Interactive Terminal Sessions

Unified bidirectional interactive session wrapper for serial ports, SSH, and local shells. It bridges the gap between `serial` (where monitoring and sending are separate commands) and `ssh` (where remote commands are mostly one-shot executions): use this skill when the target requires maintaining login state, menu state, REPL state, or device CLI context.

## Positioning

- `serial`: Scanning, monitoring, one-shot sending, logging, Hex viewing.
- `ssh`: OpenSSH configuration, remote commands, transfers, tunnels.
- `terminal`: Maintain a continuously readable and writable interactive session, driving subsequent decisions via `send/read`.

## Configuration

### Environment Configuration (`config.json`)

The environment-level configuration for the terminal skill is currently an empty object `{}`. Key parameters for interactive terminals are typically tied to specific sessions and should preferably be passed explicitly via the `start` command to avoid misconnecting devices or misusing credentials.

### Session State (`.embeddedskills/state.json`)

Runtime state for background sessions is saved to `.embeddedskills/state.json` in the workspace, using the `terminal_sessions` field to record session name, backend, PID, TCP control port, and log path.

### Parameter Precedence

1. **CLI Arguments** (`--port`, `--baudrate`, `--host`, `--name`, etc.) - Highest priority
2. **Session State** (already started `terminal_sessions` in `.embeddedskills/state.json`)
3. **Defaults** - Lowest priority

## Subcommands

| Subcommand | Description | Risk |
|------------|-------------|------|
| `start` | Start a background interactive session | Medium |
| `list` | List existing sessions | Low |
| `status` | Query the status of a single session | Low |
| `send` | Send text or Hex data to a session | Medium |
| `read` | Read and drain the session output buffer | Low |
| `attach` | Attach to session in foreground line mode | Medium |
| `stop` | Stop session and clean up state | Medium |

## Backends

| Backend | Use Case | Dependencies |
|---------|----------|--------------|
| `serial` | MCU UART console, AT commands, Bootloader menu, board CLI | `pyserial` |
| `ssh` | Linux dev board interactive shell, continuous post-login operations | OpenSSH client |
| `local` | Local temporary shell, REPL, interactive CLI programs | Python standard library |

## Script Invocation

All scripts are located under `scripts/` in the skill directory and invoked directly via `python`. Command examples are based on the skill directory.

```bash
# Start serial terminal
python scripts/terminal_session.py start serial --port /dev/ttyUSB0 --baudrate 115200 --name board

# Start SSH terminal, host uses the Host alias in ~/.ssh/config
python scripts/terminal_session.py start ssh --host 1380-P904 --name devboard

# Start local shell
python scripts/terminal_session.py start local --name local-shell

# Send a line of command and append CRLF
python scripts/terminal_session.py send board "help" --crlf

# Read output, waiting up to 1 second
python scripts/terminal_session.py read board --timeout 1

# Attach in foreground line mode
python scripts/terminal_session.py attach board

# Query and stop
python scripts/terminal_session.py list
python scripts/terminal_session.py status board
python scripts/terminal_session.py stop board
```

## Session State Details

Session metadata is saved to the workspace:

```text
.embeddedskills/state.json
```

Recorded under the `terminal_sessions` field:

```json
{
  "terminal_sessions": {
    "board": {
      "backend": "serial",
      "tcp_port": 23145,
      "pid": 1234,
      "started_at": "2026-05-26T10:00:00+08:00"
    }
  }
}
```

Background process logs are saved to:

```text
.embeddedskills/logs/terminal/
```

## Output Format

The script outputs JSON by default:

```json
{
  "status": "ok",
  "action": "read",
  "summary": "read 42 bytes",
  "details": {
    "session": "board",
    "text": "help\r\n..."
  }
}
```

Error output:

```json
{
  "status": "error",
  "action": "send",
  "error": {
    "code": "session_unreachable",
    "message": "session unreachable, may have exited"
  }
}
```

## Workflow

1. Determine whether maintaining an interactive state is truly necessary; for one-shot remote commands, prefer `ssh`; for serial log capture only, prefer `serial`.
2. Choose backend: `serial` for serial consoles, `ssh` for remote shells, `local` for local interactive programs.
3. Run `read --timeout 1` after `start` to capture startup banners, login prompts, or shell prompts.
4. Run `read --timeout <seconds>` after every `send` to observe feedback before deciding the next step.
5. Execute `stop` upon completion to avoid background processes occupying serial ports, SSH connections, or local shells indefinitely.

## Core Rules

- Do not guess serial ports, baud rates, SSH hosts, or credentials.
- Do not proactively execute commands that change device states without clear intent.
- Multiple sessions must use distinct `--name` values to prevent output confusion.
- `read` drains the current output buffer; record important output into the final response promptly.
- `attach` is line-mode and not equivalent to full TTY/raw mode; for full-screen programs, vim, top, or interactive password prompts, recommend users use native terminal tools.
- Serial sessions hold an exclusive lock on the physical serial port; if sharing is needed with external tools, use the mux capability in `serial` skill first.
- The SSH backend uses Host aliases from `~/.ssh/config`; host configuration, jump hosts, and file transfers should still be delegated to the `ssh` skill.
- Preserve real errors on failure: do not swallow port conflicts, missing `pyserial`, missing `ssh`, unresolvable Host aliases, or exited processes.
