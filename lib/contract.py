#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Extract the tested ABI from the reviewed full kernel source, not host headers."""

import argparse
from pathlib import Path
import re
import subprocess


COMMIT = "d461acfb591c198755f6e84494f8a68a3b6d8bd2"
STRUCTS = ("mshv_create_partition", "mshv_create_vp", "mshv_vp_registers")
ENUMS = ("MSHV_PT_BIT_LAPIC", "MSHV_PT_ISOLATION_NONE")
DEFINES = ("MSHV_IOCTL", "MSHV_PT_FLAGS_MASK", "MSHV_CREATE_PARTITION", "MSHV_INITIALIZE_PARTITION",
           "MSHV_CREATE_VP", "MSHV_VP_MAX_REGISTERS", "MSHV_GET_VP_REGISTERS",
           "MSHV_SET_VP_REGISTERS")


def extract(source):
    def git(*args):
        return subprocess.check_output(
            ["git", "-C", str(source), *args], text=True).strip()

    if git("rev-parse", "HEAD") != COMMIT:
        raise RuntimeError(f"Unreviewed MSHV contract: expected kernel commit {COMMIT}")
    if git("status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("MSHV contract source has tracked modifications")
    text = (source / "include/uapi/linux/mshv.h").read_text()
    snippets = []
    for name in ENUMS:
        match = re.search(
            r"enum\s*\{(?=[^}]*\b" + re.escape(name) + r"\b)[^}]+\};", text)
        if match is None:
            raise RuntimeError(f"Missing UAPI enumeration containing {name}")
        snippets.append(match[0])
    for name in STRUCTS:
        match = re.search(r"struct " + name + r" \{[^}]+\};", text)
        if match is None:
            raise RuntimeError(f"Missing UAPI structure: {name}")
        snippets.append(match[0].replace("__user ", ""))
    for name in DEFINES:
        match = re.search(r"^#define " + name + r"\s+[^\n]+", text, re.MULTILINE)
        if match is None:
            raise RuntimeError(f"Missing UAPI definition: {name}")
        snippets.append(match[0])
    return ("/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */\n"
            "/* Generated from the selected kernel; do not edit. */\n"
            f'#define VV_MSHV_CONTRACT "{COMMIT}"\n'
            + "\n".join(snippets) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        header = extract(args.source.resolve())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if not args.output.exists() or args.output.read_text() != header:
            args.output.write_text(header)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    main()
