# SPDX-License-Identifier: Apache-2.0
"""MSHV-specific policy; orchestration and reporting belong to Virtio Villain."""

import os
from pathlib import Path
from lib.appliance import Suite
from mshv.contract import COMMIT

ROOT = Path(__file__).resolve().parent


class MshvSuite(Suite):
    def add_arguments(self, parser):
        backend = parser.add_mutually_exclusive_group()
        backend.add_argument("--vmm", default="cloud-hypervisor",
                             help="Cloud Hypervisor MSHV executable")
        backend.add_argument("--launcher", help="Privileged Hyper-V appliance launcher")

    def preflight(self, args):
        if not args.launcher:
            fd = os.open("/dev/mshv", os.O_RDWR | os.O_CLOEXEC)
            os.close(fd)

    def build_command(self, args, selected, run_id):
        cmdline = ("console=ttyS0,115200 rdinit=/init panic=-1 loglevel=3 "
                   f"vv.run={run_id} vv.tests={','.join(selected)}")
        if args.launcher:
            return [args.launcher, "--kernel", str(args.kernel), "--initramfs",
                    str(args.initramfs), "--cmdline", cmdline, "--run-id", run_id]
        return [args.vmm, "--kernel", str(args.kernel), "--initramfs", str(args.initramfs),
                "--cmdline", cmdline, "--cpus", "boot=2,nested=on", "--memory", "size=1G",
                "--serial", "tty", "--console", "off"]


def create_suite():
    return MshvSuite(name="MSHV", contract=COMMIT, binary=ROOT / "target/mshv/init",
                     initramfs=ROOT / "target/mshv/initramfs.cpio.gz",
                     protocol_prefix="MSHV", requires_control=True)
