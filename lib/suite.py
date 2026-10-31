# SPDX-License-Identifier: Apache-2.0
"""MSHV launch policy using Virtio Villain orchestration and reporting."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from villain import process
from villain.appliance import Suite, executable, source_catalog
from villain.vmm import CloudHypervisor, LaunchConfig, OpenVmm
from .boot_image import FIRMWARE, prepare_image, resolve_firmware, validate_boot_inputs
from .build import create_build
from .sources import test_sources

ROOT = Path(__file__).resolve().parents[1]


def vmm_backend(binary, backend):
    if backend == "openvmm" or (backend == "auto" and "openvmm" in Path(binary).name):
        return OpenVmm(binary)
    return CloudHypervisor(binary)


class MshvSuite(Suite):
    def list_tests(self, binary):
        return source_catalog(
            test_sources(ROOT), "REGISTER_MSHV_TEST", metadata=True,
            definitions=[ROOT / "lib/mshv.h"])

    def add_arguments(self, parser):
        parser.epilog = (
            "Use --vmm to select the Cloud Hypervisor or OpenVMM executable. "
            "OpenVMM uses KVM and local MSVM.fd prepared with make openvmm-firmware. "
            f"Cloud Hypervisor prefers installed UEFI firmware at {FIRMWARE}, otherwise download "
            "the latest cloud-hypervisor/edk2 CLOUDHV.fd with SHA256 verification. "
            "Boot files are checked before launching tests. "
            "Use make help in the suite directory for kernel config and build options.")
        parser.add_argument("--vmm", default="cloud-hypervisor",
                            help="Cloud Hypervisor MSHV or OpenVMM executable")
        parser.add_argument("--backend", choices=("auto", "ch", "openvmm"), default="auto",
                            help="VMM backend (default: OpenVMM when its name contains "
                            "'openvmm', otherwise Cloud Hypervisor)")
        parser.add_argument("--firmware", type=Path,
                            help="Local UEFI firmware override (OpenVMM default: selected "
                            "build output openvmm-firmware/MSVM.fd)")
        parser.add_argument("--esp", type=Path,
                            help="Local boot components (default: selected build output "
                            "mshv-boot-inputs/esp, prepared with make esp)")
        parser.add_argument("--offline", action="store_true",
                            help="Use installed or cached firmware without network access")

    def preflight(self, args):
        context = self.build_spec.context(args.build_dir)
        if args.esp is None:
            args.esp = context.target / "mshv-boot-inputs/esp"
            if not args.esp.is_dir():
                raise RuntimeError(
                    f"No prepared boot components at {args.esp}. "
                    "Run make esp with the matching TARGET or select --esp PATH.")
        args.esp = args.esp.resolve()
        backend = vmm_backend(args.vmm, args.backend)
        if isinstance(backend, OpenVmm):
            if args.firmware is None:
                args.firmware = context.target / "openvmm-firmware/MSVM.fd"
                if not args.firmware.is_file():
                    raise RuntimeError(
                        f"No prepared OpenVMM firmware at {args.firmware}. "
                        "Run make openvmm-firmware with the matching TARGET "
                        "or select --firmware PATH.")
            args.firmware = args.firmware.resolve()
        else:
            args.firmware = resolve_firmware(args.firmware, offline=args.offline)
        validate_boot_inputs(args.kernel, args.initramfs, args.esp, firmware=args.firmware)
        executable(args.vmm)
        device = "/dev/kvm" if isinstance(backend, OpenVmm) else "/dev/mshv"
        fd = os.open(device, os.O_RDWR | os.O_CLOEXEC)
        os.close(fd)
        args.boot_image = prepare_image(
            context.target / "boot", args.kernel, args.initramfs, args.esp, args.firmware)

    def build_command(self, args, selected, run_id):
        return self.execution_command([
            "--vmm", args.vmm, "--backend", args.backend,
            "--image", str(args.boot_image),
            "--firmware", str(args.boot_image.parent / "firmware.fd"),
            "--tests", ",".join(selected), "--run-id", run_id,
            "--output", str(args.workspace / "boot")])

    def execute(self, argv):
        parser = argparse.ArgumentParser(description="Boot the MSHV appliance")
        parser.add_argument("--vmm", required=True)
        parser.add_argument("--backend", choices=("auto", "ch", "openvmm"), default="auto")
        parser.add_argument("--image", required=True, type=Path)
        parser.add_argument("--firmware", required=True, type=Path)
        parser.add_argument("--tests", required=True)
        parser.add_argument("--run-id", required=True)
        parser.add_argument("--output", required=True, type=Path)
        args = parser.parse_args(argv)
        if not re.fullmatch(r"[A-Za-z0-9_-]+", args.run_id):
            parser.error("Invalid run identifier")
        if len(args.run_id) > 61:
            parser.error("Run identifier exceeds the SMBIOS transport limit")
        if (not re.fullmatch(r"[A-Za-z0-9_]+(?:,[A-Za-z0-9_]+)*", args.tests)
                or len(args.tests) > 32):
            parser.error("Invalid SMBIOS test selection")
        output = args.output
        output.mkdir(parents=True, exist_ok=False)
        (output / "launch.json").write_text(json.dumps({
            "image": str(args.image), "firmware": str(args.firmware),
            "image_manifest": str(args.image.parent / "manifest.json"),
            "run_id": args.run_id, "tests": args.tests.split(","),
        }, indent=2) + "\n")
        selection = args.tests.replace(",", "+")
        # Keep each SMBIOS value within the firmware string limit.
        serial, version = args.run_id[:32], "vv:" + args.run_id[32:]
        backend = vmm_backend(args.vmm, args.backend)
        if isinstance(backend, OpenVmm):
            command = backend.build_launch_cmd(
                LaunchConfig(cpus=2, memory="2G"),
                hypervisor="kvm", serial="stderr")
            command += [
                "--nested-virt", "--pcie-root-complex", "rc0,segment=1",
                "--uefi", f"firmware={args.firmware},console=com1",
                "--disk", f"file:{args.image},ro",
                "--smbios", f"type=1,serial={serial},version={version},sku={selection}",
                "--guest-shutdown-action", "exit", "--guest-reset-action", "exit",
                "--guest-crash-action", "exit:1"]
        else:
            command = backend.build_launch_cmd(
                LaunchConfig(cpus=2, memory="2G", firmware=args.firmware),
                nested=True, serial="tty", console="off")
            command += [
                "--disk", f"path={args.image},image_type=raw,readonly=on",
                "--platform",
                f"system_serial_number={serial},system_version={version},"
                f"system_sku_number={selection}"]
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
