#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Private contract and IOCTL-fixture checks; generic runner tests live upstream."""

import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = ROOT.parent / "virtio-villain"
spec = importlib.util.spec_from_file_location("mshv_contract", ROOT / "lib/contract.py")
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


class ContractTests(unittest.TestCase):
    def test_one_case_per_source(self):
        sources = sorted((ROOT / "tests").glob("*/*.c"))
        self.assertEqual(len(sources), 7)
        for source in sources:
            with self.subTest(source=source.name):
                text = source.read_text()
                self.assertEqual(text.count("REGISTER_MSHV_TEST("), 1)
                self.assertIn(f"REGISTER_MSHV_TEST({source.stem.split('_')[0].upper()},", text)
                self.assertEqual(source.parent.name, source.stem[:2])

    def test_reject_unreviewed_or_dirty_source(self):
        for responses in (["wrong"], [contract.COMMIT, " M drivers/hv/mshv_root_main.c"]):
            with self.subTest(responses=responses), \
                 patch.object(contract.subprocess, "check_output", side_effect=responses), \
                 self.assertRaises(RuntimeError):
                contract.extract(Path("/unused"))


@unittest.skipUnless(shutil.which("cc"), "C compiler required for fixture selftests")
class FixtureTests(unittest.TestCase):
    def test_cleanup_success_and_injected_failures(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            header = [
                f'#define VV_MSHV_CONTRACT "{contract.COMMIT}"',
                "struct mshv_create_partition { __u64 pt_flags; __u64 pt_isolation; };",
                "struct mshv_create_vp { __u32 vp_index; };",
                "struct mshv_vp_registers { __u32 count; __u32 padding; "
                "struct hv_register_assoc *regs; };",
                "#define MSHV_IOCTL 0xb8",
                "#define MSHV_VP_MAX_REGISTERS 128",
                "#define MSHV_CREATE_PARTITION _IOW(MSHV_IOCTL, 0, struct mshv_create_partition)",
                "#define MSHV_INITIALIZE_PARTITION _IO(MSHV_IOCTL, 0)",
                "#define MSHV_CREATE_VP _IOW(MSHV_IOCTL, 1, struct mshv_create_vp)",
                "#define MSHV_GET_VP_REGISTERS _IOWR(MSHV_IOCTL, 0xf0, struct mshv_vp_registers)",
                "#define MSHV_SET_VP_REGISTERS _IOW(MSHV_IOCTL, 0xf1, struct mshv_vp_registers)",
            ]
            (root / "contract.h").write_text("\n".join(header) + "\n")
            binary = root / "test-mshv"
            command = ["cc", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT),
                       "-I", str(FRAMEWORK), "-I", str(root), str(ROOT / "selftest/test_mshv.c"),
                       str(ROOT / "lib/lifecycle.c"), str(ROOT / "lib/registers.c"),
                       *(str(source) for source in sorted((ROOT / "tests").glob("*/*.c"))),
                       "-Wl,--wrap=open,--wrap=close,--wrap=fcntl,--wrap=ioctl",
                       "-o", str(binary)]
            subprocess.run(command, check=True, capture_output=True)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
            self.assertIn("mshv mock checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
