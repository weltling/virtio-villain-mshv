#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Private contract and IOCTL-fixture checks; generic runner tests live upstream."""

import errno
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
    def test_extract_partition_flag_and_isolation_enumerations(self):
        enums = (
            "enum { MSHV_PT_BIT_LAPIC, MSHV_PT_BIT_NESTED_VIRTUALIZATION, "
            "MSHV_PT_BIT_COUNT };",
            "enum { MSHV_PT_ISOLATION_NONE, MSHV_PT_ISOLATION_SNP, "
            "MSHV_PT_ISOLATION_COUNT };")
        with tempfile.TemporaryDirectory() as work:
            source = Path(work)
            header = source / "include/uapi/linux/mshv.h"
            header.parent.mkdir(parents=True)
            declarations = [
                *(f"struct {name} {{ __u64 value; }};" for name in contract.STRUCTS),
                *(f"#define {name} 0" for name in contract.DEFINES)]
            for missing in (None, *range(len(enums))):
                with self.subTest(missing=missing):
                    header.write_text("\n".join([
                        *declarations,
                        *(enum for index, enum in enumerate(enums) if index != missing)]))
                    with patch.object(contract.subprocess, "check_output",
                                      side_effect=[contract.COMMIT, ""]):
                        if missing is None:
                            extracted = contract.extract(source)
                            for enum in enums:
                                self.assertIn(enum, extracted)
                        else:
                            with self.assertRaisesRegex(
                                    RuntimeError, "Missing UAPI enumeration"):
                                contract.extract(source)

    def test_one_case_per_source(self):
        sources = sorted((ROOT / "tests").glob("*/*.c"))
        self.assertTrue(sources)
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
                "enum { MSHV_PT_ISOLATION_NONE, MSHV_PT_ISOLATION_SNP, "
                "MSHV_PT_ISOLATION_COUNT };",
                "struct mshv_create_partition { __u64 pt_flags; __u64 pt_isolation; };",
                "struct mshv_create_vp { __u32 vp_index; };",
                "struct mshv_vp_registers { __u32 count; __u32 padding; "
                "struct hv_register_assoc *regs; };",
                "#define MSHV_IOCTL 0xb8",
                "#define MSHV_CREATE_PARTITION _IOW(MSHV_IOCTL, 0, struct mshv_create_partition)",
                "#define MSHV_INITIALIZE_PARTITION _IO(MSHV_IOCTL, 0)",
                "#define MSHV_CREATE_VP _IOW(MSHV_IOCTL, 1, struct mshv_create_vp)",
                "#define MSHV_GET_VP_REGISTERS _IOWR(MSHV_IOCTL, 0xf0, struct mshv_vp_registers)",
                "#define MSHV_SET_VP_REGISTERS _IOW(MSHV_IOCTL, 0xf1, struct mshv_vp_registers)",
            ]
            binary = root / "test-mshv"
            (root / "cpuid.h").write_text(
                "void mshv_test_cpuid(unsigned, unsigned *, unsigned *, unsigned *, unsigned *);\n"
                "#define __cpuid(leaf, a, b, c, d) "
                "mshv_test_cpuid((leaf), &(a), &(b), &(c), &(d))\n")
            command = ["cc", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT),
                       "-I", str(FRAMEWORK), "-I", str(root), str(ROOT / "selftest/test_mshv.c"),
                       str(ROOT / "lib/appliance.c"),
                       str(ROOT / "lib/lifecycle.c"), str(ROOT / "lib/registers.c"),
                       *(str(source) for source in sorted((ROOT / "tests").glob("*/*.c"))),
                       "-pthread", "-Wl,--wrap=open,--wrap=close,--wrap=fcntl,--wrap=ioctl",
                       "-Wl,--wrap=getrlimit,--wrap=setrlimit",
                       "-o", str(binary)]
            for limit in (128, 64):
                with self.subTest(limit=limit):
                    (root / "contract.h").write_text(
                        "\n".join([*header, f"#define MSHV_VP_MAX_REGISTERS {limit}"]) + "\n")
                    subprocess.run(command, check=True, capture_output=True)
                    result = subprocess.run(
                        [str(binary)], check=True, capture_output=True, text=True)
                    self.assertIn(
                        "MSHV_CREATE_PARTITION flags=0xabc isolation=0x123456789abcdef0: "
                        f"expected resource fd >= 0, actual -1 errno={errno.EACCES}",
                        result.stdout)
                    self.assertIn(
                        "MSHV_CREATE_VP index=7: fd=20 expected F_GETFD with FD_CLOEXEC, "
                        "actual 0 errno=0", result.stdout)
                    self.assertIn(
                        "MSHV_CREATE_VP index=7: fd=20 expected F_GETFD with FD_CLOEXEC, "
                        f"actual -1 errno={errno.EBADF}", result.stdout)
                    self.assertIn("MSHV_CREATE_PARTITION flags=0x0 isolation=0x0:", result.stdout)
                    self.assertIn("MSHV_CREATE_VP index=0:", result.stdout)
                    for request in ("GET", "SET"):
                        self.assertIn(f"{request} count={limit + 1}:", result.stdout)
                        self.assertIn(
                            f"{request} count=1 NULL register array:", result.stdout)
                    for count in (0, 5):
                        self.assertIn(
                            f"internal register count: expected 1..4, actual {count}",
                            result.stdout)
                    for cycle in (1, 128):
                        self.assertIn(f"mshv-cycle {cycle}/128\n", result.stdout)
                    for cycle in (1, 32):
                        self.assertIn(
                            f"mshv-isolation cycle {cycle}/32 create A with VP index=0\n",
                            result.stdout)
                    self.assertIn(
                        "mshv-isolation cycle 1/32 close A VP first\n", result.stdout)
                    self.assertIn(
                        "mshv-isolation cycle 2/32 close A parents first\n", result.stdout)
                    for diagnostic in (
                            "no hypervisor CPUID bit", "Hyper-V feature leaf unavailable",
                            "expected Hv#1 CPUID interface signature",
                            "requires CreatePartitions (HV_CREATE_PARTITIONS) "
                            "without HV_ISOLATION"):
                        self.assertIn(diagnostic, result.stdout)
                    self.assertEqual(
                        result.stdout.count("prerequisite lifecycle failed"), 4)
                    self.assertIn("mshv mock checks passed", result.stdout)
                    self.assertIn("mshv isolation mock checks passed", result.stdout)
                    for cycle in (1, 64):
                        self.assertIn(
                            f"mshv-concurrency A cycle {cycle}/64 create with VP index=0",
                            result.stdout)
                    self.assertIn("mshv-concurrency A completed 64/64 cycles", result.stdout)
                    self.assertIn("mshv-concurrency check B after A worker exit", result.stdout)
                    self.assertIn("mshv concurrency mock checks passed", result.stdout)
                    self.assertIn(
                        "mshv-unwind completed 64 cycles, 512 partition and 512 VP EMFILE failures",
                        result.stdout)
                    self.assertIn("mshv unwind mock checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
