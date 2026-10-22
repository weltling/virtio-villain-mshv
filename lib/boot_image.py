#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Assemble a private UEFI disk from installed Hyper-V boot components."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ESP = Path(os.environ.get("MSHV_ESP", "/boot/efi"))
FIRMWARE = Path("/usr/share/cloud-hypervisor/CLOUDHV_EFI.fd")


def grub_config(cmdline):
    if any(char in cmdline for char in "\r\n\0"):
        raise ValueError("Kernel command line must be a single line")
    arguments = " ".join(shlex.quote(arg) for arg in shlex.split(cmdline))
    return (
        "terminal_input console\n"
        "terminal_output console\n"
        "set timeout=0\n"
        "set default=0\n"
        "menuentry 'MSHV nested Hyper-V appliance' {\n"
        "  echo VV-BOOT-GRUB\n"
        "  search --no-floppy --set=root --file /HvLoader.efi\n"
        "  if chainloader /HvLoader.efi lxhvloader.dll "
        r"MSHV_ROOT=\\Windows MSHV_ENABLE=TRUE MSHV_SCHEDULER_TYPE=ROOT "
        "MSHV_X2APIC_POLICY=ENABLE "
        "MSHV_LOAD_OPTION=INCLUDETRACEMETADATA=1 MSHV_FORCE_NESTED=TRUE; then\n"
        "    if boot; then\n"
        "      echo VV-BOOT-HYPERV-LOADER-SUCCESS\n"
        "    else\n"
        "      echo VV-BOOT-ERROR hyper-v-loader\n"
        "      halt\n"
        "    fi\n"
        "  else\n"
        "    echo VV-BOOT-ERROR chainloader\n"
        "    halt\n"
        "  fi\n"
        "  echo VV-BOOT-HYPERV-RETURNED\n"
        "  search --no-floppy --set=root --file /boot/vmlinuz\n"
        f"  linux /boot/vmlinuz {arguments}\n"
        "  initrd /boot/initramfs.cpio.gz\n"
        "  echo VV-BOOT-LINUX\n"
        "}\n"
    )


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build_image(output, kernel, initramfs, cmdline, esp=ESP, firmware=FIRMWARE):
    with kernel.open("rb") as stream:
        stream.seek(0x202)
        if stream.read(4) != b"HdrS":
            raise ValueError("GRUB requires the x86 bzImage kernel, not vmlinux ELF")
    if initramfs.stat().st_size == 0:
        raise ValueError("Test initramfs is empty")
    config = grub_config(cmdline)
    tools = ("sfdisk", "mkfs.vfat", "mmd", "mcopy", "mdir")
    for tool in tools:
        if not shutil.which(tool):
            raise RuntimeError(f"Missing image construction tool: {tool}")
    output.mkdir(parents=True, exist_ok=False)
    workspace = ROOT / "target/image-work"
    workspace.mkdir(parents=True, exist_ok=True)
    sources = {
        "EFI/BOOT/BOOTX64.EFI": esp / "EFI/BOOT/bootx64.efi",
        "EFI/BOOT/grubx64.efi": esp / "EFI/BOOT/grubx64.efi",
        "EFI/BOOT/mmx64.efi": esp / "EFI/BOOT/mmx64.efi",
        "HvLoader.efi": esp / "HvLoader.efi",
        "lxhvloader.dll": esp / "lxhvloader.dll",
        "Windows/System32/hvix64.exe": esp / "Windows/System32/hvix64.exe",
        "Windows/System32/hvax64.exe": esp / "Windows/System32/hvax64.exe",
        "Windows/System32/kdstub.dll": esp / "Windows/System32/kdstub.dll",
        "boot/vmlinuz": kernel,
        "boot/initramfs.cpio.gz": initramfs,
    }
    manifest = {"cmdline": cmdline, "files": {}, "firmware_source": str(firmware)}
    with tempfile.TemporaryDirectory(prefix="assemble-", dir=workspace) as temporary:
        scratch = Path(temporary)
        partition = scratch / "esp.fat"
        with partition.open("xb") as stream:
            stream.truncate(128 * 1024 * 1024)
        subprocess.run(["mkfs.vfat", "-F", "32", "-n", "MSHVBOOT", str(partition)], check=True)
        directories = ("EFI", "EFI/BOOT", "Windows", "Windows/System32", "boot", "boot/grub2")
        subprocess.run(["mmd", "-i", str(partition),
                        *(f"::/{name}" for name in directories)], check=True)
        for index, (name, source) in enumerate(sources.items()):
            staged = scratch / f"component-{index}"
            shutil.copyfile(source, staged)
            manifest["files"][name] = {"source": str(source), "sha256": sha256(staged)}
            subprocess.run(["mcopy", "-i", str(partition), str(staged), f"::/{name}"],
                           check=True)
        config_path = output / "grub.cfg"
        config_path.write_text(config)
        for name in ("boot/grub2/grub.cfg", "EFI/BOOT/grub.cfg", "grub.cfg"):
            subprocess.run(["mcopy", "-i", str(partition), str(config_path), f"::/{name}"],
                           check=True)
        disk = output / "boot.img"
        with disk.open("xb") as stream:
            stream.truncate(130 * 1024 * 1024)
        subprocess.run(["sfdisk", str(disk)], input=(
            "label: gpt\nunit: sectors\n"
            "start=2048,size=262144,type=U,name=\"MSHVBOOT\"\n"
        ), text=True, check=True)
        with disk.open("r+b") as destination, partition.open("rb") as source:
            destination.seek(1024 * 1024)
            shutil.copyfileobj(source, destination)
        subprocess.run(["mdir", "-i", f"{disk}@@1048576", "::/EFI/BOOT"], check=True)
    shutil.copyfile(firmware, output / "firmware.fd")
    manifest["firmware_sha256"] = sha256(output / "firmware.fd")
    manifest["disk_sha256"] = sha256(disk)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return disk


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="New output directory containing boot.img and firmware.fd")
    parser.add_argument("--kernel", type=Path, default=(
        ROOT / "target/kernel-microsoft/images/bzImage-x86_64"))
    parser.add_argument("--initramfs", type=Path, default=ROOT / "target/mshv/initramfs.cpio.gz")
    parser.add_argument("--cmdline", default=(
        "console=ttyS0,115200 rdinit=/init panic=-1 loglevel=7 "
        "no5lvl intel_iommu=off amd_iommu=off vv.run=image-probe vv.tests=ML001"))
    parser.add_argument("--esp", type=Path, default=ESP)
    parser.add_argument("--firmware", type=Path, default=FIRMWARE)
    args = parser.parse_args()
    try:
        disk = build_image(args.output.resolve(), args.kernel.resolve(),
                           args.initramfs.resolve(), args.cmdline,
                           args.esp.resolve(), args.firmware.resolve())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(2, f"Image construction failed: {error}\n")
    print(f"Guest boot disk: {disk}")
    print(f"Firmware: {disk.parent / 'firmware.fd'}")


if __name__ == "__main__":
    main()
