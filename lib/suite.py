# SPDX-License-Identifier: Apache-2.0
"""MSHV launch policy using Virtio Villain orchestration and reporting."""

import os
from pathlib import Path
from lib.appliance import Suite, source_catalog
from .contract import COMMIT

ROOT = Path(__file__).resolve().parents[1]


class MshvSuite(Suite):
    def list_tests(self, binary):
        return source_catalog(ROOT.glob("tests/*/*.c"), "REGISTER_MSHV_TEST")

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
        cmdline = ("console=ttyS0,115200 rdinit=/init panic=-1 loglevel=3 vv.shutdown=host "
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
                     protocol_prefix="MSHV", host_shutdown=True)
