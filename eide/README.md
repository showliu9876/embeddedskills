# eide

Claude Code skill for driving EIDE (Embedded IDE) to scan projects, enumerate build configurations, compile and build, and return artifact paths to hand over to `jlink/openocd`.

## Features

- Scan directories for EIDE projects (directories containing `.eide/eide.yml`)
- Enumerate build configurations in projects (ConfigName)
- Incremental build / Full rebuild / Clean
- Return artifact paths such as `elf_file` / `hex_file` for seamless handover to `jlink/openocd`
- ELF size analysis (text/data/bss and memory usage)
- Parse build logs and output structured error/warning information

## Requirements

- [VS Code](https://code.visualstudio.com/) — Provides the `code` CLI
- [EIDE Extension](https://marketplace.visualstudio.com/items?itemName=cl.eide) — Provides `unify_builder`
- ARM CC (AC5/AC6) or arm-none-eabi-gcc — Toolchain
- Python 3.x — Runs scripts (PyYAML required)
- PyYAML — `pip install pyyaml`

## Configuration

### Environment-level Configuration (skill/config.json)

Copy `config.example.json` to `config.json` and adjust according to the actual installation paths:

```json
{
  "builder_dir": "~/.vscode/extensions/cl.eide-3.27.0/res/tools/linux/x86_64/unify_builder",
  "builder_exe": "unify_builder",
  "code_exe": "code",
  "toolchain_prefix": "arm-none-eabi-",
  "operation_mode": 1
}
```

| Field | Required | Description |
|---|---|---|
| `builder_dir` | No | Directory where EIDE unify_builder resides; when empty, auto-probes `~/.vscode`, `~/.vscode-server`, `~/.vscode-oss`, `~/.cursor` extension directories |
| `builder_exe` | No | Builder executable file name, defaults to `unify_builder` |
| `code_exe` | No | VS Code CLI path, searched from PATH for `code`/`codium`/`code-oss`/`code-insiders` by default |
| `toolchain_prefix` | No | Toolchain prefix used for size analysis, defaults to `arm-none-eabi-` |
| `operation_mode` | No | `1` execute directly / `2` output risk summary / `3` require confirmation before execution |

### Project-level Configuration (workspace/.embeddedskills/config.json)

Project-level shared configuration is stored in `.embeddedskills/config.json` within the workspace:

```json
{
  "eide": {
    "project": "",
    "config": "",
    "log_dir": ".embeddedskills/build"
  }
}
```

| Field | Description |
|---|---|
| `project` | Default project root directory (relative to workspace, containing `.eide/eide.yml`) |
| `config` | Default build configuration name |
| `log_dir` | Build log output directory, defaults to `.embeddedskills/build` |

### Parameter Resolution Precedence

Parameter resolution order (from highest to lowest):
1. CLI explicit arguments
2. Environment-level configuration (skill/config.json)
3. Project-level configuration (.embeddedskills/config.json)
4. state.json (last build record)
5. Search / Prompt user
