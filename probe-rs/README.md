# probe-rs

The `probe-rs` skill is a debug backend in this repository designed to maintain the same JSON output schema and `workflow` orchestration style as the existing `jlink` and `openocd` skills.

## Capabilities

- Probe discovery: `list`
- Target info: `info`
- Flash / Erase / Reset: `flash`, `erase`, `reset`
- Memory access: `read-mem`, `write-mem`
- One-shot debugging: `probe_rs_gdb.py`
- RTT observation: `probe_rs_rtt.py`

## Configuration Examples

For machine-level `config.json`, refer to `config.example.json`.

Project-level `.embeddedskills/config.json`:

```json
{
  "probe-rs": {
    "chip": "STM32F407VGTx",
    "protocol": "swd",
    "probe": "",
    "speed": 4000,
    "connect_under_reset": false
  }
}
```

## Important Notes

- `probe-rs` relies on the external official CLI by default; installers are not bundled in this repository.
- `probe-rs` in `workflow` integrates only one-shot debugging and does not directly expose interactive DAP sessions.
- Non-root users on Linux need to install the official `probe-rs` udev rules (`69-probe-rs.rules` → `/etc/udev/rules.d/`) and run `sudo udevadm control --reload`.
- `probe-rs` and official SEGGER tools will contend for the same J-Link device; do not run them concurrently.
