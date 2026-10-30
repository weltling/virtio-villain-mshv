#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Assemble a UEFI disk from extracted Hyper-V boot components."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = Path("/usr/share/cloud-hypervisor/CLOUDHV_EFI.fd")
FIRMWARE_REPOSITORY = "cloud-hypervisor/edk2"
FIRMWARE_ASSET = "CLOUDHV.fd"
IMAGE_TOOLS = ("sfdisk", "mkfs.vfat", "mmd", "mcopy", "mdir")
BOOT_DISK_SIZE = 130 * 1024 * 1024
ESP_SIZE = 128 * 1024 * 1024
ESP_OFFSET = 1024 * 1024
SECTOR_SIZE = 512
ESP_START_SECTOR = ESP_OFFSET // SECTOR_SIZE
ESP_SECTOR_COUNT = ESP_SIZE // SECTOR_SIZE
ESP_COMPONENTS = {
    "EFI/BOOT/BOOTX64.EFI": "EFI/BOOT/bootx64.efi",
    "EFI/BOOT/grubx64.efi": "EFI/BOOT/grubx64.efi",
    "EFI/BOOT/mmx64.efi": "EFI/BOOT/mmx64.efi",
    "HvLoader.efi": "HvLoader.efi",
    "lxhvloader.dll": "lxhvloader.dll",
    "Windows/System32/hvix64.exe": "Windows/System32/hvix64.exe",
    "Windows/System32/hvax64.exe": "Windows/System32/hvax64.exe",
    "Windows/System32/kdstub.dll": "Windows/System32/kdstub.dll",
}

PE_DOS_HEADER_SIZE = 64
PE_DOS_LFANEW_OFFSET = 60
PE_SIGNATURE = b"PE\0\0"
PE_COFF_HEADER = struct.Struct("<HHIIIHH")
PE_MACHINE_AMD64 = 0x8664
PE_CHARACTERISTIC_EXECUTABLE_IMAGE = 0x0002
PE32_PLUS_MAGIC = 0x020B
PE32_PLUS_MIN_HEADER_SIZE = 112
PE_SECTION_HEADER = struct.Struct("<8sIIIIIIHHI")

ELF64_LE_IDENT = b"\x7fELF\x02\x01"
ELF64_HEADER = struct.Struct("<16sHHIQQQIHHHHHH")
ELF64_PROGRAM_HEADER = struct.Struct("<IIQQQQQQ")
ELF_MACHINE_I386 = 3
ELF_MACHINE_X86_64 = 62
ELF_ET_EXEC = 2
ELF_ET_DYN = 3
ELF_PT_LOAD = 1

UEFI_FV_SIGNATURE = b"_FVH"
UEFI_FV_SIGNATURE_OFFSET = 40
UEFI_FV_HEADER = struct.Struct("<16s16sQIIHHHBB")
UEFI_FV_REVISION = 2
LINUX_BOOT_FLAG_OFFSET = 0x1FE
LINUX_BOOT_FLAG = b"\x55\xaa"
LINUX_SETUP_SIGNATURE_OFFSET = 0x202
LINUX_SETUP_SIGNATURE = b"HdrS"
NEWC_HEADER_SIZE = 110
VALIDATION_CHUNK_SIZE = 64 * 1024


def _read_at(stream, offset, size, description):
    stream.seek(offset)
    data = stream.read(size)
    if len(data) != size:
        raise ValueError(f"Truncated {description}: expected {size} bytes, got {len(data)}")
    return data


def _validate_pe(stream, size):
    dos = _read_at(stream, 0, PE_DOS_HEADER_SIZE, "PE DOS header")
    if dos[:2] != b"MZ":
        raise ValueError(f"Expected MZ DOS signature, got {dos[:2]!r}")
    pe_offset = struct.unpack_from("<I", dos, PE_DOS_LFANEW_OFFSET)[0]
    if pe_offset < PE_DOS_HEADER_SIZE:
        raise ValueError(f"Invalid PE header offset {pe_offset}")
    signature = _read_at(stream, pe_offset, len(PE_SIGNATURE), "PE signature")
    if signature != PE_SIGNATURE:
        raise ValueError(f"Expected PE/COFF signature {PE_SIGNATURE!r}, got {signature!r}")
    coff = _read_at(stream, pe_offset + len(PE_SIGNATURE), PE_COFF_HEADER.size, "COFF header")
    machine, sections, _, _, _, optional_size, characteristics = PE_COFF_HEADER.unpack(coff)
    if machine != PE_MACHINE_AMD64:
        raise ValueError(f"Expected AMD64 PE machine 0x{PE_MACHINE_AMD64:x}, got 0x{machine:x}")
    if not characteristics & PE_CHARACTERISTIC_EXECUTABLE_IMAGE:
        raise ValueError("PE/COFF image lacks IMAGE_FILE_EXECUTABLE_IMAGE")
    if optional_size < PE32_PLUS_MIN_HEADER_SIZE:
        raise ValueError(f"Truncated PE32+ optional header size {optional_size}")
    optional_offset = pe_offset + len(PE_SIGNATURE) + PE_COFF_HEADER.size
    optional = _read_at(stream, optional_offset, optional_size, "PE32+ optional header")
    magic = struct.unpack_from("<H", optional)[0]
    if magic != PE32_PLUS_MAGIC:
        raise ValueError(f"Expected PE32+ magic 0x{PE32_PLUS_MAGIC:x}, got 0x{magic:x}")
    section_offset = optional_offset + optional_size
    if not sections or section_offset + sections * PE_SECTION_HEADER.size > size:
        raise ValueError("Missing or truncated PE section table")
    for index in range(sections):
        section = PE_SECTION_HEADER.unpack(_read_at(
            stream, section_offset + index * PE_SECTION_HEADER.size,
            PE_SECTION_HEADER.size, "PE section header"))
        raw_size, raw_offset = section[3:5]
        if raw_size and raw_offset + raw_size > size:
            raise ValueError(f"Truncated PE section {index}: data extends beyond the file")


def _validate_firmware(stream, size):
    if _read_at(stream, 0, min(4, size), "firmware signature") == b"\x7fELF":
        header = ELF64_HEADER.unpack(_read_at(stream, 0, ELF64_HEADER.size, "ELF64 header"))
        ident, file_type, machine, _, _, phoff, _, _, ehsize, phsize, phcount, _, _, _ = header
        # The installed ELF64 firmware uses an EM_386 entry before entering long mode.
        if (not ident.startswith(ELF64_LE_IDENT)
                or machine not in (ELF_MACHINE_I386, ELF_MACHINE_X86_64)):
            raise ValueError("Expected little endian ELF64 firmware for x86")
        if file_type not in (ELF_ET_EXEC, ELF_ET_DYN) or ehsize != ELF64_HEADER.size:
            raise ValueError("Invalid executable ELF firmware header")
        if (not phcount or phsize != ELF64_PROGRAM_HEADER.size
                or phoff + phsize * phcount > size):
            raise ValueError("Missing or truncated ELF firmware program headers")
        loadable = False
        for index in range(phcount):
            segment = ELF64_PROGRAM_HEADER.unpack(_read_at(
                stream, phoff + index * phsize, phsize, "ELF program header"))
            kind, _, offset, _, _, file_size, memory_size, _ = segment
            if kind == ELF_PT_LOAD:
                if file_size > memory_size or offset + file_size > size:
                    raise ValueError(f"Invalid ELF load segment {index}")
                loadable |= file_size > 0
        if not loadable:
            raise ValueError("ELF firmware has no loadable data")
    for offset in range(0, size, VALIDATION_CHUNK_SIZE):
        block = _read_at(stream, offset, min(
            VALIDATION_CHUNK_SIZE + len(UEFI_FV_SIGNATURE) - 1, size - offset), "firmware data")
        start = 0
        while (position := block.find(UEFI_FV_SIGNATURE, start)) >= 0:
            start = position + len(UEFI_FV_SIGNATURE)
            base = offset + position - UEFI_FV_SIGNATURE_OFFSET
            if base < 0 or base + UEFI_FV_HEADER.size > size:
                continue
            header = UEFI_FV_HEADER.unpack(_read_at(
                stream, base, UEFI_FV_HEADER.size, "UEFI firmware volume header"))
            _, _, length, _, _, header_length, _, _, _, revision = header
            if (revision != UEFI_FV_REVISION or header_length < UEFI_FV_HEADER.size
                    or header_length % 2 or header_length > length or base + length > size):
                continue
            data = _read_at(stream, base, header_length, "UEFI firmware volume checksum")
            if sum(struct.unpack(f"<{header_length // 2}H", data)) & 0xFFFF == 0:
                return
    raise ValueError("No UEFI firmware volume with a valid signature, length and header checksum")


def _validate_kernel(stream, size):
    boot_flag = _read_at(stream, LINUX_BOOT_FLAG_OFFSET, len(LINUX_BOOT_FLAG), "bzImage boot flag")
    setup = _read_at(stream, LINUX_SETUP_SIGNATURE_OFFSET,
                     len(LINUX_SETUP_SIGNATURE), "bzImage setup signature")
    if boot_flag != LINUX_BOOT_FLAG or setup != LINUX_SETUP_SIGNATURE:
        raise ValueError("Expected x86 bzImage boot flag and HdrS signature, not vmlinux ELF")


def _validate_initramfs(stream, size):
    with gzip.GzipFile(fileobj=stream) as archive:
        header = archive.read(NEWC_HEADER_SIZE)
        if (len(header) != NEWC_HEADER_SIZE or header[:6] not in (b"070701", b"070702")
                or any(byte not in b"0123456789abcdefABCDEF" for byte in header[6:])):
            raise ValueError("Expected a gzip compressed newc initramfs header")
        # Reading to EOF makes gzip verify the trailer and CRC.
        while archive.read(VALIDATION_CHUNK_SIZE):
            pass


def validate_boot_inputs(kernel, initramfs, esp, firmware=FIRMWARE):
    checks = [
        ("bzImage kernel", kernel, _validate_kernel),
        ("gzip/newc initramfs", initramfs, _validate_initramfs),
        ("UEFI firmware", firmware, _validate_firmware),
        *(("x86-64 PE/COFF boot component", esp / name, _validate_pe)
          for name in ESP_COMPONENTS.values()),
    ]
    errors = []
    for kind, path, validate in checks:
        try:
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or not info.st_size:
                raise ValueError("Expected a nonempty regular file")
            with path.open("rb") as stream:
                validate(stream, info.st_size)
        except (OSError, ValueError, EOFError, struct.error, zlib.error) as error:
            errors.append(f"{kind} {path}: {error}")
    for tool in IMAGE_TOOLS:
        if not shutil.which(tool):
            errors.append(f"Missing image construction tool: {tool}")
    if errors:
        raise RuntimeError("Boot input preflight failed:\n  " + "\n  ".join(errors))


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


def resolve_firmware(firmware=None, *, offline=False):
    if firmware is not None:
        return firmware.resolve()
    try:
        FIRMWARE.lstat()
    except FileNotFoundError:
        from villain.artifacts import github_release_asset

        cache = ROOT / "target"
        return github_release_asset(
            FIRMWARE_REPOSITORY, FIRMWARE_ASSET,
            cache / "virtio-villain/firmware", offline=offline).resolve()
    return FIRMWARE


def build_image(output, kernel, initramfs, cmdline, esp, firmware=FIRMWARE):
    validate_boot_inputs(kernel, initramfs, esp, firmware)
    config = grub_config(cmdline)
    from villain.images import create_raw

    output.mkdir(parents=True, exist_ok=False)
    sources = {
        **{name: esp / source for name, source in ESP_COMPONENTS.items()},
        "boot/vmlinuz": kernel,
        "boot/initramfs.cpio.gz": initramfs,
    }
    manifest = {"cmdline": cmdline, "files": {}, "firmware_source": str(firmware)}
    with tempfile.TemporaryDirectory(prefix="assemble-", dir=output) as temporary:
        scratch = Path(temporary)
        partition = scratch / "esp.fat"
        create_raw(partition, ESP_SIZE, exclusive=True)
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
        create_raw(disk, BOOT_DISK_SIZE, exclusive=True)
        subprocess.run(["sfdisk", str(disk)], input=(
            "label: gpt\nunit: sectors\n"
            f"start={ESP_START_SECTOR},size={ESP_SECTOR_COUNT},type=U,name=\"MSHVBOOT\"\n"
        ), text=True, check=True)
        with disk.open("r+b") as destination, partition.open("rb") as source:
            destination.seek(ESP_OFFSET)
            shutil.copyfileobj(source, destination)
        subprocess.run(["mdir", "-i", f"{disk}@@{ESP_OFFSET}", "::/EFI/BOOT"], check=True)
    shutil.copyfile(firmware, output / "firmware.fd")
    manifest["firmware_sha256"] = sha256(output / "firmware.fd")
    manifest["disk_sha256"] = sha256(disk)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return disk


def main():
    framework = ROOT.parent / "virtio-villain"
    sys.path.insert(0, str(framework / "lib/python"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="New output directory containing boot.img and firmware.fd")
    parser.add_argument("--kernel", type=Path, help="Override the recorded kernel image")
    parser.add_argument("--initramfs", type=Path, help="Override the suite initramfs")
    parser.add_argument("--build-dir", type=Path,
                        help="Suite output root containing the selected build artifacts")
    parser.add_argument("--cmdline", default=(
        "console=ttyS0,115200 rdinit=/init panic=-1 loglevel=7 "
        "no5lvl intel_iommu=off amd_iommu=off vv.run=image-probe vv.tests=ML001"))
    parser.add_argument("--esp", type=Path, required=True,
                        help="Directory containing extracted boot components")
    parser.add_argument("--firmware", type=Path,
                        help=f"Local firmware override (otherwise prefer {FIRMWARE})")
    parser.add_argument("--offline", action="store_true",
                        help="Use installed or cached firmware without network access")
    args = parser.parse_args()
    try:
        if args.kernel is None or args.initramfs is None:
            from villain.appliance import load_suite

            suite = load_suite(ROOT)
            context = suite.configure_build(args.build_dir)
            if args.kernel is None:
                args.kernel = context.kernel_image
                if args.kernel is None:
                    raise RuntimeError(
                        "No recorded kernel build result. Run make kernel "
                        "or select an existing image with --kernel PATH.")
            if args.initramfs is None:
                args.initramfs = context.initramfs
        firmware = resolve_firmware(args.firmware, offline=args.offline)
        disk = build_image(args.output.resolve(), args.kernel.resolve(),
                           args.initramfs.resolve(), args.cmdline,
                           args.esp.resolve(), firmware)
    except (OSError, RuntimeError, ValueError, ImportError, subprocess.SubprocessError) as error:
        parser.exit(2, f"Image construction failed: {error}\n")
    print(f"Guest boot disk: {disk}")
    print(f"Firmware: {disk.parent / 'firmware.fd'}")


if __name__ == "__main__":
    main()
