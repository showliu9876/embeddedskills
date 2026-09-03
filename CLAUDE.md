# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

`embeddedskills` is **not an application** — it is a collection of Agent Skills that let an AI
coding assistant drive embedded toolchains directly (build → flash → debug → observe) without a
human relaying output between steps.

Each top-level directory (`keil/`, `gcc/`, `eide/`, `jlink/`, `openocd/`, `probe-rs/`, `serial/`,
`can/`, `net/`, `ssh/`, `terminal/`, `workflow/`) is one self-contained skill. There is no build
system, no package manifest, no test suite, and no CI. The deliverable is the Python scripts plus
the `SKILL.md` that describes them to an AI agent.

Docs are written in English; match that when editing `SKILL.md` / `README.md`.
Code identifiers and log strings stay English.

This repo is a fork of `https://github.com/zhinkgit/embeddedskills.git`; upstream URLs in the
docs still point there.

## Running scripts

Every script is a standalone CLI invoked with the ambient `python` — no venv, no install step.
Only `serial`/`can`/`terminal` need third-party packages (`pyserial`, `python-can`, `cantools`);
everything else is stdlib-only by design. **Keep it that way** — do not add dependencies to a
stdlib-only skill.

```bash
python gcc/scripts/gcc_project.py scan --json
python gcc/scripts/gcc_build.py build --workspace /path/to/proj --json
python workflow/scripts/workflow_run.py build-flash --workspace /path/to/proj --json
```

`--json` is the machine-readable mode; without it scripts print `result["summary"]` only.
There is no lint/format/test command configured — verification is manual execution against a real
project directory or real hardware.

## Architecture

### Three-file state model (the core contract)

| File | Scope | Holds | Committed? |
|---|---|---|---|
| `<skill>/config.json` | machine-local | tool executable paths, local probe serials | no — gitignored; seeded from `config.example.json` |
| `<workspace>/.embeddedskills/config.json` | project, shared | project path, target, preset, chip, interface, log dirs | in the user's project |
| `<workspace>/.embeddedskills/state.json` | runtime history | `last_build` / `last_flash` / `last_debug` / `last_observe` and their artifacts | in the user's project |

The workspace is the **user's embedded project**, not this repo. Skill scripts always resolve it
via `--workspace` (default: cwd).

### Parameter resolution — priority depends on parameter *type*

This is the single most important invariant, specified in `docs/runtime-resolution-spec.md`:

- **Tool executables** (`exe`, `cmake_exe`, `gdb_exe`): `CLI > <skill>/config.json > system PATH > builtin command name`.
  Never read from project config or state; never auto-write back to `<skill>/config.json`.
- **Project/hardware params** (`project`, `target`, `preset`, `device`, `interface`, `speed`):
  `CLI > .embeddedskills/config.json > state.json > auto-discovery > default > error`.
  Never read from `<skill>/config.json`.
- **Artifact paths** (`elf`, `flash_file`): `CLI > project config > state.json > bounded workspace search > error`.
- **Runtime options** (`gdb_port`, `log_dir`): `CLI > project config > <skill>/config.json > state.json > default`.

PATH discovery must be **active** (`shutil.which()` against a candidate-name list), not a
post-failure fallback, and the source must be recorded as `path:cmake`, not bare `path`. When PATH
misses, a skill may probe that tool's standard install prefixes (`/opt/SEGGER/JLink`,
`/usr/share/openocd/scripts`, the VS Code extension tree) and record `install_dir:<abs path>`.

### Linux-first, Windows as a trailing fallback

Every skill except `keil` targets Linux. Defaults, config examples, and auto-discovery paths use
Linux conventions (`JLinkExe` / `JLinkGDBServerCLExe` / `JLinkRTTClient`, `/opt/SEGGER/JLink`,
`/usr/share/openocd/scripts`, `~/.vscode/extensions/.../res/tools/linux/x86_64/`, `/dev/ttyUSB0`,
SocketCAN, `lsusb`). Windows command names stay in the candidate lists but always **last**, as a
minimal compat layer — don't delete the existing platform branches, and don't promote them.

`keil` is the exception: `UV4.exe` has no Linux build, so that skill is left Windows-only and is
marked as such in `keil/SKILL.md`, `keil/README.md`, and the top-level READMEs. New code must not
copy `keil`'s Windows-oriented style.

Auto-discovery is allowed only when there is exactly one candidate (one project, one serial port,
one CAN interface). Ambiguous `device` / probe serial / `board` / `.bin` flash address must raise
an error — **never guess**.

### Per-skill runtime module

Each skill owns a private `scripts/<skill>_runtime.py`. These are **deliberately duplicated, not
shared** — a skill directory must work when installed standalone (`npx skills add --skill jlink`).
Do not refactor them into a common package.

Common helpers: `load_local_config`, `load_project_config` / `save_project_config`,
`load_workspace_state` / `update_state_entry`, `resolve_tool_param` / `resolve_project_param` /
`resolve_runtime_param` / `resolve_artifact_param`, `make_result`, `make_timing`,
`parameter_context`, `output_json`, `hidden_subprocess_kwargs`.

Note `gcc_runtime.py` still exposes the older single `resolve_param()`; the typed resolvers in
`docs/skill-template-reference.md` are the current target. New code should use the typed ones.

### Unified JSON result envelope

All scripts return the shape built by `make_result()`:

```json
{
  "status": "ok | error",
  "action": "build",
  "summary": "...",
  "details": {},
  "context": { "provider": "gcc", "workspace": "...", "parameter_sources": {"exe": "path:cmake"} },
  "artifacts": {}, "metrics": {}, "state": {}, "next_actions": [], "timing": {}, "error": {}
}
```

`context.parameter_sources` is how the agent explains *where each value came from* — populate it
for every resolved parameter. Empty values are stripped by `compact_dict()`. Timestamps are
ISO-8601 with local offset via `now_iso()`.
Streaming commands (serial/CAN/net monitors) emit JSON Lines with `source`, `channel_type`,
`stream_type`, `timestamp` instead.

### `workflow` is a thin orchestrator

`workflow/scripts/workflow_run.py` does **not** reimplement any tool logic. It computes
`ROOT_DIR = parents[2]` (the repo root), then shells out to sibling skills with `sys.executable`
and `--json`, parsing stdout via `run_json()`. Backend selection: explicit CLI arg →
`workflow.preferred_*` in project config → auto (exactly one candidate, else an error listing the
candidates). Build backends: `keil` / `gcc` / `eide`. Flash/debug/observe backends: `jlink` /
`openocd` / `probe-rs` — the two axes combine freely.

Because of this, a change to any leaf skill's CLI flags or JSON keys can silently break
`workflow`. Grep `workflow/scripts/workflow_run.py` for the skill name before renaming a flag.

## Adding or modifying a skill

Follow `docs/skill-template-reference.md`. Required layout:

```
<skill>/
├── SKILL.md              # YAML frontmatter: name, description, argument-hint
├── README.md
├── config.example.json   # machine-level template; config.json itself is gitignored
├── scripts/<skill>_runtime.py + one script per concern
├── references/           # optional lookup data
└── templates/            # optional tool script templates (.jlink, .cfg, ...)
```

The `SKILL.md` `description` is what triggers the skill — it must enumerate concrete trigger terms
and phrasings, not just describe capability (see `gcc/SKILL.md` for the pattern).

Entry-script order is fixed: parse CLI → load local/project/state config → resolve via runtime
helpers → validate required → invoke tool → parse output → write back config/state → emit JSON.

Checklist before finishing:
- separate runtime module, three config layers honored
- active PATH probing with recorded source labels
- JSON envelope with `parameter_sources`
- confirmed project params written back to `.embeddedskills/config.json`, run record to `state.json`
- priority documented in `SKILL.md`
- no machine-absolute paths written into project config

## Known inconsistencies to respect when editing

`docs/runtime-resolution-spec.md` lists deviations that are still open: `can`/`serial`/`net` helper
docs vs. actual calls, two conflicting priority descriptions inside `jlink` and `openocd`
`SKILL.md`, `openocd_telnet.py` not aligned with its siblings, missing PATH layer in `probe-rs`
docs, and the "three-layer config" wording in `README.md` / `docs/getting-started.md` that predates
the PATH layer. Prefer converging on the spec rather than copying a neighbouring file's older style.

The former `README.en.md` / `docs/getting-started.en.md` duplicates were removed once the docs
became English-only. Do not reintroduce them.
