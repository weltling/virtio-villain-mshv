#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Private nested boot disk assembly checks."""

import contextlib
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = Path(os.environ.get("VV_ROOT", ROOT.parent / "virtio-villain")).resolve()
sys.path.insert(0, str(FRAMEWORK / "lib/python"))
from villain import appliance, images  # noqa: E402
from villain.appliance import load_suite  # noqa: E402
from villain.initramfs import archive as initramfs_archive  # noqa: E402

spec = importlib.util.spec_from_file_location("mshv_boot_image", ROOT / "lib/boot_image.py")
boot_image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot_image)

EXPECTED_BOOT_DISK_SIZE = 130 * 1024 * 1024
EXPECTED_ESP_SIZE = 128 * 1024 * 1024
EXPECTED_ESP_OFFSET = 1024 * 1024
EXPECTED_SECTOR_SIZE = 512
EXPECTED_ESP_START_SECTOR = 2048
EXPECTED_ESP_SECTOR_COUNT = 262144


def pe_image():
    data = bytearray(512)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 0x84, 0x8664, 1, 0, 0, 0, 240, 0x0002)
    struct.pack_into("<H", data, 0x98, 0x020B)
    struct.pack_into("<8sIIIIIIHHI", data, 0x188,
                     b".text", 64, 0x1000, 64, 448, 0, 0, 0, 0, 0x60000020)
    return bytes(data)


def firmware_volume():
    data = bytearray(512)
    struct.pack_into("<16s16sQIIHHHBB", data, 0, b"", b"fixture-fs-guid",
                     len(data), int.from_bytes(b"_FVH", "little"), 0, 72, 0, 0, 0, 2)
    struct.pack_into("<II", data, 56, 1, len(data))
    checksum = -sum(struct.unpack_from("<36H", data)) & 0xFFFF
    struct.pack_into("<H", data, 50, checksum)
    return bytes(data)


def elf_firmware(machine):
    volume = firmware_volume()
    data = bytearray(0x1000 + len(volume))
    struct.pack_into("<16sHHIQQQIHHHHHH", data, 0,
                     b"\x7fELF\x02\x01\x01", 2, machine, 1, 0x100000,
                     64, 0, 0, 64, 56, 1, 0, 0, 0)
    struct.pack_into("<IIQQQQQQ", data, 64, 1, 5, 0x1000, 0x100000,
                     0x100000, len(volume), len(volume), 0x1000)
    data[0x1000:] = volume
    return bytes(data)


def boot_inputs(root):
    esp = root / "esp"
    for name in boot_image.ESP_COMPONENTS.values():
        path = esp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pe_image())
    kernel = root / "bzImage"
    kernel.write_bytes(b"\0" * 0x1FE + b"\x55\xaa" + b"\0\0" + b"HdrS")
    elf = bytearray(64)
    elf[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<HH", elf, 54, 56, 0)
    archive = root / "initramfs.cpio.gz"
    archive.write_bytes(initramfs_archive(elf))
    firmware = root / "firmware.fd"
    firmware.write_bytes(firmware_volume())
    return dict(kernel=kernel, initramfs=archive, esp=esp, firmware=firmware)


class FirmwareTests(unittest.TestCase):
    def test_installed_firmware_prevents_network_and_cache_access(self):
        with tempfile.TemporaryDirectory() as work:
            installed = Path(work) / "installed.fd"
            installed.write_bytes(firmware_volume())
            with patch.object(boot_image, "FIRMWARE", installed), \
                 patch("villain.artifacts.github_release_asset") as fetch:
                for offline in (False, True):
                    self.assertEqual(boot_image.resolve_firmware(offline=offline), installed)
            fetch.assert_not_called()

    def test_explicit_override_does_not_fall_back_when_missing(self):
        missing = Path("/nonexistent/explicit/firmware.fd")
        with patch("villain.artifacts.github_release_asset") as fetch:
            self.assertEqual(boot_image.resolve_firmware(missing), missing)
        fetch.assert_not_called()

    def test_absent_installed_firmware_uses_shared_latest_asset_cache(self):
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            selected = root / "cached.fd"
            for offline in (False, True):
                with self.subTest(offline=offline), \
                     patch.object(boot_image, "FIRMWARE", root / "missing.fd"), \
                     patch.dict(boot_image.os.environ, {"XDG_CACHE_HOME": str(root)}), \
                     patch("villain.artifacts.github_release_asset",
                           return_value=selected) as fetch:
                    self.assertEqual(boot_image.resolve_firmware(offline=offline), selected)
                    fetch.assert_called_once_with(
                        "cloud-hypervisor/edk2", "CLOUDHV.fd",
                        root / "virtio-villain/firmware", offline=offline)

    def test_unreadable_installed_firmware_does_not_trigger_download(self):
        with patch.object(Path, "lstat", side_effect=PermissionError("Unreadable firmware")), \
             patch("villain.artifacts.github_release_asset") as fetch, \
             self.assertRaisesRegex(PermissionError, "Unreadable firmware"):
            boot_image.resolve_firmware()
        fetch.assert_not_called()

    def test_invalid_installed_firmware_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as work:
            inputs = boot_inputs(Path(work))
            inputs["firmware"].write_bytes(b"invalid firmware")
            with patch.object(boot_image, "FIRMWARE", inputs["firmware"]), \
                 patch("villain.artifacts.github_release_asset") as fetch, \
                 patch.object(boot_image.shutil, "which", return_value="/tool"), \
                 self.assertRaisesRegex(RuntimeError, "firmware"):
                inputs["firmware"] = boot_image.resolve_firmware()
                boot_image.validate_boot_inputs(**inputs)
            fetch.assert_not_called()
            self.assertEqual(inputs["firmware"].read_bytes(), b"invalid firmware")

    def test_standalone_builder_passes_override_and_offline_policy(self):
        with tempfile.TemporaryDirectory() as work:
            output = Path(work) / "output"
            firmware = Path(work) / "selected.fd"
            with patch.object(sys, "argv", [
                    "boot_image.py", "--output", str(output), "--offline",
                    "--kernel", "/kernel", "--initramfs", "/archive",
                    "--firmware", str(firmware)]), \
                 patch.object(boot_image, "resolve_firmware", return_value=firmware) as resolve, \
                 patch.object(boot_image, "build_image",
                              return_value=output / "boot.img") as build, \
                 contextlib.redirect_stdout(io.StringIO()):
                boot_image.main()
            resolve.assert_called_once_with(firmware, offline=True)
            self.assertEqual(build.call_args.args[-1], firmware)

    def test_standalone_builder_uses_recorded_kernel_and_matching_archive(self):
        with tempfile.TemporaryDirectory() as work:
            target = Path(work) / "custom-output"
            target.mkdir()
            kernel = Path(work) / "elsewhere/custom-kernel"
            (target / "kernel-result.json").write_text(json.dumps({
                "image": str(kernel), "arch": "x86_64", "format": "bzImage"}))
            output = Path(work) / "disk"
            firmware = Path(work) / "firmware"
            with patch.object(sys, "argv", [
                    "boot_image.py", "--output", str(output),
                    "--build-dir", str(target), "--firmware", str(firmware)]), \
                 patch.object(boot_image, "build_image",
                              return_value=output / "boot.img") as build, \
                 contextlib.redirect_stdout(io.StringIO()):
                boot_image.main()
            self.assertEqual(build.call_args.args[1], kernel)
            self.assertEqual(build.call_args.args[2], target / "mshv/initramfs.cpio.gz")


class BootImageTests(unittest.TestCase):
    def validate(self, inputs):
        with patch.object(boot_image.shutil, "which", return_value="/tool"):
            boot_image.validate_boot_inputs(**inputs)

    def test_preflight_checks_valid_inputs_without_modifying_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = boot_inputs(root)
            before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
            with patch.object(boot_image.subprocess, "run") as run:
                self.validate(inputs)
            run.assert_not_called()
            self.assertEqual(before, {
                path: path.read_bytes() for path in root.rglob("*") if path.is_file()})
            self.assertFalse((root / "image").exists())

    def test_preflight_checks_every_pe_component(self):
        with tempfile.TemporaryDirectory() as temporary:
            inputs = boot_inputs(Path(temporary))
            for name in boot_image.ESP_COMPONENTS.values():
                with self.subTest(name=name):
                    path = inputs["esp"] / name
                    path.write_bytes(b"not PE")
                    with self.assertRaisesRegex(RuntimeError, str(path)):
                        self.validate(inputs)
                    path.write_bytes(pe_image())

    def test_preflight_rejects_invalid_pe_headers_and_sections(self):
        cases = (
            (0, b"NZ", "MZ"),
            (60, struct.pack("<I", 0xFFFF), "Truncated PE signature"),
            (0x80, b"PX\0\0", "PE/COFF signature"),
            (0x84, struct.pack("<H", 0xAA64), "AMD64"),
            (0x86, struct.pack("<H", 0), "section table"),
            (0x94, struct.pack("<H", 2), "optional header size"),
            (0x96, struct.pack("<H", 0), "EXECUTABLE_IMAGE"),
            (0x98, struct.pack("<H", 0x10B), "PE32\\+"),
            (0x188 + 20, struct.pack("<I", 512), "Truncated PE section"))
        with tempfile.TemporaryDirectory() as temporary:
            inputs = boot_inputs(Path(temporary))
            path = inputs["esp"] / "Windows/System32/hvix64.exe"
            for offset, value, message in cases:
                with self.subTest(message=message):
                    data = bytearray(pe_image())
                    data[offset:offset + len(value)] = value
                    path.write_bytes(data)
                    with self.assertRaisesRegex(RuntimeError, message):
                        self.validate(inputs)

    def test_preflight_accepts_raw_and_x86_elf_firmware(self):
        with tempfile.TemporaryDirectory() as temporary:
            inputs = boot_inputs(Path(temporary))
            for data in (firmware_volume(), elf_firmware(3), elf_firmware(62)):
                with self.subTest(prefix=data[:6]):
                    inputs["firmware"].write_bytes(data)
                    self.validate(inputs)

    def test_preflight_rejects_corrupt_or_wrong_architecture_firmware(self):
        volume = bytearray(firmware_volume())
        volume[50] ^= 1
        truncated_elf = bytearray(elf_firmware(62))
        struct.pack_into("<Q", truncated_elf, 64 + 32, len(truncated_elf) + 1)
        with tempfile.TemporaryDirectory() as temporary:
            inputs = boot_inputs(Path(temporary))
            for data, message in (
                    (b"not firmware", "UEFI firmware volume"),
                    (volume, "header checksum"),
                    (elf_firmware(183), "ELF64 firmware for x86"),
                    (truncated_elf, "Invalid ELF load segment")):
                with self.subTest(message=message):
                    inputs["firmware"].write_bytes(data)
                    with self.assertRaisesRegex(RuntimeError, message):
                        self.validate(inputs)

    def test_preflight_rejects_invalid_kernel_and_compressed_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            inputs = boot_inputs(Path(temporary))
            originals = {name: inputs[name].read_bytes() for name in ("kernel", "initramfs")}
            bad_crc = bytearray(originals["initramfs"])
            bad_crc[-8] ^= 1
            for name, data in (
                    ("kernel", b"\x7fELF"), ("kernel", b"\0" * 0x202 + b"HdrS"),
                    ("initramfs", b"archive"), ("initramfs", gzip.compress(b"not newc")),
                    ("initramfs", originals["initramfs"][:-4]), ("initramfs", bad_crc)):
                with self.subTest(name=name, prefix=data[:8]):
                    inputs[name].write_bytes(data)
                    with self.assertRaisesRegex(RuntimeError, str(inputs[name])):
                        self.validate(inputs)
                    inputs[name].write_bytes(originals[name])

    def test_preflight_collects_missing_files_empty_files_and_missing_tools(self):
        with tempfile.TemporaryDirectory() as temporary:
            inputs = boot_inputs(Path(temporary))
            missing = inputs["esp"] / "HvLoader.efi"
            empty = inputs["esp"] / "lxhvloader.dll"
            missing.unlink()
            empty.write_bytes(b"")
            inputs["firmware"].unlink()
            inputs["firmware"].mkdir()
            with patch.object(boot_image.shutil, "which",
                              side_effect=lambda tool: None if tool == "mcopy" else "/tool"), \
                 self.assertRaises(RuntimeError) as caught:
                boot_image.validate_boot_inputs(**inputs)
            for text in (str(missing), str(empty), str(inputs["firmware"]), "regular file",
                         "Missing image construction tool: mcopy"):
                self.assertIn(text, str(caught.exception))

    def test_preflight_reports_component_permission_errors_without_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = boot_inputs(root)
            blocked = inputs["esp"] / "HvLoader.efi"
            open_file = Path.open

            def readable(path, *args, **kwargs):
                if path == blocked:
                    raise PermissionError("Component is unreadable")
                return open_file(path, *args, **kwargs)

            with patch.object(Path, "open", readable), \
                 patch.object(boot_image.shutil, "which", return_value="/tool"), \
                 patch.object(boot_image.subprocess, "run") as run, \
                 self.assertRaisesRegex(RuntimeError, "Component is unreadable"):
                boot_image.build_image(root / "image", cmdline="vv.run=token", **inputs)
            run.assert_not_called()
            self.assertFalse((root / "image").exists())

    def test_suite_prepares_the_boot_disk_and_executes_the_selected_vmm(self):
        suite = load_suite(ROOT)
        module = sys.modules[type(suite).__module__]
        output = Path("/diagnostics/artifacts/1-ML001/boot")
        arguments = [
            "--vmm", "/vmm", "--kernel", "/kernel", "--initramfs", "/archive",
            "--firmware", "/selected/firmware",
            "--cmdline", "vv.run=launcher-test", "--run-id", "launcher-test",
            "--output", str(output)]
        with patch.object(module, "build_image", return_value=output / "boot.img") as build, \
             patch.object(module.os, "execvp") as execute, \
             patch.object(module.CloudHypervisor, "build_cmd",
                          side_effect=AssertionError("Virtio fixtures must not be selected")), \
             patch.dict(os.environ, {"VV_CH_DEBUG": "1"}), \
             contextlib.redirect_stdout(io.StringIO()):
            suite.execute(arguments)
        build.assert_called_once_with(
            output, Path("/kernel"), Path("/archive"), "vv.run=launcher-test",
            firmware=Path("/selected/firmware"))
        command = execute.call_args.args[1]
        self.assertEqual(execute.call_args.args[0], "/vmm")
        self.assertEqual(command, [
            "/vmm", "--firmware", str(output / "firmware.fd"),
            "--cpus", "boot=2,nested=on", "--memory", "size=2G",
            "--serial", "tty", "--console", "off",
            "--disk", f"path={output / 'boot.img'},image_type=raw,readonly=on"])

    def test_suite_does_not_start_a_vm_after_builder_failure(self):
        suite = load_suite(ROOT)
        module = sys.modules[type(suite).__module__]
        arguments = [
            "--vmm", "/vmm", "--kernel", "/kernel", "--initramfs", "/archive",
            "--firmware", "/selected/firmware",
            "--cmdline", "vv.run=launcher-test", "--run-id", "launcher-test",
            "--output", "/diagnostics/artifacts/1-ML001/boot"]
        with patch.object(module, "build_image", side_effect=RuntimeError("Builder failed")), \
             patch.object(module.os, "execvp") as execute, \
             self.assertRaisesRegex(RuntimeError, "Builder failed"):
            suite.execute(arguments)
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
            with self.assertRaisesRegex(RuntimeError, "bzImage"):
                boot_image.build_image(output, kernel, root / "archive", "vv.run=token")
            self.assertFalse(output.exists())

    def test_component_permission_error_is_not_elevated(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = boot_inputs(root)
            with patch.object(boot_image, "ROOT", root), \
                 patch.object(boot_image.shutil, "which", return_value="/tool"), \
                 patch.object(boot_image.subprocess, "run") as run, \
                 patch.object(boot_image.shutil, "copyfile",
                              side_effect=PermissionError("Component is unreadable")), \
                 self.assertRaisesRegex(PermissionError, "Component is unreadable"):
                boot_image.build_image(root / "image", cmdline="vv.run=token", **inputs)
            self.assertTrue(all(call.args[0][0] != "sudo" for call in run.call_args_list))
            self.assertEqual(list((root / "image").iterdir()), [])
            self.assertFalse((root / "target").exists())

    @unittest.skipUnless(all(shutil.which(tool) for tool in (
        "sfdisk", "mkfs.vfat", "mmd", "mcopy", "mdir", "mtype")),
        "Disk image tools required")
    def test_image_contents_and_temporary_workspace_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = boot_inputs(root)
            output = root / "image"
            with patch.object(boot_image, "ROOT", root), \
                 patch.object(images, "create_raw", wraps=images.create_raw) as create_raw:
                disk = boot_image.build_image(
                    output, cmdline="vv.run=token vv.tests=ML001", **inputs)
            self.assertEqual(len(create_raw.call_args_list), 2)
            partition, whole_disk = create_raw.call_args_list
            self.assertEqual(partition.args[0].name, "esp.fat")
            self.assertEqual(partition.args[1], EXPECTED_ESP_SIZE)
            self.assertEqual(partition.kwargs, {"exclusive": True})
            self.assertEqual(whole_disk.args, (disk, EXPECTED_BOOT_DISK_SIZE))
            self.assertEqual(whole_disk.kwargs, {"exclusive": True})
            self.assertEqual(disk.stat().st_size, EXPECTED_BOOT_DISK_SIZE)
            table = json.loads(subprocess.check_output(["sfdisk", "--json", str(disk)]))[
                "partitiontable"]
            self.assertEqual(table["label"], "gpt")
            self.assertEqual(table["sectorsize"], EXPECTED_SECTOR_SIZE)
            self.assertEqual(len(table["partitions"]), 1)
            esp = table["partitions"][0]
            self.assertEqual(
                (esp["start"], esp["size"], esp["name"]),
                (EXPECTED_ESP_START_SECTOR, EXPECTED_ESP_SECTOR_COUNT, "MSHVBOOT"))
            self.assertEqual(esp["type"].upper(), "C12A7328-F81F-11D2-BA4B-00A0C93EC93B")
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["disk_sha256"], boot_image.sha256(disk))
            self.assertEqual((output / "firmware.fd").read_bytes(), inputs["firmware"].read_bytes())
            for name, metadata in manifest["files"].items():
                source = Path(metadata["source"])
                self.assertEqual(metadata["sha256"], boot_image.sha256(source))
                contents = subprocess.check_output([
                    "mtype", "-i", f"{disk}@@{EXPECTED_ESP_OFFSET}", f"::/{name}"])
                self.assertEqual(contents, source.read_bytes())
            for name in ("boot/grub2/grub.cfg", "EFI/BOOT/grub.cfg", "grub.cfg"):
                contents = subprocess.check_output([
                    "mtype", "-i", f"{disk}@@{EXPECTED_ESP_OFFSET}", f"::/{name}"])
                self.assertEqual(contents, (output / "grub.cfg").read_bytes())
            self.assertEqual({path.name for path in output.iterdir()},
                             {"boot.img", "firmware.fd", "grub.cfg", "manifest.json"})
            self.assertFalse((root / "target").exists())

    @unittest.skipUnless(all(shutil.which(tool) for tool in boot_image.IMAGE_TOOLS),
                         "Disk image tools required")
    def test_run_artifacts_follow_default_build_and_explicit_output_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = boot_inputs(root)
            source = root / "suite"
            private = source / "lib"
            private.mkdir(parents=True)
            for name in ("suite.py", "boot_image.py", "build.py", "sources.py"):
                shutil.copyfile(ROOT / "lib" / name, private / name)
            vmm = root / "fixture-vmm"
            vmm.write_text(
                f"#!{sys.executable}\n"
                "import json, signal, sys\n"
                "from pathlib import Path\n"
                "firmware = Path(sys.argv[sys.argv.index('--firmware') + 1])\n"
                "manifest = json.loads((firmware.parent / 'manifest.json').read_text())\n"
                "options = dict(word.split('=', 1) for word in manifest['cmdline'].split()\n"
                "               if '=' in word)\n"
                "token, name = options['vv.run'], options['vv.tests']\n"
                "print(f'MSHV-BEGIN {token} mshv-uapi-v1')\n"
                "print(f'MSHV-RUN {token} {name}')\n"
                "print(f'MSHV-RESULT {token} {name} PASS')\n"
                "print(f'MSHV-SUMMARY {token} 1 0 0 0')\n"
                "print(f'MSHV-END {token} 0')\n"
                "print(f'vv-appliance-stop {token}', flush=True)\n"
                "signal.pause()\n")
            vmm.chmod(0o755)
            for mode in ("default", "build-dir", "output"):
                with self.subTest(mode=mode), \
                     patch.dict(os.environ, {"MSHV_ESP": str(inputs["esp"]), "TARGET": "target"}):
                    suite = load_suite(source)
                    options = [] if mode == "default" else ["--build-dir", "selected-build"]
                    if mode == "output":
                        options.extend(["--output", str(root / "selected diagnostics")])
                    args = appliance.parse_args(suite, [
                        "--kernel", str(inputs["kernel"]),
                        "--initramfs", str(inputs["initramfs"]),
                        "--firmware", str(inputs["firmware"]),
                        "--vmm", str(vmm), *options])
                    with contextlib.redirect_stdout(io.StringIO()) as captured:
                        status = appliance.launch(suite, args, ["ML001"])
                    self.assertEqual(status, 0, captured.getvalue())
                    target = source / ("target" if mode == "default" else "selected-build")
                    directory = (root / "selected diagnostics" if mode == "output" else
                                 next((target / "mshv/results").iterdir()))
                    report = json.loads((directory / "results.json").read_text())
                    run = report["runs"][0]
                    workspace = directory / "artifacts/1-ML001"
                    self.assertEqual(Path(run["workspace"]), workspace)
                    self.assertEqual(Path(run["console"]).parent, directory)
                    self.assertTrue(run["host_shutdown"])
                    output = workspace / "boot"
                    self.assertEqual({path.name for path in output.iterdir()},
                                     {"boot.img", "firmware.fd", "grub.cfg", "manifest.json"})
                    manifest = json.loads((output / "manifest.json").read_text())
                    self.assertIn("vv.run=" + run["run_id"], manifest["cmdline"])
                    self.assertEqual(report["kernel_sha256"],
                                     boot_image.sha256(inputs["kernel"]))
                    self.assertEqual(report["initramfs_sha256"],
                                     boot_image.sha256(inputs["initramfs"]))
                    self.assertFalse((source / "target/nested-hyperv").exists())
                    self.assertFalse((source / "target/image-work").exists())
