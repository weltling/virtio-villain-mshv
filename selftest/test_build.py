#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify build target ordering and parallel goal deduplication."""

import gzip
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = ROOT.parent / "virtio-villain"


@unittest.skipUnless(shutil.which("make"), "Make required for build checks")
class BuildTests(unittest.TestCase):
    def test_kernel_target_disables_rust_probing_without_a_command_line_override(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            framework = root / "framework"
            framework.mkdir()
            (framework / "lib/python/villain").mkdir(parents=True)
            shutil.copyfile(
                FRAMEWORK / "lib/python/villain/initramfs.py",
                framework / "lib/python/villain/initramfs.py")
            (framework / "Makefile").write_text(
                ".PHONY: appliance\nappliance:\n"
                '\tpython3 "$(CURDIR)/build.py" "$(APPLIANCE_TARGET)"\n')
            (framework / "build.py").write_text(
                "from pathlib import Path\n"
                "import struct, sys\n"
                "output = Path(sys.argv[1])\n"
                "output.mkdir(parents=True, exist_ok=True)\n"
                "elf = bytearray(64)\n"
                "elf[:6] = b'\\x7fELF\\x02\\x01'\n"
                "struct.pack_into('<HH', elf, 54, 56, 0)\n"
                "(output / 'init').write_bytes(elf)\n")
            (root / "lib").mkdir()
            (root / "lib/contract.py").write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "output = Path(sys.argv[sys.argv.index('--output') + 1])\n"
                "output.parent.mkdir(parents=True, exist_ok=True)\n"
                "output.write_text('/* fixture contract */\\n')\n")
            source = root / "source"
            source.mkdir()
            config = source / "Microsoft/configs/x86/mshv_defconfig"
            config.parent.mkdir(parents=True)
            config.write_text("CONFIG_RUSTC_VERSION=0\nCONFIG_RUSTC_LLVM_VERSION=0\n")
            (source / "configure.py").write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "output = Path(sys.argv[1])\n"
                "output.mkdir(parents=True, exist_ok=True)\n"
                "version = '0' if sys.argv[2] == 'false' else '1'\n"
                "(output / '.config').write_text("
                "f'CONFIG_RUSTC_VERSION={version}\\nCONFIG_RUSTC_LLVM_VERSION={version}\\n')\n"
                "(output / 'compiler-origin').write_text(sys.argv[3])\n")
            (source / "Makefile").write_text(
                "RUSTC = rustc\n"
                ".PHONY: allnoconfig vmlinux bzImage\n"
                "allnoconfig:\n"
                '\tpython3 configure.py "$(O)" "$(RUSTC)" "$(origin RUSTC)"\n'
                "vmlinux:\n"
                '\t@test "$(RUSTC)" = false\n'
                '\tprintf "fixture image" > "$(O)/vmlinux"\n'
                "bzImage:\n"
                '\t@test "$(RUSTC)" = false\n'
                '\tmkdir -p "$(O)/arch/x86/boot"\n'
                '\tprintf "fixture image" > "$(O)/arch/x86/boot/bzImage"\n')
            record = root / "kernel-command.json"
            builder = framework / "build-kernel"
            builder.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, runpy, sys\n"
                "from pathlib import Path\n"
                f"Path({str(record)!r}).write_text(json.dumps("
                "{'rustc': os.environ.get('RUSTC'), 'argv': sys.argv[1:]}))\n"
                "for name in ('MAKEFLAGS', 'MAKEOVERRIDES'):\n"
                "    os.environ.pop(name, None)\n"
                f"runpy.run_path({str(FRAMEWORK / 'build-kernel')!r}, run_name='__main__')\n")
            builder.chmod(0o755)
            for overrides in ([], ["RUSTC=rustc"]):
                goals = ["init", "initramfs", "kernel", *overrides]
                with self.subTest(goals=goals):
                    subprocess.run([
                        "make", "--no-print-directory", "-j8", "-C", str(root),
                        "-f", str(ROOT / "Makefile"), f"VV_ROOT={framework}",
                        f"MSHV_SOURCE={root / 'source'}", *goals,
                    ], env=dict(os.environ, RUSTC="rustc"),
                        check=True, capture_output=True, text=True, timeout=20)
                    command = json.loads(record.read_text())
                    self.assertEqual(command["rustc"], "false")
                    arguments = command["argv"]
                    self.assertEqual(
                        arguments[arguments.index("--config") + 1],
                        str(root / "source/Microsoft/configs/x86/mshv_defconfig"))
                    self.assertIn("--offline", arguments)
                    self.assertTrue((root / "target/mshv/initramfs.cpio.gz").is_file())
                    self.assertTrue(
                        (root / "target/kernel-microsoft/images/bzImage-x86_64").is_file())
                    self.assertEqual(
                        (root / "target/kernel-microsoft/x86_64/compiler-origin").read_text(),
                        "command line")

    def test_standard_targets_and_aliases_share_one_build(self):
        for goals in (["init"], ["initramfs"],
                      ["init", "initramfs", "mshv", "mshv-initramfs"], []):
            with self.subTest(goals=goals), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                framework = root / "framework"
                (root / "lib").mkdir()
                (framework / "lib/python/villain").mkdir(parents=True)
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
                (framework / "lib/python/villain/initramfs.py").write_text(
                    "from pathlib import Path\n"
                    "import sys\n"
                    f"sys.path.insert(0, {str(FRAMEWORK / 'lib/python')!r})\n"
                    "from villain.initramfs import main\n"
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
