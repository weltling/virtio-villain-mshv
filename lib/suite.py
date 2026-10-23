# SPDX-License-Identifier: Apache-2.0
"""MSHV launch policy using Virtio Villain orchestration and reporting."""

import argparse
import os
from pathlib import Path
import re
from villain.appliance import Suite, executable, source_catalog
from .boot_image import FIRMWARE, build_image, resolve_firmware, validate_boot_inputs
from .build import create_build
from .sources import test_sources

ROOT = Path(__file__).resolve().parents[1]


class MshvSuite(Suite):
    def list_tests(self, binary):
        return source_catalog(test_sources(ROOT), "REGISTER_MSHV_TEST")

    def add_arguments(self, parser):
        parser.epilog = (
            "MSHV_VMM selects the default Cloud Hypervisor executable. "
            "MSHV_ESP selects readable boot components (default /boot/efi). "
            f"Prefer installed UEFI firmware at {FIRMWARE}, otherwise download "
            "the latest cloud-hypervisor/edk2 CLOUDHV.fd with SHA256 verification. "
            "Boot files are checked before launching tests. "
            "Use make help in the suite directory for kernel config and build options.")
        parser.add_argument("--vmm", default=os.environ.get("MSHV_VMM", "cloud-hypervisor"),
                            help="Cloud Hypervisor MSHV executable (default: PATH lookup)")
        parser.add_argument("--firmware", type=Path, help="Explicit local UEFI firmware")
        parser.add_argument("--offline", action="store_true",
                            help="Use installed or cached firmware without network access")

    def preflight(self, args):
        args.firmware = resolve_firmware(args.firmware, offline=args.offline)
        validate_boot_inputs(args.kernel, args.initramfs, firmware=args.firmware)
        executable(args.vmm)
        fd = os.open("/dev/mshv", os.O_RDWR | os.O_CLOEXEC)
        os.close(fd)

    def build_command(self, args, selected, run_id):
        cmdline = ("console=ttyS0,115200 rdinit=/init panic=-1 loglevel=3 vv.shutdown=host "
                   f"vv.run={run_id} vv.tests={','.join(selected)}")
        return self.execution_command([
            "--vmm", args.vmm, "--kernel", str(args.kernel),
            "--initramfs", str(args.initramfs), "--firmware", str(args.firmware),
            "--cmdline", cmdline, "--run-id", run_id])

    def execute(self, argv):
        parser = argparse.ArgumentParser(description="Boot the MSHV appliance")
        parser.add_argument("--vmm", required=True)
        parser.add_argument("--kernel", required=True, type=Path)
        parser.add_argument("--initramfs", required=True, type=Path)
        parser.add_argument("--firmware", required=True, type=Path)
        parser.add_argument("--cmdline", required=True)
        parser.add_argument("--run-id", required=True)
        args = parser.parse_args(argv)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", args.run_id):
            parser.error("Invalid run identifier")
        output = ROOT / "target/nested-hyperv/runs" / args.run_id
        disk = build_image(output, args.kernel, args.initramfs, args.cmdline,
                           firmware=args.firmware)
        command = [
            args.vmm, "--firmware", str(output / "firmware.fd"),
            "--disk", f"path={disk},image_type=raw,readonly=on",
            "--cpus", "boot=2,nested=on", "--memory", "size=2G",
            "--serial", "tty", "--console", "off"]
        print("Nested Hyper-V launch: " + " ".join(command), flush=True)
        os.execvp(args.vmm, command)


def create_suite():
    build = create_build(ROOT)
    context = build.context()
    return MshvSuite(name="MSHV", contract="mshv-uapi-v1", binary=context.binary,
                     initramfs=context.initramfs, build_spec=build,
                     protocol_prefix="MSHV", host_shutdown=True,
                     kernel_build_hint=(
                         f"Build it with make -C {ROOT} kernel "
                         "MSHV_SOURCE=PATH KERNEL_CONFIGS=PATH, "
                         "or select another image with --kernel PATH."))
