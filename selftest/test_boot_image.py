#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Private nested boot disk assembly checks."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mshv_boot_image", ROOT / "lib/boot_image.py")
boot_image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot_image)


class BootImageTests(unittest.TestCase):
    def test_launcher_uses_the_private_builder_and_its_outputs(self):
        launch = runpy.run_path(str(ROOT / "launch-nested"))["main"]
        output = ROOT / "target/nested-hyperv/runs/launcher-test"
        arguments = [
            "launch-nested", "--kernel", "/kernel", "--initramfs", "/archive",
            "--cmdline", "vv.run=launcher-test", "--run-id", "launcher-test"]
        with patch.object(sys, "argv", arguments), \
             patch.dict(launch.__globals__["os"].environ, {"MSHV_VMM": "/vmm"}), \
             patch.object(subprocess, "run") as build, \
             patch.object(launch.__globals__["os"], "execv") as execute, \
             contextlib.redirect_stdout(io.StringIO()):
            launch()
        build.assert_called_once_with([
            sys.executable, str(ROOT / "lib/boot_image.py"),
            "--output", str(output), "--kernel", "/kernel",
            "--initramfs", "/archive", "--cmdline", "vv.run=launcher-test",
        ], check=True)
        command = execute.call_args.args[1]
        self.assertEqual(execute.call_args.args[0], "/vmm")
        self.assertEqual(command[command.index("--firmware") + 1],
                         str(output / "firmware.fd"))
        self.assertEqual(command[command.index("--disk") + 1],
                         f"path={output / 'boot.img'},image_type=raw,readonly=on")

    def test_launcher_does_not_start_a_vm_after_builder_failure(self):
        launch = runpy.run_path(str(ROOT / "launch-nested"))["main"]
        arguments = [
            "launch-nested", "--kernel", "/kernel", "--initramfs", "/archive",
            "--cmdline", "vv.run=launcher-test", "--run-id", "launcher-test"]
        errors = io.StringIO()
        with patch.object(sys, "argv", arguments), \
             patch.object(subprocess, "run",
                          side_effect=subprocess.CalledProcessError(1, ["builder"])), \
             patch.object(launch.__globals__["os"], "execv") as execute, \
             contextlib.redirect_stderr(errors), self.assertRaises(SystemExit) as exit:
            launch()
        self.assertEqual(exit.exception.code, 2)
        self.assertIn("Image construction failed", errors.getvalue())
        execute.assert_not_called()

    def test_grub_chain_and_command_line(self):
        config = boot_image.grub_config("vv.run=token vv.tests=ML001 rdinit=/init")
        self.assertIn("chainloader /HvLoader.efi lxhvloader.dll", config)
        self.assertIn(r"MSHV_ROOT=\\Windows", config)
        self.assertIn("MSHV_FORCE_NESTED=TRUE", config)
        self.assertIn("if boot; then", config)
        self.assertIn("VV-BOOT-ERROR hyper-v-loader", config)
        self.assertIn("linux /boot/vmlinuz vv.run=token vv.tests=ML001 rdinit=/init", config)
        self.assertIn("initrd /boot/initramfs.cpio.gz", config)

    def test_reject_multiline_command_line(self):
        for text in ("valid\nhalt", "valid\rhalt", "valid\0halt"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                boot_image.grub_config(text)

    def test_reject_elf_kernel_before_creating_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kernel = root / "vmlinux"
            kernel.write_bytes(b"\x7fELF")
            output = root / "image"
            with self.assertRaisesRegex(ValueError, "bzImage"):
                boot_image.build_image(output, kernel, root / "archive", "vv.run=token")
            self.assertFalse(output.exists())

    def test_component_permission_error_is_not_elevated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kernel, archive = root / "bzImage", root / "archive"
            kernel.write_bytes(b"\0" * 0x202 + b"HdrS")
            archive.write_bytes(b"archive")
            with patch.object(boot_image, "ROOT", root), \
                 patch.object(boot_image.shutil, "which", return_value="/tool"), \
                 patch.object(boot_image.subprocess, "run") as run, \
                 patch.object(boot_image.shutil, "copyfile",
                              side_effect=PermissionError("Component is unreadable")), \
                 self.assertRaisesRegex(PermissionError, "Component is unreadable"):
                boot_image.build_image(root / "image", kernel, archive, "vv.run=token")
            self.assertTrue(all(call.args[0][0] != "sudo" for call in run.call_args_list))

    @unittest.skipUnless(all(shutil.which(tool) for tool in (
        "sfdisk", "mkfs.vfat", "mmd", "mcopy", "mdir", "mtype")),
        "Disk image tools required")
    def test_image_contents_and_temporary_workspace_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            esp = root / "host-esp"
            names = ("EFI/BOOT/bootx64.efi", "EFI/BOOT/grubx64.efi",
                     "EFI/BOOT/mmx64.efi", "HvLoader.efi", "lxhvloader.dll",
                     "Windows/System32/hvix64.exe", "Windows/System32/hvax64.exe",
                     "Windows/System32/kdstub.dll")
            for name in names:
                source = esp / name
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(name.encode())
            kernel = root / "bzImage"
            kernel.write_bytes(b"\0" * 0x202 + b"HdrS")
            archive, firmware = root / "initramfs", root / "firmware"
            archive.write_bytes(b"test archive")
            firmware.write_bytes(b"test firmware")
            output = root / "image"
            with patch.object(boot_image, "ROOT", root):
                disk = boot_image.build_image(output, kernel, archive,
                                              "vv.run=token vv.tests=ML001",
                                              esp=esp, firmware=firmware)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["disk_sha256"], boot_image.sha256(disk))
            self.assertEqual((output / "firmware.fd").read_bytes(), b"test firmware")
            for name, metadata in manifest["files"].items():
                source = Path(metadata["source"])
                self.assertEqual(metadata["sha256"], boot_image.sha256(source))
                contents = subprocess.check_output([
                    "mtype", "-i", f"{disk}@@1048576", f"::/{name}"])
                self.assertEqual(contents, source.read_bytes())
            for name in ("boot/grub2/grub.cfg", "EFI/BOOT/grub.cfg", "grub.cfg"):
                contents = subprocess.check_output([
                    "mtype", "-i", f"{disk}@@1048576", f"::/{name}"])
                self.assertEqual(contents, (output / "grub.cfg").read_bytes())
            self.assertEqual(list((root / "target/image-work").iterdir()), [])
