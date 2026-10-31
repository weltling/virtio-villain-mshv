#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Private ABI and IOCTL fixture checks; generic runner tests live upstream."""

import errno
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = (ROOT.parent / "virtio-villain").resolve()
sys.path.insert(0, str(FRAMEWORK / "lib/python"))
from villain import appliance  # noqa: E402


class AbiTests(unittest.TestCase):
    def test_one_case_per_source(self):
        sources = sorted((ROOT / "tests").glob("*/*.c"))
        prefixes = {"ml": "ml", "mr": "mr", "tlfs": "tl"}
        self.assertTrue(sources)
        for source in sources:
            with self.subTest(source=source.name):
                text = source.read_text()
                self.assertEqual(text.count("REGISTER_MSHV_TEST("), 1)
                self.assertIn(f"REGISTER_MSHV_TEST({source.stem.split('_')[0].upper()},", text)
                self.assertIn(source.parent.name, prefixes)
                self.assertEqual(prefixes[source.parent.name], source.stem[:2])

    def test_tlfs_sources_identify_requirements(self):
        sources = sorted((ROOT / "tests/tlfs").glob("*.c"))
        expected = {
            "TL0001": "7.8",
            "TL0002": "7.10.1",
            "TL0003": "7.2",
            "TL0004": "2.4",
            "TL0005": "9.4",
            "TL0006": "11.9"}
        catalog = appliance.source_catalog(
            sources, "REGISTER_MSHV_TEST", metadata=True, definitions=[ROOT / "lib/mshv.h"])
        self.assertEqual(set(catalog), set(expected))
        for source in sources:
            with self.subTest(source=source.name):
                text = source.read_text()
                name = source.stem.split("_")[0].upper()
                self.assertEqual(catalog[name][1:], ("6.0b", expected[name]))
                self.assertRegex(catalog[name][2], r"^\d+(?:\.\d+)+$")
                self.assertIn(f"TLFS 6.0b section {expected[name]}", text)
                self.assertIn("TLFS_SPEC_V6_0B,", text)
                self.assertNotIn("TLFS@", text)
                self.assertIn("Requires ", text)


@unittest.skipUnless(shutil.which("cc"), "C compiler required for fixture selftests")
class FixtureTests(unittest.TestCase):
    def test_cleanup_success_and_injected_failures(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            (root / "contract.h").write_text("#error Generated headers must not be used\n")
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
            compiled = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run(
                [str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout[-4096:])
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
                self.assertIn(f"{request} count=129:", result.stdout)
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
            self.assertIn("mshv TLFS mock checks passed", result.stdout)
            self.assertIn(
                "mshv-register unexpected write readback name=0x20011 high=0x0 low=0x0",
                result.stdout)


if __name__ == "__main__":
    unittest.main()
