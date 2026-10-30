#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Private launch policy checks using the shared appliance interface."""

import contextlib
import io
from itertools import product
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = (ROOT.parent / "virtio-villain").resolve()
sys.path.insert(0, str(FRAMEWORK / "lib/python"))
from villain import appliance  # noqa: E402
from test_build import install_build_fixture  # noqa: E402


class PolicyTests(unittest.TestCase):
    def test_missing_prepared_esp_fails_without_fetching(self):
        suite = appliance.load_suite(ROOT)
        module = sys.modules[type(suite).__module__]
        with tempfile.TemporaryDirectory() as work:
            args = appliance.parse_args(suite, ["--list", "--build-dir", work])
            with patch.object(module, "resolve_firmware") as resolve, \
                 patch.object(module, "validate_boot_inputs") as validate, \
                 patch.object(module, "executable") as executable, \
                 patch.object(os, "open") as opened, \
                 self.assertRaisesRegex(RuntimeError, "No prepared boot components.*make esp"):
                suite.preflight(args)
        resolve.assert_not_called()
        validate.assert_not_called()
        executable.assert_not_called()
        opened.assert_not_called()

    def test_prepared_esp_follows_the_selected_build_output(self):
        suite = appliance.load_suite(ROOT)
        module = sys.modules[type(suite).__module__]
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            for selected in (None, root / "custom"):
                with self.subTest(selected=selected), \
                     patch.dict(os.environ, {"TARGET": str(root / "default")}):
                    options = [] if selected is None else ["--build-dir", str(selected)]
                    args = appliance.parse_args(suite, ["--list", *options])
                    expected = (selected or root / "default") / "mshv-boot-inputs/esp"
                    expected.mkdir(parents=True)
                    with patch.object(module, "resolve_firmware",
                                      return_value=Path("/firmware")), \
                         patch.object(module, "validate_boot_inputs") as validate, \
                         patch.object(module, "executable"), \
                         patch.object(os, "open", return_value=42), \
                         patch.object(os, "close"), \
                         patch("urllib.request.urlopen") as network:
                        suite.preflight(args)
                    self.assertEqual(args.esp, expected)
                    validate.assert_called_once_with(
                        args.kernel, args.initramfs, expected, firmware=Path("/firmware"))
                    network.assert_not_called()
                    args.workspace = root / "diagnostics"
                    command = suite.build_command(args, ["ML0001"], "token")
                    self.assertEqual(command[command.index("--esp") + 1], str(expected))

    def test_worker_requires_explicit_esp(self):
        suite = appliance.load_suite(ROOT)
        module = sys.modules[type(suite).__module__]
        errors = io.StringIO()
        with patch.object(module, "build_image", return_value=Path("/disk")) as build, \
             patch.object(os, "execvp") as execute, \
             contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(errors), \
             self.assertRaises(SystemExit) as exit:
            suite.execute([
                "--vmm", "/vmm", "--kernel", "/kernel", "--initramfs", "/initramfs",
                "--firmware", "/firmware", "--cmdline", "vv.run=token",
                "--run-id", "token", "--output", "/output"])
        self.assertEqual(exit.exception.code, 2)
        self.assertIn("--esp", errors.getvalue())
        build.assert_not_called()
        execute.assert_not_called()

    def test_suite_identity_is_independent_of_kernel_source(self):
        with patch.dict(os.environ, {"MSHV_SOURCE": "/nonexistent/kernel/source"}):
            suite = appliance.load_suite(ROOT)
        self.assertEqual(suite.contract, "mshv-uapi-v1")
        self.assertIn(f'#define VV_MSHV_SUITE_ID "{suite.contract}"',
                      (ROOT / "lib/ioctls.h").read_text())
        self.assertIsNone(suite.build_spec.prepare)

    @unittest.skipUnless(shutil.which("make"), "Make required for source selection checks")
    def test_build_and_listing_select_the_same_tests(self):
        suite = appliance.load_suite(ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "lib").mkdir()
            framework = root / "framework"
            framework.mkdir()
            record = root / "sources"
            (framework / "Makefile").write_text(
                f"appliance:\n\t@printf '%s\\n' \"$(APPLIANCE_SRCS)\" > '{record}'\n")
            install_build_fixture(root, framework)
            (framework / "Makefile").write_text(
                f"appliance:\n\t@printf '%s\\n' \"$(APPLIANCE_SRCS)\" > '{record}'\n"
                '\t@mkdir -p "$(APPLIANCE_TARGET)"\n'
                '\t@printf "fixture" > "$(APPLIANCE_TARGET)/init"\n')
            paths = {
                "ML010": root / "tests/ml/first.c",
                "ML030": root / "tests/ml/added.c",
                "MR020": root / "tests/mr/second.c"}
            for name in ("ML010", "MR020"):
                path = paths[name]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f'REGISTER_MSHV_TEST({name}, test, "Fixture {name}");\n')
            ignored = root / "tests/ml/nested/ignored.c"
            ignored.parent.mkdir()
            ignored.write_text('REGISTER_MSHV_TEST(XX001, test, "Ignored");\n')
            (root / "tests/ignored.c").write_text(
                'REGISTER_MSHV_TEST(XX002, test, "Ignored");\n')
            for names in (
                    ("ML010", "MR020"), ("ML010", "ML030", "MR020"), ("ML030", "MR020")):
                with self.subTest(names=names):
                    if "ML030" in names:
                        paths["ML030"].write_text(
                            'REGISTER_MSHV_TEST(ML030, test, "Fixture ML030");\n')
                    if "ML010" not in names:
                        paths["ML010"].unlink()
                    subprocess.run([
                        "make", "--no-print-directory", "-C", str(root),
                        "-f", str(ROOT / "Makefile"), f"VV_ROOT={framework}", "init",
                    ], check=True, capture_output=True, text=True, timeout=20)
                    expected = [root / name for name in (
                        "bin/mshv.c", "lib/appliance.c", "lib/lifecycle.c", "lib/registers.c")]
                    expected.extend(sorted(paths[name] for name in names))
                    self.assertEqual(record.read_text().split(), list(map(str, expected)))
                    with patch.dict(suite.list_tests.__globals__, {"ROOT": root}):
                        self.assertEqual(suite.list_tests(None), {
                            name: f"Fixture {name}" for name in names})

    def test_execution_help_exposes_arguments_and_build_help(self):
        with contextlib.redirect_stdout(io.StringIO()) as output, \
             self.assertRaises(SystemExit) as exit:
            appliance.main(["--suite", str(ROOT), "--help"])
        self.assertEqual(exit.exception.code, 0)
        text = " ".join(output.getvalue().split())
        for expected in ("--vmm", "--esp", "CLOUDHV_EFI.fd", "make help",
                         "--kernel", "--firmware", "--offline", "SHA256",
                         "openvmm-firmware/MSVM.fd", "make openvmm-firmware"):
            self.assertIn(expected, text)
        self.assertNotIn("/boot/efi", text)

    def test_default_kernel_matches_the_suite_build_output(self):
        suite = appliance.load_suite(ROOT)
        self.assertIsNone(suite.kernel)
        self.assertIn(f"make -C {ROOT} kernel ", suite.kernel_build_hint)
        self.assertIn("MSHV_SOURCE=PATH", suite.kernel_build_hint)
        self.assertNotIn("KERNEL_CONFIGS=PATH", suite.kernel_build_hint)
        self.assertIsNone(appliance.parse_args(suite, ["--list"]).kernel)
        with tempfile.TemporaryDirectory() as work:
            kernel = Path(work) / "built-kernel"
            archive = Path(work) / "archive"
            kernel.write_bytes(b"kernel")
            archive.write_bytes(b"archive")
            target = Path(work) / "selected-output"
            target.mkdir()
            (target / "kernel-result.json").write_text(json.dumps({
                "image": str(kernel), "arch": "x86_64", "format": "bzImage"}))
            args = appliance.parse_args(suite, [
                "--build-dir", str(target), "--initramfs", str(archive),
                "--esp", "/components", "ML001"])
            self.assertEqual(args.kernel, kernel)
            args.workspace = target / "mshv/results/fixture/artifacts/1-ML001"
            command = suite.build_command(args, ["ML001"], "token")
            self.assertEqual(command[command.index("--kernel") + 1], str(kernel))
            self.assertEqual(command[command.index("--output") + 1],
                             str(args.workspace / "boot"))

    def test_source_listing_without_an_appliance_binary(self):
        output = io.StringIO()
        with patch.object(appliance.subprocess, "run",
                          side_effect=AssertionError("Listing must not execute a binary")), \
             contextlib.redirect_stdout(output):
            status = appliance.main([
                "--suite", str(ROOT),
                "--binary", "/nonexistent/mshv-init", "--list"])
        self.assertEqual(status, 0)
        entries = appliance.parse_catalog(output.getvalue())
        sources = sorted(ROOT.glob("tests/*/*.c"))
        self.assertTrue(sources)
        self.assertEqual(list(entries), [
            source.stem.split("_", 1)[0].upper() for source in sources])
        self.assertTrue(all(entries.values()))
        self.assertTrue(all(not description[0].islower() for description in entries.values()))

    def test_nested_execution_without_external_control(self):
        suite = appliance.load_suite(ROOT)
        module = sys.modules[type(suite).__module__]
        with tempfile.TemporaryDirectory() as work:
            image = Path(work) / "image"
            image.write_bytes(b"image")
            args = appliance.parse_args(suite, [
                "--kernel", str(image), "--initramfs", str(image),
                "--vmm", "/local/cloud-hypervisor", "--firmware", str(image),
                "--esp", "relative-components",
                "--jobs", "16", "ML001"])
            args.workspace = Path(work) / "diagnostics/artifacts/1-ML001"
        self.assertEqual(args.jobs, 16)
        self.assertFalse(suite.requires_control)
        self.assertIsNone(args.control)
        errors = io.StringIO()
        with patch.object(module, "validate_boot_inputs") as validate, \
             patch.object(module, "executable", return_value=args.vmm) as executable, \
             patch.object(os, "open", return_value=42) as opened, \
             patch.object(os, "close") as closed, \
             contextlib.redirect_stderr(errors):
            suite.preflight(args)
        validate.assert_called_once_with(
            args.kernel, args.initramfs, Path("relative-components").resolve(), firmware=image)
        executable.assert_called_once_with(args.vmm)
        opened.assert_called_once_with(
            "/dev/mshv", os.O_RDWR | os.O_CLOEXEC)
        closed.assert_called_once_with(42)
        self.assertEqual(errors.getvalue(), "")
        command = suite.build_command(args, ["ML001"], "token")
        self.assertEqual(command[:3], [
            sys.executable, str(Path(appliance.__file__).with_name("suite_exec.py")),
            str(ROOT / "lib/suite.py")])
        self.assertEqual(command[command.index("--vmm") + 1], "/local/cloud-hypervisor")
        self.assertEqual(command[command.index("--run-id") + 1], "token")
        self.assertEqual(command[command.index("--firmware") + 1], str(image))
        self.assertEqual(command[command.index("--esp") + 1],
                         str(Path("relative-components").resolve()))
        self.assertEqual(command[command.index("--output") + 1],
                         str(args.workspace / "boot"))
        self.assertIn("vv.tests=ML001", command[command.index("--cmdline") + 1])
        self.assertIn("vv.shutdown=host", command[command.index("--cmdline") + 1])
        self.assertTrue(suite.host_shutdown)

    def test_external_control_uses_the_same_nested_environment(self):
        suite = appliance.load_suite(ROOT)
        module = sys.modules[type(suite).__module__]
        with tempfile.TemporaryDirectory() as work:
            image = Path(work) / "image"
            image.write_bytes(b"image")
            args = appliance.parse_args(suite, [
                "--kernel", str(image), "--initramfs", str(image),
                "--control", "/external/control", "--firmware", str(image),
                "--esp", "/components"])
        errors = io.StringIO()
        with patch.object(module, "validate_boot_inputs") as validate, \
             patch.object(module, "executable", return_value=args.vmm) as executable, \
             patch.object(os, "open", return_value=42) as opened, \
             patch.object(os, "close") as closed, \
             contextlib.redirect_stderr(errors):
            suite.preflight(args)
        validate.assert_called_once_with(
            args.kernel, args.initramfs, Path("/components"), firmware=image)
        executable.assert_called_once_with(args.vmm)
        opened.assert_called_once_with("/dev/mshv", os.O_RDWR | os.O_CLOEXEC)
        closed.assert_called_once_with(42)
        self.assertEqual(args.control, "/external/control")
        self.assertEqual(errors.getvalue(), "")

    def test_dependency_preflight_stops_parallel_execution_before_device_access(self):
        suite = appliance.load_suite(ROOT)
        module = sys.modules[type(suite).__module__]
        errors = io.StringIO()
        with tempfile.TemporaryDirectory() as work:
            image = Path(work) / "image"
            image.write_bytes(b"image")
            with patch.object(appliance, "load_suite", return_value=suite), \
                 patch.object(appliance, "catalog", return_value={"ML001": "Fixture"}), \
                 patch.object(module, "validate_boot_inputs",
                              side_effect=RuntimeError("Bad HvLoader.efi signature")) as validate, \
                 patch.object(os, "open") as opened, \
                 patch.object(appliance, "launch") as launch, \
                 contextlib.redirect_stderr(errors):
                status = appliance.main([
                    "--suite", str(ROOT), "--kernel", str(image), "--initramfs", str(image),
                    "--jobs", "16", "--firmware", str(image), "--esp", "/components"])
            validate.assert_called_once_with(image, image, Path("/components"), firmware=image)
            opened.assert_not_called()
            launch.assert_not_called()
        self.assertEqual(status, 2)
        self.assertEqual(errors.getvalue().count("[INFRA]"), 1)
        self.assertIn("Bad HvLoader.efi signature", errors.getvalue())

    def test_missing_vmm_stops_before_device_access(self):
        suite = appliance.load_suite(ROOT)
        module = sys.modules[type(suite).__module__]
        with tempfile.TemporaryDirectory() as work:
            image = Path(work) / "image"
            image.write_bytes(b"image")
            args = appliance.parse_args(suite, [
                "--kernel", str(image), "--initramfs", str(image),
                "--vmm", str(Path(work) / "missing-vmm"), "--firmware", str(image),
                "--esp", "/components"])
            with patch.object(module, "validate_boot_inputs") as validate, \
                 patch.object(os, "open") as opened, \
                 self.assertRaisesRegex(RuntimeError, "Executable not found"):
                suite.preflight(args)
            validate.assert_called_once_with(image, image, Path("/components"), firmware=image)
            opened.assert_not_called()

    def test_default_nested_boot_needs_no_launcher_selection(self):
        suite = appliance.load_suite(ROOT)
        args = appliance.parse_args(suite, ["--list"])
        self.assertEqual(args.vmm, "cloud-hypervisor")
        self.assertFalse(hasattr(args, "launcher"))

    def test_explicit_vmm_selects_the_executable(self):
        suite = appliance.load_suite(ROOT)
        args = appliance.parse_args(suite, ["--list", "--vmm", "/selected/openvmm"])
        self.assertEqual(args.vmm, "/selected/openvmm")

    def test_openvmm_preflight_checks_kvm_without_cloud_firmware_resolution(self):
        suite = appliance.load_suite(ROOT)
        module = sys.modules[type(suite).__module__]
        for binary, backend in (("/local/openvmm", "auto"), ("/local/vmm", "openvmm")):
            with self.subTest(binary=binary):
                args = appliance.parse_args(suite, [
                    "--list", "--vmm", binary, "--backend", backend,
                    "--firmware", "/local/MSVM.fd", "--offline", "--esp", "/components"])
                with patch.object(module, "resolve_firmware") as resolve, \
                     patch.object(module, "validate_boot_inputs") as validate, \
                     patch.object(module, "executable") as executable, \
                     patch.object(os, "open", return_value=42) as opened, \
                     patch.object(os, "close") as closed:
                    suite.preflight(args)
                resolve.assert_not_called()
                validate.assert_called_once_with(
                    args.kernel, args.initramfs, Path("/components"),
                    firmware=Path("/local/MSVM.fd"))
                executable.assert_called_once_with(binary)
                opened.assert_called_once_with("/dev/kvm", os.O_RDWR | os.O_CLOEXEC)
                closed.assert_called_once_with(42)
                args.workspace = Path("/diagnostics")
                command = suite.build_command(args, ["ML0001"], "token")
                self.assertEqual(command[command.index("--backend") + 1], backend)
                self.assertEqual(command[command.index("--esp") + 1], "/components")
                self.assertEqual(command[command.index("--firmware") + 1], "/local/MSVM.fd")

    def test_openvmm_uses_prepared_firmware_from_the_selected_output(self):
        suite = appliance.load_suite(ROOT)
        module = sys.modules[type(suite).__module__]
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            default = root / "default"
            cases = product(
                (None, root / "custom"),
                (("/local/openvmm", "auto"), ("/local/vmm", "openvmm")),
                (None, root / "components"), (False, True))
            for selected, (binary, backend), esp, offline in cases:
                with self.subTest(selected=selected, backend=backend, esp=esp, offline=offline), \
                     patch.dict(os.environ, {"TARGET": str(default)}):
                    target = selected or default
                    firmware = target / "openvmm-firmware/MSVM.fd"
                    firmware.parent.mkdir(parents=True, exist_ok=True)
                    firmware.write_bytes(b"firmware")
                    components = esp or target / "mshv-boot-inputs/esp"
                    components.mkdir(parents=True, exist_ok=True)
                    options = ["--list", "--vmm", binary, "--backend", backend]
                    if selected is not None:
                        options.extend(["--build-dir", str(selected)])
                    if esp is not None:
                        options.extend(["--esp", str(esp)])
                    if offline:
                        options.append("--offline")
                    args = appliance.parse_args(suite, options)
                    with patch.object(module, "resolve_firmware") as resolve, \
                         patch.object(module, "validate_boot_inputs") as validate, \
                         patch.object(module, "executable"), \
                         patch.object(os, "open", return_value=42) as opened, \
                         patch.object(os, "close"), \
                         patch("urllib.request.urlopen") as network:
                        suite.preflight(args)
                    self.assertEqual(args.firmware, firmware)
                    validate.assert_called_once_with(
                        args.kernel, args.initramfs, components, firmware=firmware)
                    resolve.assert_not_called()
                    network.assert_not_called()
                    opened.assert_called_once_with("/dev/kvm", os.O_RDWR | os.O_CLOEXEC)
                    args.workspace = root / "diagnostics"
                    command = suite.build_command(args, ["ML0001"], "token")
                    self.assertEqual(command[command.index("--firmware") + 1], str(firmware))

    def test_missing_prepared_openvmm_firmware_fails_without_fetching(self):
        suite = appliance.load_suite(ROOT)
        module = sys.modules[type(suite).__module__]
        with tempfile.TemporaryDirectory() as work:
            firmware = Path(work) / "openvmm-firmware/MSVM.fd"
            args = appliance.parse_args(suite, [
                "--list", "--vmm", "/local/openvmm", "--build-dir", work,
                "--esp", "/components"])
            with patch.object(module, "resolve_firmware") as resolve, \
                 patch.object(module, "validate_boot_inputs") as validate, \
                 patch.object(module, "executable") as executable, \
                 patch.object(os, "open") as opened, \
                 patch("urllib.request.urlopen") as network, \
                 self.assertRaisesRegex(RuntimeError, "make openvmm-firmware") as error:
                suite.preflight(args)
            self.assertIn(str(firmware), str(error.exception))
        resolve.assert_not_called()
        validate.assert_not_called()
        executable.assert_not_called()
        opened.assert_not_called()
        network.assert_not_called()

    def test_openvmm_device_failure_is_not_ignored(self):
        suite = appliance.load_suite(ROOT)
        module = sys.modules[type(suite).__module__]
        args = appliance.parse_args(suite, [
            "--list", "--vmm", "openvmm", "--firmware", "/local/MSVM.fd",
            "--esp", "/components"])
        with patch.object(module, "validate_boot_inputs"), \
             patch.object(module, "executable"), \
             patch.object(os, "open", side_effect=PermissionError("KVM denied")), \
             self.assertRaisesRegex(PermissionError, "KVM denied"):
            suite.preflight(args)

    def test_explicit_cloud_backend_overrides_openvmm_filename(self):
        suite = appliance.load_suite(ROOT)
        module = sys.modules[type(suite).__module__]
        self.assertIsInstance(module.vmm_backend("/local/openvmm", "ch"),
                              module.CloudHypervisor)

    def test_openvmm_worker_launches_nested_uefi_on_kvm(self):
        suite = appliance.load_suite(ROOT)
        module = sys.modules[type(suite).__module__]
        output = Path("/diagnostics/boot")
        for binary, backend, status in (
                ("/local/openvmm", "auto", 0), ("/local/vmm", "openvmm", 1)):
            with self.subTest(binary=binary, status=status), \
                 patch.object(module, "build_image", return_value=Path("/disk")) as build, \
                 patch.object(module.process, "spawn") as spawn, \
                 patch.object(os, "execvp") as execute, \
                 contextlib.redirect_stdout(io.StringIO()):
                proc = Mock()
                proc.wait.return_value = status
                spawn.return_value.__enter__.return_value = (proc, None)
                with self.assertRaises(SystemExit) as exit:
                    suite.execute([
                        "--vmm", binary, "--backend", backend, "--kernel", "/kernel",
                        "--initramfs", "/initramfs", "--firmware", "/MSVM.fd",
                        "--esp", "/components",
                        "--cmdline", "vv.tests=ML0001", "--run-id", "fixture",
                        "--output", str(output)])
                self.assertEqual(exit.exception.code, status)
                proc.wait.assert_called_once_with()
                execute.assert_not_called()
                build.assert_called_once_with(
                    output, Path("/kernel"), Path("/initramfs"),
                    "vv.tests=ML0001", Path("/components"), firmware=Path("/MSVM.fd"))
                spawn.assert_called_once_with([
                    binary, "--hypervisor", "kvm", "-m", "2G", "-p", "2",
                    "--com1", "stderr", "--nested-virt",
                    "--pcie-root-complex", "rc0,segment=1",
                    "--uefi", f"firmware={output / 'firmware.fd'},console=com1",
                    "--disk", "file:/disk,ro",
                    "--guest-shutdown-action", "exit", "--guest-reset-action", "exit",
                    "--guest-crash-action", "exit:1"],
                    stdin=subprocess.PIPE, start_new_session=False)

    def test_firmware_is_resolved_once_and_passed_to_workers(self):
        suite = appliance.load_suite(ROOT)
        module = sys.modules[type(suite).__module__]
        firmware = Path("/cache/verified/firmware.fd")
        args = appliance.parse_args(suite, [
            "--list", "--offline", "--esp", "/components"])
        with patch.object(module, "resolve_firmware", return_value=firmware) as resolve, \
             patch.object(module, "validate_boot_inputs") as validate, \
             patch.object(module, "executable"), patch.object(os, "open", return_value=42), \
             patch.object(os, "close"):
            suite.preflight(args)
            for token in ("first", "second"):
                args.workspace = Path("/diagnostics") / token
                command = suite.build_command(args, ["ML001"], token)
                self.assertEqual(command[command.index("--firmware") + 1], str(firmware))
        resolve.assert_called_once_with(None, offline=True)
        validate.assert_called_once_with(
            args.kernel, args.initramfs, Path("/components"), firmware=firmware)

    def test_worker_builds_with_selected_firmware_without_resolving_again(self):
        suite = appliance.load_suite(ROOT)
        module = sys.modules[type(suite).__module__]
        output = Path("/diagnostics/artifacts/1-ML001/boot")
        with patch.object(module, "resolve_firmware",
                          side_effect=AssertionError("Worker must not resolve firmware")), \
             patch.object(module, "build_image", return_value=Path("/disk")) as build, \
             patch.object(os, "execvp") as execute, contextlib.redirect_stdout(io.StringIO()):
            suite.execute([
                "--vmm", "/vmm", "--kernel", "/kernel", "--initramfs", "/initramfs",
                "--firmware", "/selected/firmware", "--esp", "/components",
                "--cmdline", "vv.tests=ML001",
                "--run-id", "fixture", "--output", str(output)])
        build.assert_called_once_with(
            output, Path("/kernel"), Path("/initramfs"),
            "vv.tests=ML001", Path("/components"), firmware=Path("/selected/firmware"))
        execute.assert_called_once()
        self.assertEqual(execute.call_args.args[1][2], str(output / "firmware.fd"))

    def test_firmware_resolution_failure_is_one_infrastructure_error(self):
        suite = appliance.load_suite(ROOT)
        module = sys.modules[type(suite).__module__]
        errors = io.StringIO()
        with tempfile.TemporaryDirectory() as work:
            image = Path(work) / "image"
            image.write_bytes(b"image")
            with patch.object(appliance, "load_suite", return_value=suite), \
                 patch.object(appliance, "catalog", return_value={"ML001": "Fixture"}), \
                 patch.object(module, "resolve_firmware",
                              side_effect=RuntimeError("No published SHA256")), \
                 patch.object(module, "validate_boot_inputs") as validate, \
                 patch.object(os, "open") as opened, \
                 patch.object(appliance, "launch") as launch, \
                 contextlib.redirect_stderr(errors):
                status = appliance.main([
                    "--suite", str(ROOT), "--kernel", str(image), "--initramfs", str(image),
                    "--jobs", "16", "--esp", "/components"])
            validate.assert_not_called()
            opened.assert_not_called()
            launch.assert_not_called()
        self.assertEqual(status, 2)
        self.assertEqual(errors.getvalue().count("[INFRA]"), 1)
        self.assertIn("No published SHA256", errors.getvalue())

    def test_listing_does_not_resolve_or_download_firmware(self):
        suite = appliance.load_suite(ROOT)
        module = sys.modules[type(suite).__module__]
        with patch.object(appliance, "load_suite", return_value=suite), \
             patch.object(module, "resolve_firmware") as resolve, \
             contextlib.redirect_stdout(io.StringIO()):
            status = appliance.main(["--suite", str(ROOT), "--list", "--offline"])
        self.assertEqual(status, 0)
        resolve.assert_not_called()
