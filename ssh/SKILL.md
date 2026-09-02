---
name: ssh
description: SSH / server operations assistant. Used for remote servers, user@host, SSH configuration, uploads/downloads, deployment, jump hosts, tunneling, port forwarding, and executing server commands; uses Host aliases in ~/.ssh/config as the sole server inventory, favors key-based authentication, and wraps OpenSSH operations via Python scripts in this skill.
---

# SSH Skill

## Positioning

This is a lightweight SSH operations gateway. It does not maintain an independent server database; by default it only reads and writes standard OpenSSH configuration:

```text
~/.ssh/config
```

Core principles:

- Use `Host` aliases to identify servers; do not memorize IPs or passwords directly.
- Favor key-based authentication and native OpenSSH commands.
- Execute SSH, SCP, configuration inspection, and tunneling operations via scripts in `scripts/` of this skill.
- Prefer fixed read-only probing for environment identification instead of composing ad-hoc collection scripts from arbitrary commands.
- Automatically backup `~/.ssh/config` before writing to it.
- Discourage storing plaintext passwords on disk; if a password must be used, let OpenSSH prompt interactively or have the user configure secure credentials.

## When to Trigger

Use this skill when the user mentions any of the following tasks:

- SSH, remote servers, server IP/hostname, `user@host`
- Logging in, executing remote commands, checking server status
- Uploading, downloading, deploying, or migrating files
- Jump hosts, `ProxyJump`, intranet/bastion access
- Tunnels, port forwarding, database connections
- Configuring `~/.ssh/config`, adding/searching server aliases

Do not use for local `localhost`, current directory, local file operations, or general networking concept explanations.

## Script Entry Points

Prefer invoking scripts from the current skill directory. The scripts directory is:

```text
scripts/
```

All command examples are based on the skill directory.

## Common Commands

`ssh_exec.py`, `ssh_transfer.py`, and `ssh_tunnel.py` all support:

```bash
--accept-new-host-key
--known-hosts-file <temporary_known_hosts_path>
```

When connecting to a newly verified trusted dev board for the first time, you may explicitly append `--accept-new-host-key`. If you prefer not to write to the global `known_hosts` during testing, append `--known-hosts-file <temporary_known_hosts_path>`.

### List Servers

```bash
python scripts/ssh_config.py list
```

### Search Servers

```bash
python scripts/ssh_config.py find <keyword>
python scripts/ssh_config.py find <environment_keyword> <capability_keyword>
```

Multiple keywords use AND matching. Narrow down by environment group first, then
confirm the target by device alias or tag. `search` is an alias for `find`.

### Resolve a Unique Server

```bash
python scripts/ssh_config.py resolve <keyword...>
```

Proceed only when the result is unique. Exit code 2 indicates multiple candidates
exist; you must confirm with the user and must not automatically pick the first
one. Exact OpenSSH `Host` aliases take priority.

### Verify Alias Resolution

```bash
python scripts/ssh_config.py show <alias>
```

### Add Server

The script automatically backs up `~/.ssh/config` before writing:

```bash
python scripts/ssh_config.py add <alias> --host <IP_or_domain> --user <user> --port 22 --key ~/.ssh/id_ed25519
```

Optional arguments:

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
python scripts/ssh_exec.py <alias> "command" --timeout 30
```

The script outputs JSON containing `success`, `exit_code`, `stdout`, and `stderr`.

### Probe Remote Environment

```bash
python scripts/ssh_probe.py <alias>
```

The probe script only runs built-in read-only commands and outputs structured
JSON. It enables non-interactive authentication by default, disables port and
agent forwarding, and requires the host fingerprint to already be trusted. Use
`--dry-run` to preview the commands first; only use `--accept-new-host-key` once
a new device is confirmed trusted. The probe entry point explicitly disables
`ProxyCommand` from the SSH configuration — do not use it to connect to targets
that require a proxy command. OpenSSH still parses the user configuration; if the
configuration contains `Match exec`, it may execute local commands, so only use
the probe entry point with trusted SSH configurations.

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

Tunnel commands run in the foreground. When long-running background persistence is required, explain the impact and termination method to the user first.

## Configuration Format

Recommended configuration:

```ssh-config
# description: Dev Board
# aliases: test-board,main-controller
# groups: lab-test-env
# tags: embedded,linux
# location: lab
Host 1380-P904
    HostName 192.168.137.76
    User root
    Port 22
    IdentityFile ~/.ssh/id_ed25519
```

Jump host:

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

Comment metadata supported:

- `description`
- `aliases`
- `groups`
- `tags`
- `location`

Never write plaintext passwords, tokens, private key contents, or other sensitive information into the configuration.

## Operational Rules

- Query tasks can be executed directly.
- The script must create a backup before adding or modifying `~/.ssh/config`.
- Confirm with the user first before risky actions such as deleting configurations, overwriting remote files, deploying, running batch executions, or setting up port forwarding.
- Do not run raw `ssh`/`scp` directly; prefer scripts in this skill. Only explain the reason and fall back to native commands if scripts are unavailable or explicitly requested by the user.
- Do not modify Git, system services, firewalls, or remote production configurations unless explicitly requested by the user.
- Prioritize read-only checks when executing remote commands; confirm first if operations involve rebooting, deleting, overwriting, installing, or upgrading.
- When reporting to the user, state the target alias, actual HostName, executed command, key results, and reason for failure.

## Troubleshooting

Check in order:

1. `python scripts/ssh_config.py show <alias>`
2. Whether `ssh -G <alias>` can resolve HostName/User/Port
3. Whether the key file exists and has appropriate permissions
4. Whether the `ProxyJump` alias is also present in `~/.ssh/config`
5. Whether the network is reachable and the port is open
6. Whether `--accept-new-host-key` needs to be explicitly appended on initial connection

If the script fails, preserve the actual stderr and do not swallow errors.
