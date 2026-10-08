"""Unit tests for jlink_exec.py JTAG handling, aborted-script detection and resume option."""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import jlink_exec  # noqa: E402

# Output captured from a real J-Link Lite V8 on a Cortex-A9 JTAG target when -JTAGConf is missing:
# JLinkExe asks for the JTAG chain position interactively and swallows the rest of the script.
ABORTED_STDOUT = """\
J-Link Command File read successfully.
Processing script file...
J-Link>si JTAG
Selecting JTAG as current target interface.
J-Link>speed 4000
Selecting 4000 kHz as target interface speed
J-Link>connect
Device position in JTAG chain (IRPre,DRPre) <Default>: -1,-1 => Auto-detect
Script processing completed.
"""

READ_MEM_STDOUT = """\
J-Link>connect
Found Cortex-A9 r4p1
Cortex-A9 identified.
J-Link>halt
PC: (R15) = 200A8FC0, CPSR = 8000001F (System mode, ARM)
J-Link>mem32 0x20000000,4
20000000 = E59FF018 E59FF018 E59FF018 E59FF018
J-Link>exit
Script processing completed.
"""


class TestBuildJlinkCmd:
    def test_jtag_adds_interface_and_jtagconf(self):
        cmd = jlink_exec.build_jlink_cmd("JLinkExe", "Cortex-A9", "s.jlink", "123456789",
                                         interface="JTAG", jtag_conf="-1,-1")
        assert cmd[cmd.index("-If") + 1] == "JTAG"
        assert cmd[cmd.index("-JTAGConf") + 1] == "-1,-1"

    def test_swd_does_not_add_jtagconf(self):
        cmd = jlink_exec.build_jlink_cmd("JLinkExe", "STM32F407VG", "s.jlink", "",
                                         interface="SWD", jtag_conf="-1,-1")
        assert "-JTAGConf" not in cmd
        assert cmd[cmd.index("-If") + 1] == "SWD"

    def test_interface_is_case_insensitive(self):
        cmd = jlink_exec.build_jlink_cmd("JLinkExe", "Cortex-A9", "s.jlink", "",
                                         interface="jtag", jtag_conf="0,0")
        assert cmd[cmd.index("-JTAGConf") + 1] == "0,0"


class TestParseOutput:
    def test_aborted_script_is_reported_as_error(self):
        parsed = jlink_exec.parse_output(ABORTED_STDOUT, "read-mem")
        assert parsed["error_code"] == "script_aborted"

    def test_completed_read_mem_returns_memory(self):
        parsed = jlink_exec.parse_output(READ_MEM_STDOUT, "read-mem")
        assert "error_code" not in parsed
        assert parsed["memory"][0] == {"address": "0x20000000",
                                       "data": "E59FF018 E59FF018 E59FF018 E59FF018"}
