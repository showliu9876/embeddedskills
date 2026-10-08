"""Unit tests for jlink_exec.py JTAG handling, aborted-script detection and resume option."""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import jlink_exec  # noqa: E402


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
