#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Verify build target ordering and parallel goal deduplication."""

import gzip
from itertools import product
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = (ROOT.parent / "virtio-villain").resolve()


def install_build_fixture(root, framework):
    library = framework / "lib/python/villain"
    library.mkdir(parents=True, exist_ok=True)
    for source in (FRAMEWORK / "lib/python/villain").glob("*.py"):
        destination = library / source.name
        if not destination.exists():
            shutil.copyfile(source, destination)
    shutil.copyfile(FRAMEWORK / "lib/suite.mk", framework / "lib/suite.mk")
    (root / "lib").mkdir(exist_ok=True)
    for name in ("build.py", "sources.py"):
        destination = root / "lib" / name
        if not destination.exists():
            shutil.copyfile(ROOT / "lib" / name, destination)
    (root / "kernel").mkdir(exist_ok=True)
    for source in (ROOT / "kernel").glob("*.config"):
        destination = root / "kernel" / source.name
        if not destination.exists():
            shutil.copyfile(source, destination)
    (root / "lib/suite.py").write_text(
        "from pathlib import Path\n"
        "from villain.appliance import Suite\n"
        "from .build import create_build\n"
        "def create_suite():\n"
        "    build = create_build(Path(__file__).resolve().parents[1])\n"
        "    context = build.context()\n"
        "    return Suite('fixture', 'fixture-v1', context.binary, context.initramfs,\n"
        "                 build_spec=build)\n")
    for name in ("bin/mshv.c", "lib/appliance.c", "lib/lifecycle.c", "lib/registers.c"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("/* fixture source */\n")


class KernelConfigTests(unittest.TestCase):
    def test_x86_fragments_preserve_required_appliance_options(self):
        fragments = [
            {line for line in (ROOT / "kernel" / name).read_text().splitlines()
             if line.startswith("CONFIG_")}
            for name in ("common.config", "x86_64.config")]
        common, x86 = fragments
        self.assertTrue(common.isdisjoint(x86))
        self.assertEqual(x86, {
            "CONFIG_EFI_HANDOVER_PROTOCOL=y", "CONFIG_SERIAL_8250_CONSOLE=y",
            "CONFIG_DMI=y", "CONFIG_DMIID=y"})
        self.assertEqual(common | x86, {
            "CONFIG_64BIT=y", "CONFIG_MSHV_ROOT=y", "CONFIG_HYPERV=y",
            "CONFIG_HYPERV_VMBUS=y", "CONFIG_EFI_STUB=y",
            "CONFIG_EFI_HANDOVER_PROTOCOL=y", "CONFIG_BLK_DEV_INITRD=y",
            "CONFIG_RD_GZIP=y", "CONFIG_BINFMT_ELF=y",
            "CONFIG_SERIAL_8250_CONSOLE=y", "CONFIG_DEVTMPFS=y",
            "CONFIG_PROC_FS=y", "CONFIG_SYSFS=y", "CONFIG_DMI=y", "CONFIG_DMIID=y"})

    def test_arm64_fragment_requires_4k_pages_without_x86_boot_options(self):
        common, arm = [
            {line for line in (ROOT / "kernel" / name).read_text().splitlines()
             if line.startswith("CONFIG_")}
            for name in ("common.config", "aarch64.config")]
        self.assertTrue(common.isdisjoint(arm))
        self.assertTrue({
            "CONFIG_ARM64=y", "CONFIG_ARM64_4K_PAGES=y", "CONFIG_EFI=y",
            "CONFIG_ACPI=y", "CONFIG_SERIAL_AMBA_PL011=y",
            "CONFIG_SERIAL_AMBA_PL011_CONSOLE=y"}.issubset(arm))
        self.assertIn("CONFIG_MSHV_ROOT=y", common | arm)
        self.assertNotIn("CONFIG_EFI_HANDOVER_PROTOCOL=y", common | arm)
        self.assertNotIn("CONFIG_SERIAL_8250_CONSOLE=y", common | arm)


@unittest.skipUnless(shutil.which("make"), "Make required for build checks")
class BuildTests(unittest.TestCase):
    def test_relocated_selftests_use_the_sibling_framework(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            suite = root / "suite"
            tests = suite / "selftest"
            tests.mkdir(parents=True)
            modules = ("test_build", "test_mshv", "test_boot_image", "test_policy")
            for name in modules:
                shutil.copyfile(ROOT / "selftest" / f"{name}.py", tests / f"{name}.py")
            (suite / "lib").mkdir()
            shutil.copyfile(ROOT / "lib/boot_image.py", suite / "lib/boot_image.py")
            (root / "virtio-villain").symlink_to(FRAMEWORK, target_is_directory=True)
            environment = dict(os.environ, PYTHONPATH=str(tests))
            result = subprocess.run([
                sys.executable, "-c",
                "import importlib\n"
                "from pathlib import Path\n"
                f"expected = Path({str(FRAMEWORK.resolve())!r})\n"
                f"for name in {modules!r}:\n"
                "    module = importlib.import_module(name)\n"
                "    assert module.FRAMEWORK == expected, name\n"
                "import villain\n"
                "assert Path(villain.__file__).resolve().parent == "
                "expected / 'lib/python/villain'\n",
            ], cwd=root, env=environment,
                capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_build_and_wrapper_use_the_same_framework_location(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            suite = root / "checkouts/mshv"
            suite.mkdir(parents=True)
            for name in ("Makefile", "run"):
                shutil.copy(ROOT / name, suite / name)
            record = root / "wrapper.json"
            default = suite.parent / "virtio-villain"
            alternate = root / "alternate"
            default.mkdir()
            runner = default / "run"
            runner.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "from pathlib import Path\n"
                f"Path({str(record)!r}).write_text(json.dumps("
                "{'runner': __file__, 'argv': sys.argv[1:]}))\n")
            runner.chmod(0o755)
            environment = dict(os.environ, HOME=str(root / "unrelated-home"))
            environment.pop("VV_ROOT", None)
            result = subprocess.run([
                "make", "--no-print-directory", "-C", str(root),
                "-f", str(suite / "Makefile"), "help",
            ], env=environment, check=True, capture_output=True,
                text=True, timeout=20)
            self.assertIn(f"(current: {default})", result.stdout)
            subprocess.run([
                str(suite / "run"), "--list",
            ], cwd=root, env=environment, check=True,
                capture_output=True, text=True, timeout=20)
            self.assertEqual(json.loads(record.read_text()), {
                "runner": str(default / "run"),
                "argv": ["--suite", str(suite), "--list"]})
            result = subprocess.run([
                "make", "--no-print-directory", "-C", str(root),
                "-f", str(suite / "Makefile"), f"VV_ROOT={alternate}", "help",
            ], env=environment, check=True, capture_output=True,
                text=True, timeout=20)
            self.assertIn(f"(current: {alternate})", result.stdout)

    def test_source_selection_failure_stops_the_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copyfile(ROOT / "Makefile", root / "Makefile")
            (root / "lib").mkdir()
            (root / "lib/sources.py").write_text(
                "raise SystemExit('fixture source selection failure')\n")
            framework = root / "framework"
            framework.mkdir()
            marker = root / "unexpected-build"
            (framework / "Makefile").write_text(
                f"appliance:\n\t@touch '{marker}'\n")
            install_build_fixture(root, framework)
            result = subprocess.run([
                "make", "--no-print-directory", "-C", str(root),
                f"VV_ROOT={framework}", "init",
            ], capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("fixture source selection failure", result.stderr)
            self.assertFalse(marker.exists())

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
            source = root / "source tree"
            source.mkdir()
            config = source / "Microsoft/configs/x86/mshv_defconfig"
            config.parent.mkdir(parents=True)
            config.write_text("CONFIG_RUSTC_VERSION=0\nCONFIG_RUSTC_LLVM_VERSION=0\n")
            (source / "configure.py").write_text(
                "from pathlib import Path\n"
                "import os, re, sys\n"
                "output = Path(sys.argv[1])\n"
                "output.mkdir(parents=True, exist_ok=True)\n"
                "version = '0' if sys.argv[2] == 'false' else '1'\n"
                "text = Path(os.environ['KCONFIG_ALLCONFIG']).read_text()\n"
                "for name in ('CONFIG_RUSTC_VERSION', 'CONFIG_RUSTC_LLVM_VERSION'):\n"
                "    text = re.sub('^' + name + '=.*$', name + '=' + version, "
                "text, flags=re.MULTILINE)\n"
                "(output / '.config').write_text(text)\n"
                "(output / 'compiler-origin').write_text(sys.argv[3])\n")
            (source / "Makefile").write_text(
                "RUSTC = rustc\n"
                ".PHONY: allnoconfig vmlinux bzImage\n"
                "allnoconfig:\n"
                '\tpython3 configure.py "$(O)" "$(RUSTC)" "$(origin RUSTC)"\n'
                "vmlinux:\n"
                '\tprintf "%s" "$(RUSTC)" > "$(O)/vmlinux-rustc"\n'
                '\tprintf "fixture image" > "$(O)/vmlinux"\n'
                "bzImage:\n"
                '\tprintf "%s" "$(RUSTC)" > "$(O)/bzImage-rustc"\n'
                '\tmkdir -p "$(O)/arch/x86/boot"\n'
                '\tprintf "fixture image" > "$(O)/arch/x86/boot/bzImage"\n')
            record = root / "kernel-command.json"
            install_build_fixture(root, framework)
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
            base, fragment, rust = (root / name for name in (
                "base.config", "fragment.config", "rust.config"))
            base.write_text(config.read_text() + "CONFIG_FIXTURE=m\n")
            fragment.write_text("CONFIG_FIXTURE=y\n")
            rust.write_text("CONFIG_RUSTC_VERSION=1\nCONFIG_RUSTC_LLVM_VERSION=1\n")
            default = root / "target/kernel"
            strict_output = root / "strict-kernel"
            custom = root / "custom-kernel"
            rust_output = root / "rust-kernel"
            environment = dict(os.environ, RUSTC="rustc")
            environment.pop("KERNEL_CONFIGS", None)
            cases = (
                ([], [config], "false", default),
                (["KERNEL_CONFIGS=   "], [config], "false", default),
                ([f'KERNEL_CONFIGS="{config}"', f"KERNEL_ARGS=--output {strict_output}"],
                 [config], "false", strict_output),
                ([f'KERNEL_CONFIGS="{config}"', "RUSTC=false",
                  f"KERNEL_ARGS=--output {strict_output}"], [config], "false", strict_output),
                ([f"KERNEL_CONFIGS={base} {fragment}",
                  f"KERNEL_ARGS=--output {custom} --jobs 2"], [base, fragment], "false", custom),
                ([f"KERNEL_CONFIGS={rust}", "RUSTC=rustc",
                  f"KERNEL_ARGS=--output {rust_output} --jobs 2"], [rust], "rustc", rust_output))
            for public, case in product((False, True), cases):
                overrides, configs, compiler, output = case
                goals = ["init", "initramfs", "kernel", *overrides]
                with self.subTest(goals=goals, public=public):
                    subprocess.run([
                        "make", "--no-print-directory", "-j8", "-C",
                        str(framework if public else root), "-f",
                        str((FRAMEWORK if public else ROOT) / "Makefile"),
                        f"SUITE={root}" if public else f"VV_ROOT={framework}",
                        f"MSHV_SOURCE={source}", *goals,
                    ], env=environment,
                        check=True, capture_output=True, text=True, timeout=20)
                    command = json.loads(record.read_text())
                    self.assertEqual(command["rustc"], compiler)
                    arguments = command["argv"]
                    default_config = not any(
                        arg.startswith("KERNEL_CONFIGS=") and arg.split("=", 1)[1].strip()
                        for arg in overrides)
                    expected_configs = ([root / "kernel/common.config",
                                         root / "kernel/x86_64.config"]
                                        if default_config else configs)
                    self.assertEqual([
                        arguments[index + 1] for index, argument in enumerate(arguments)
                        if argument == "--config"], [str(path) for path in expected_configs])
                    if default_config:
                        self.assertEqual(arguments[arguments.index("--base-config") + 1],
                                         str(config))
                    else:
                        self.assertNotIn("--base-config", arguments)
                    self.assertIn("--offline", arguments)
                    self.assertTrue((root / "target/initramfs.cpio.gz").is_file())
                    self.assertTrue(
                        (output / "images/bzImage-x86_64").is_file())
                    selected = json.loads((root / "target/kernel-result.json").read_text())
                    self.assertEqual(selected, {
                        "image": str(output / "images/bzImage-x86_64"),
                        "arch": "x86_64", "format": "bzImage"})
                    self.assertEqual(
                        (output / "x86_64/compiler-origin").read_text(),
                        "command line")
                    for target in ("vmlinux", "bzImage"):
                        self.assertEqual(
                            (output / f"x86_64/{target}-rustc").read_text(), compiler)
                    if configs == [base, fragment]:
                        text = (output / "images/config-x86_64").read_text()
                        self.assertIn("CONFIG_FIXTURE=y", text)
                        self.assertNotIn("CONFIG_FIXTURE=m", text)

    def test_kernel_source_must_be_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            framework = root / "framework"
            framework.mkdir()
            install_build_fixture(root, framework)
            environment = dict(os.environ)
            environment.pop("MSHV_SOURCE", None)
            environment.pop("KERNEL_CONFIGS", None)
            for overrides, expected in (
                    ([], "Set MSHV_SOURCE"),
                    (["MSHV_SOURCE=   "], "Set MSHV_SOURCE")):
                with self.subTest(overrides=overrides):
                    result = subprocess.run([
                        "make", "--no-print-directory", "-C", str(root),
                        "-f", str(ROOT / "Makefile"), f"VV_ROOT={framework}",
                        "kernel", *overrides,
                    ], env=environment, capture_output=True, text=True, timeout=20)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(expected, result.stderr)
            self.assertFalse((root / "target/kernel").exists())

    def test_help_exposes_build_configuration(self):
        result = subprocess.run([
            "make", "--no-print-directory", "-C", str(ROOT), "help",
        ], check=True, capture_output=True, text=True, timeout=20)
        for text in (
                "initramfs", "kernel", "MSHV_SOURCE", "VV_ROOT", "TARGET",
                "KERNEL_CONFIGS", "KERNEL_ARGS", "RUSTC", "--output", "--jobs",
                "Later files override earlier values",
                "Microsoft/configs/x86/mshv_defconfig", "replaces the default config"):
            self.assertIn(text, result.stdout)

    def test_clean_removes_the_whole_selected_output_tree(self):
        for target in ("target", "custom output"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "lib/suite.py"
                source.parent.mkdir()
                source.write_text("fixture source\n")
                subprocess.run(["git", "init", "-q", str(root)], check=True)
                subprocess.run(["git", "-C", str(root), "add", "lib"], check=True)
                output = root / target
                for name in (
                        "init", "initramfs.cpio.gz", "obj/test.o",
                        "stale.h", "results/results.json",
                        "kernel/images/kernel", "kernel-cache/source",
                        "nested-hyperv/runs/test/boot.img", "boot-components/esp/shim"):
                    path = output / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"generated")
                inputs = root / "boot-inputs"
                inputs.mkdir()
                (inputs / "shim").write_bytes(b"input")
                for _ in range(2):
                    result = subprocess.run([
                        "make", "--no-print-directory", "-C", str(root),
                        "-f", str(ROOT / "Makefile"), f"VV_ROOT={FRAMEWORK}",
                        f"TARGET={target}", "clean",
                    ], capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertFalse(output.exists())
                    self.assertTrue(source.is_file())
                    self.assertEqual((inputs / "shim").read_bytes(), b"input")

    def test_clean_rejects_source_and_checkout_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "lib/suite.py"
            source.parent.mkdir()
            source.write_text("fixture source\n")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "lib"], check=True)
            for target in ("lib", "."):
                with self.subTest(target=target):
                    result = subprocess.run([
                        "make", "--no-print-directory", "-C", str(root),
                        "-f", str(ROOT / "Makefile"), f"VV_ROOT={FRAMEWORK}",
                        f"TARGET={target}", "clean",
                    ], capture_output=True, text=True, timeout=20)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Refusing to clean", result.stderr)
                    self.assertTrue(source.is_file())

    def test_standard_targets_and_aliases_share_one_build(self):
        for goals in (["init"], ["initramfs"],
                      ["init", "initramfs", "mshv", "mshv-initramfs"], []):
            with self.subTest(goals=goals), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                framework = root / "framework"
                (root / "lib").mkdir()
                (framework / "lib/python/villain").mkdir(parents=True)
                events = root / "events"
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
                install_build_fixture(root, framework)
                subprocess.run([
                    "make", "--no-print-directory", "-j8", "-C", str(root),
                    "-f", str(ROOT / "Makefile"), f"VV_ROOT={framework}",
                    f"MSHV_SOURCE={root / 'nonexistent kernel source'}", *goals,
                ], check=True, capture_output=True, text=True, timeout=20)
                archive = root / "target/initramfs.cpio.gz"
                self.assertTrue((root / "target/init").is_file())
                self.assertFalse((root / "target/contract.h").exists())
                self.assertFalse((root / "target/mshv").exists())
                expected = ["link"]
                if goals != ["init"]:
                    expected.append("pack")
                    self.assertIn(b"init\0", gzip.decompress(archive.read_bytes()))
                else:
                    self.assertFalse(archive.exists())
                self.assertEqual(events.read_text().splitlines(), expected)
