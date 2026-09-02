# terminal

Claude Code skill for bidirectional interactive terminal sessions in embedded debugging: serial terminals, interactive SSH shells, local shells, device CLIs, AT commands, and menu-driven consoles.

## Features

- Start background interactive sessions and read/write continuously using session names
- Support three backends: serial, SSH, and local shell
- Send text or Hex data to sessions
- Read and drain session output buffers
- Attach to sessions in foreground line mode
- Stop sessions and clean up `.embeddedskills/state.json` state

## Requirements

- Python 3.x
- Serial backend: `pyserial`, install with `pip install pyserial`
- SSH backend: OpenSSH client `ssh`
- Local backend: defaults to `$SHELL`, falls back to `/bin/sh` if unset

## Configuration

### Environment Configuration (`config.json`)

The environment-level configuration for the terminal skill is currently an empty object:

```json
{}
```

Key parameters for interactive terminals are typically tied to specific sessions and should be passed explicitly in the `start` command to avoid misconnecting devices or misusing credentials.

### Session State (`.embeddedskills/state.json`)

`.embeddedskills/state.json` in the workspace stores currently active background sessions:

```json
{
  "terminal_sessions": {
    "board": {
      "session_id": "board",
      "backend": "serial",
      "tcp_port": 23145,
      "pid": 1234,
      "log_file": ".embeddedskills/logs/terminal/board.log"
    }
  }
}
```

### Log Directory

Background process logs are saved to:

```text
.embeddedskills/logs/terminal/
```

### Parameter Precedence

1. **CLI Arguments** (`--port`, `--baudrate`, `--host`, `--name`, etc.) - Highest priority
2. **Session State** (already started `terminal_sessions` in `.embeddedskills/state.json`)
3. **Defaults** - Lowest priority

## Common Commands

Command examples are based on the skill directory.

### Start Serial Terminal

```bash
python scripts/terminal_session.py start serial --port /dev/ttyUSB0 --baudrate 115200 --name board
```

### Start SSH Terminal

`--host` uses the Host alias in `~/.ssh/config`:

```bash
python scripts/terminal_session.py start ssh --host 1380-P904 --name devboard
```

When connecting to a trusted device for the first time, you can append:

```bash
--accept-new-host-key
--known-hosts-file <temporary_known_hosts_path>
```

### Start Local Shell

```bash
python scripts/terminal_session.py start local --name local-shell
```

### Send Commands

```bash
python scripts/terminal_session.py send board "help" --crlf
```

Send Hex:

```bash
python scripts/terminal_session.py send board "01 03 00 00 00 02" --hex
```

### Read Output

```bash
python scripts/terminal_session.py read board --timeout 1
```

### Foreground Line-Mode Attach

```bash
python scripts/terminal_session.py attach board
```

### Query and Stop

```bash
python scripts/terminal_session.py list
python scripts/terminal_session.py status board
python scripts/terminal_session.py stop board
```

## Operational Boundaries

- Use terminal only when maintaining interactive state is necessary.
- For one-shot remote commands, file transfers, and port forwarding, continue to prefer the `ssh` skill.
- For serial scanning, logging, and Hex monitoring, continue to prefer the `serial` skill.
- Do not proactively execute commands that change device states without clear intent.
- `attach` is line-mode and not equivalent to full TTY/raw mode; full-screen programs, vim, top, or interactive password prompts should use native terminal tools.
- Execute `stop` after completing debugging to prevent background sessions from occupying serial ports, SSH connections, or local shells.

## Troubleshooting

Check in order:

1. `python scripts/terminal_session.py list`
2. `python scripts/terminal_session.py status <session_name>`
3. `.embeddedskills/logs/terminal/<session_name>.log`
4. Whether the serial port is busy, and if the baud rate is correct
5. Whether the SSH Host alias can be resolved via `ssh -G <alias>`
6. Whether `pyserial` or the OpenSSH client is missing
