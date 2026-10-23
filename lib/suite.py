# SPDX-License-Identifier: Apache-2.0
"""MSHV launch policy using Virtio Villain orchestration and reporting."""

import argparse
import os
from pathlib import Path
import re
from villain.appliance import Suite, source_catalog
from .boot_image import build_image
from .contract import COMMIT

ROOT = Path(__file__).resolve().parents[1]


class MshvSuite(Suite):
    def list_tests(self, binary):
        return source_catalog(ROOT.glob("tests/*/*.c"), "REGISTER_MSHV_TEST")

    def add_arguments(self, parser):
        parser.add_argument("--vmm", default=os.environ.get(
            "MSHV_VMM", str(ROOT.parent / "cloud-hypervisor/target/release/cloud-hypervisor")),
            help="Cloud Hypervisor MSHV executable")

    def preflight(self, args):
        fd = os.open("/dev/mshv", os.O_RDWR | os.O_CLOEXEC)
        os.close(fd)

    def build_command(self, args, selected, run_id):
        cmdline = ("console=ttyS0,115200 rdinit=/init panic=-1 loglevel=3 vv.shutdown=host "
                   f"vv.run={run_id} vv.tests={','.join(selected)}")
        return self.execution_command([
            "--vmm", args.vmm, "--kernel", str(args.kernel),
            "--initramfs", str(args.initramfs), "--cmdline", cmdline, "--run-id", run_id])

    def execute(self, argv):
        parser = argparse.ArgumentParser(description="Boot the MSHV appliance")
        parser.add_argument("--vmm", required=True)
        parser.add_argument("--kernel", required=True, type=Path)
        parser.add_argument("--initramfs", required=True, type=Path)
        parser.add_argument("--cmdline", required=True)
        parser.add_argument("--run-id", required=True)
        args = parser.parse_args(argv)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", args.run_id):
            parser.error("Invalid run identifier")
        output = ROOT / "target/nested-hyperv/runs" / args.run_id
        disk = build_image(output, args.kernel, args.initramfs, args.cmdline)
        command = [
            args.vmm, "--firmware", str(output / "firmware.fd"),
            "--disk", f"path={disk},image_type=raw,readonly=on",
            "--cpus", "boot=2,nested=on", "--memory", "size=2G",
            "--serial", "tty", "--console", "off"]
        print("Nested Hyper-V launch: " + " ".join(command), flush=True)
        os.execvp(args.vmm, command)


def create_suite():
    return MshvSuite(name="MSHV", contract=COMMIT, binary=ROOT / "target/mshv/init",
                     initramfs=ROOT / "target/mshv/initramfs.cpio.gz",
                     protocol_prefix="MSHV", host_shutdown=True)
