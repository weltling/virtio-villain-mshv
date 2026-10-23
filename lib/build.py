# SPDX-License-Identifier: Apache-2.0
"""Private source and kernel policy for the shared suite builder."""

import os
from pathlib import Path
import shlex
from villain.build import BuildSpec
from .sources import build_sources

KERNEL_ARCH = "x86_64"


def kernel_source(context):
    source = context.variables.get("MSHV_SOURCE", "")
    if not source.strip():
        raise RuntimeError("Set MSHV_SOURCE to the kernel source directory")
    return Path(source)


def kernel(context):
    source = kernel_source(context)
    configs = shlex.split(context.variables.get("KERNEL_CONFIGS", ""))
    if not configs:
        raise RuntimeError("Set KERNEL_CONFIGS to the kernel configuration files")
    command = ["--source", source, "--arch", KERNEL_ARCH]
    for config in configs:
        command.extend(["--config", config])
    command.extend([
        "--output", context.target / "kernel",
        "--cache-dir", context.target / "kernel-cache", "--offline",
        "--jobs", str(len(os.sched_getaffinity(0)))])
    command.extend(shlex.split(context.variables.get("KERNEL_ARGS", "")))
    environment = dict(context.variables)
    overrides = context.variables.get("VV_BUILD_OVERRIDES", "").split()
    environment["RUSTC"] = context.variables["RUSTC"] if "RUSTC" in overrides else "false"
    return context.build_kernel(command, expected_arch=KERNEL_ARCH, image="bzImage",
                                env=environment)


def create_build(root):
    return BuildSpec(
        root=root, sources=build_sources, directory=Path("mshv"), cc="gcc",
        cppflags=lambda context: [f"-I{context.root}"],
        kernel=kernel)
