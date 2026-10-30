# SPDX-License-Identifier: Apache-2.0
"""MSHV launch policy using Virtio Villain orchestration and reporting."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
from villain import process
from villain.appliance import Suite, executable, source_catalog
from villain.vmm import CloudHypervisor, LaunchConfig, OpenVmm
from .boot_image import FIRMWARE, build_image, resolve_firmware, validate_boot_inputs
from .build import create_build
from .sources import test_sources

ROOT = Path(__file__).resolve().parents[1]


def vmm_backend(binary, backend):
    if backend == "openvmm" or (backend == "auto" and "openvmm" in Path(binary).name):
        return OpenVmm(binary)
    return CloudHypervisor(binary)


class MshvSuite(Suite):
    def list_tests(self, binary):
        return source_catalog(test_sources(ROOT), "REGISTER_MSHV_TEST")

    def add_arguments(self, parser):
        parser.epilog = (
            "MSHV_VMM selects the default Cloud Hypervisor or OpenVMM executable. "
            "OpenVMM uses KVM and requires --firmware with MSVM.fd. "
            f"Cloud Hypervisor prefers installed UEFI firmware at {FIRMWARE}, otherwise download "
            "the latest cloud-hypervisor/edk2 CLOUDHV.fd with SHA256 verification. "
            "Boot files are checked before launching tests. "
            "Use make help in the suite directory for kernel config and build options.")
        parser.add_argument("--vmm", default=os.environ.get("MSHV_VMM", "cloud-hypervisor"),
                            help="Cloud Hypervisor MSHV or OpenVMM executable")
        parser.add_argument("--backend", choices=("auto", "ch", "openvmm"), default="auto",
                            help="VMM backend (default: OpenVMM when its name contains "
                            "'openvmm', otherwise Cloud Hypervisor)")
        parser.add_argument("--firmware", type=Path, help="Explicit local UEFI firmware")
        parser.add_argument("--esp", type=Path,
                            help="Local boot components (default: selected build output "
                            "mshv-boot-inputs/esp, prepared with make esp)")
        parser.add_argument("--offline", action="store_true",
                            help="Use installed or cached firmware without network access")

    def preflight(self, args):
        if args.esp is None:
            context = self.build_spec.context(args.build_dir)
            args.esp = context.target / "mshv-boot-inputs/esp"
            if not args.esp.is_dir():
                raise RuntimeError(
                    f"No prepared boot components at {args.esp}. "
                    "Run make esp with the matching TARGET or select --esp PATH.")
        args.esp = args.esp.resolve()
        backend = vmm_backend(args.vmm, args.backend)
        if isinstance(backend, OpenVmm):
            if args.firmware is None:
                raise RuntimeError("OpenVMM requires --firmware PATH to its MSVM.fd UEFI image")
            args.firmware = args.firmware.resolve()
        else:
            args.firmware = resolve_firmware(args.firmware, offline=args.offline)
        validate_boot_inputs(args.kernel, args.initramfs, args.esp, firmware=args.firmware)
        executable(args.vmm)
        device = "/dev/kvm" if isinstance(backend, OpenVmm) else "/dev/mshv"
        fd = os.open(device, os.O_RDWR | os.O_CLOEXEC)
        os.close(fd)

    def build_command(self, args, selected, run_id):
        cmdline = ("console=ttyS0,115200 rdinit=/init panic=-1 loglevel=3 vv.shutdown=host "
                   f"vv.run={run_id} vv.tests={','.join(selected)}")
        return self.execution_command([
            "--vmm", args.vmm, "--backend", args.backend, "--kernel", str(args.kernel),
            "--initramfs", str(args.initramfs), "--firmware", str(args.firmware),
            "--esp", str(args.esp),
            "--cmdline", cmdline, "--run-id", run_id,
            "--output", str(args.workspace / "boot")])

    def execute(self, argv):
        parser = argparse.ArgumentParser(description="Boot the MSHV appliance")
        parser.add_argument("--vmm", required=True)
        parser.add_argument("--backend", choices=("auto", "ch", "openvmm"), default="auto")
        parser.add_argument("--kernel", required=True, type=Path)
        parser.add_argument("--initramfs", required=True, type=Path)
        parser.add_argument("--firmware", required=True, type=Path)
        parser.add_argument("--esp", required=True, type=Path)
        parser.add_argument("--cmdline", required=True)
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--output", required=True, type=Path)
        args = parser.parse_args(argv)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", args.run_id):
            parser.error("Invalid run identifier")
        output = args.output
        disk = build_image(output, args.kernel, args.initramfs, args.cmdline,
                           args.esp, firmware=args.firmware)
        backend = vmm_backend(args.vmm, args.backend)
        if isinstance(backend, OpenVmm):
            command = backend.build_launch_cmd(
                LaunchConfig(cpus=2, memory="2G"),
                hypervisor="kvm", serial="stderr")
            command += [
                "--nested-virt", "--uefi", f"firmware={output / 'firmware.fd'},console=com1",
                "--disk", f"file:{disk},ro",
                "--guest-shutdown-action", "exit", "--guest-reset-action", "exit",
                "--guest-crash-action", "exit:1"]
        else:
            command = backend.build_launch_cmd(
                LaunchConfig(cpus=2, memory="2G", firmware=output / "firmware.fd"),
                nested=True, serial="tty", console="off")
            command += ["--disk", f"path={disk},image_type=raw,readonly=on"]
        print("Nested Hyper-V launch: " + " ".join(command), flush=True)
        if isinstance(backend, OpenVmm):
            # Keep REPL stdin open without leaving the supervised process group.
            with process.spawn(command, stdin=subprocess.PIPE,
                               start_new_session=False) as (proc, _):
                sys.exit(proc.wait())
        os.execvp(args.vmm, command)


def create_suite():
    build = create_build(ROOT)
    context = build.context()
    return MshvSuite(name="MSHV", contract="mshv-uapi-v1", binary=context.binary,
                     initramfs=context.initramfs, build_spec=build,
                     protocol_prefix="MSHV", host_shutdown=True,
                     kernel_build_hint=(
                         f"Build it with make -C {ROOT} kernel "
                         "MSHV_SOURCE=PATH, "
                         "or select another image with --kernel PATH."))
