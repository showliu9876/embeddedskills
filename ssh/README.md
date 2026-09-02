# ssh

Claude Code skill for SSH server and Linux development board operations: OpenSSH configuration management, remote commands, file uploads/downloads, jump hosts, and local port forwarding.

## Features

- Read, query, and add `Host` aliases in `~/.ssh/config`
- Execute remote commands via Host aliases and return structured JSON
- Probe the remote system, runtime, and GPU overview via fixed read-only commands
- Upload and download files using `scp`
- Establish local port forwarding to access remote services
- Support `ProxyJump` jump host configuration
- Explicitly accept new host keys when connecting to trusted devices for the first time

## Requirements

- Python 3.x (standard library only, no extra Python dependencies)
- OpenSSH client: `ssh`, `scp`, `ssh-keygen`
- Optional: Configured SSH keys, `IdentityFile` recommended

Most Linux distributions come with OpenSSH client pre-installed; if commands are missing, install via `sudo apt install openssh-client` (Debian/Ubuntu) or `sudo dnf install openssh-clients` (Fedora/RHEL).

## Configuration

The ssh skill does not maintain an independent server database; its single source of truth is the standard OpenSSH configuration:

```text
~/.ssh/config
```

Using Host aliases to manage devices is recommended:

```ssh-config
# description: Linux Dev Board
# tags: embedded,linux,dev-board
# location: lab
Host 1380-P904
    HostName 192.168.137.76
    User root
    Port 22
    IdentityFile ~/.ssh/id_ed25519
```

Jump host example:

```ssh-config
Host bastion
    HostName bastion.example.com
    User root
    IdentityFile ~/.ssh/id_ed25519

Host internal-dev
    HostName 10.0.1.20
    User root
    IdentityFile ~/.ssh/id_ed25519
    ProxyJump bastion
```

The following comment metadata fields are supported:

| Field | Description |
|-------|-------------|
| `description` | Device or server description |
| `aliases` | Common names the user calls this host, comma-separated; usable for exact resolution |
| `groups` | Logical environment or host group, comma-separated; lets multiple hosts share membership |
| `tags` | Comma-separated tags |
| `location` | Location or environment |

Never write plaintext passwords, tokens, private key contents, or other sensitive information into `~/.ssh/config`.

## Common Commands

Command examples are based on the skill directory.

### List Servers

```bash
python scripts/ssh_config.py list
```

### Search Servers

```bash
python scripts/ssh_config.py find <keyword>
python scripts/ssh_config.py find <environment_keyword> <capability_keyword>
```

Multiple keywords use AND semantics. For example, after tagging test-environment
membership with `groups` and hardware capability with `tags`, `find test-env 4090D`
returns only hosts that satisfy both conditions. `search` is an alias for `find`.

### Resolve a Unique Server

```bash
python scripts/ssh_config.py resolve <keyword...>
```

`resolve` succeeds only when the result is unique. No match returns exit code 1;
multiple candidates return exit code 2 with a candidate list, preventing the AI
from picking a host on its own under ambiguous shared environment names. Exact
OpenSSH `Host` aliases take priority over fuzzy matching.

### Verify Alias Resolution

```bash
python scripts/ssh_config.py show <alias>
```

### Add Server

The script automatically backs up `~/.ssh/config` before writing:

```bash
python scripts/ssh_config.py add <alias> --host <IP_or_domain> --user <user> --port 22 --key ~/.ssh/id_ed25519
```

Common optional arguments:

```bash
--description "Description"
--aliases "common_name_1,common_name_2"
--groups "env1,env2"
--tags tag1,tag2
--location "Location"
--proxy-jump <bastion_alias>
```

### Execute Remote Command

```bash
python scripts/ssh_exec.py <alias> "uname -a" --timeout 30
```

The script outputs JSON containing `success`, `exit_code`, `stdout`, and `stderr`.

### Probe Remote Environment

```bash
python scripts/ssh_probe.py <alias>
```

This command only runs the built-in read-only probes; it does not accept arbitrary
remote commands. Results are returned as JSON containing OS, architecture, kernel,
CPU count, memory, Python, Node.js, GPU, and container environment information.
Connections default to non-interactive authentication, disable forwarding, and
require the host fingerprint to already be trusted. The probe entry point does not
inherit `ProxyCommand` from the SSH configuration; targets that require a proxy
command should use the regular SSH scripts and be confirmed separately. OpenSSH
still reads the user configuration; if it contains `Match exec`, that may execute
local commands during configuration parsing, so only use the probe entry point with
trusted configurations.

Preview the fixed commands before running:

```bash
python scripts/ssh_probe.py <alias> --dry-run
```

### Upload File

```bash
python scripts/ssh_transfer.py upload <alias> "<local_path>" "<remote_path>"
```

### Download File

```bash
python scripts/ssh_transfer.py download <alias> "<remote_path>" "<local_path>"
```

### Establish Local Port Forwarding

```bash
python scripts/ssh_tunnel.py <alias> --local-port <local_port> --remote-host 127.0.0.1 --remote-port <remote_port>
```

Tunnel commands run in the foreground. Confirm termination method before running long-running background tasks.

## Initial Connection Host Key

`ssh_exec.py`, `ssh_transfer.py`, and `ssh_tunnel.py` all support:

```bash
--accept-new-host-key
--known-hosts-file <temporary_known_hosts_path>
```

- `--accept-new-host-key`: Allows OpenSSH to accept new host fingerprints once the device is confirmed trusted.
- `--known-hosts-file`: Specifies a custom `known_hosts` file. Use a temporary file during debugging to avoid polluting global `~/.ssh/known_hosts`.

Example:

```bash
python scripts/ssh_exec.py 1380-P904 "echo SSH_OK && uname -m" --accept-new-host-key
```

## Operational Boundaries

- Query tasks can be executed directly.
- The script must create a backup before adding or modifying `~/.ssh/config`.
- Confirm first before risky actions such as deleting configurations, overwriting remote files, deploying, running batch executions, or setting up port forwarding.
- Prioritize read-only checks when executing remote commands; confirm first if operations involve rebooting, deleting, overwriting, installing, or upgrading.
- If the script fails, preserve the actual stderr and do not swallow errors.

## Troubleshooting

Check in order:

1. `python scripts/ssh_config.py show <alias>`
2. Whether `ssh -G <alias>` can resolve HostName/User/Port
3. Whether `ssh-keygen -F <HostName>` already has the host key
4. Whether the key file exists and has appropriate permissions
5. Whether the `ProxyJump` alias is also present in `~/.ssh/config`
6. Whether the network is reachable and the port is open
7. Whether `--accept-new-host-key` needs to be explicitly appended on initial connection
