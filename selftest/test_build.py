#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify build target ordering and parallel goal deduplication."""

import gzip
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = ROOT.parent / "virtio-villain"


@unittest.skipUnless(shutil.which("make"), "Make required for build checks")
class BuildTests(unittest.TestCase):
    def test_standard_targets_and_aliases_share_one_build(self):
        for goals in (["init"], ["initramfs"],
                      ["init", "initramfs", "mshv", "mshv-initramfs"], []):
            with self.subTest(goals=goals), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                framework = root / "framework"
                (root / "lib").mkdir()
                (framework / "lib").mkdir(parents=True)
                events = root / "events"
                (root / "lib/contract.py").write_text(
                    "from pathlib import Path\n"
                    "import sys\n"
                    f"with Path({str(events)!r}).open('a') as stream:\n"
                    "    stream.write('contract\\n')\n"
                    "output = Path(sys.argv[sys.argv.index('--output') + 1])\n"
                    "output.parent.mkdir(parents=True, exist_ok=True)\n"
                    "output.write_text('/* fixture contract */\\n')\n")
                (framework / "Makefile").write_text(
                    ".PHONY: appliance\nappliance:\n"
                    '\tpython3 "$(CURDIR)/build.py" "$(APPLIANCE_TARGET)"\n')
                (framework / "build.py").write_text(
                    "from pathlib import Path\n"
                    "import struct, sys\n"
                    f"with Path({str(events)!r}).open('a') as stream:\n"
                    "    stream.write('link\\n')\n"
                    "output = Path(sys.argv[1])\n"
                    "output.mkdir(parents=True, exist_ok=True)\n"
                    "elf = bytearray(64)\n"
                    "elf[:6] = b'\\x7fELF\\x02\\x01'\n"
                    "struct.pack_into('<HH', elf, 54, 56, 0)\n"
                    "(output / 'init').write_bytes(elf)\n")
                (framework / "lib/initramfs.py").write_text(
                    "from pathlib import Path\n"
                    "import sys\n"
                    f"sys.path.insert(0, {str(FRAMEWORK)!r})\n"
                    "from lib.initramfs import main\n"
                    f"with Path({str(events)!r}).open('a') as stream:\n"
                    "    stream.write('pack\\n')\n"
                    "main()\n")
                subprocess.run([
                    "make", "--no-print-directory", "-j8", "-C", str(root),
                    "-f", str(ROOT / "Makefile"), f"VV_ROOT={framework}", *goals,
                ], check=True, capture_output=True, text=True, timeout=20)
                archive = root / "target/mshv/initramfs.cpio.gz"
                self.assertTrue((root / "target/mshv/init").is_file())
                expected = ["contract", "link"]
                if goals != ["init"]:
                    expected.append("pack")
                    self.assertIn(b"init\0", gzip.decompress(archive.read_bytes()))
                else:
                    self.assertFalse(archive.exists())
                self.assertEqual(events.read_text().splitlines(), expected)
