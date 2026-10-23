# SPDX-License-Identifier: Apache-2.0
"""Shared source selection for compilation and test discovery."""

import argparse
from pathlib import Path


def test_sources(root):
    return sorted(root.glob("tests/*/*.c"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Suite source directory")
    root = parser.parse_args().root
    sources = [root / name for name in (
        "bin/mshv.c", "lib/lifecycle.c", "lib/registers.c")]
    print(" ".join(map(str, [*sources, *test_sources(root)])))


if __name__ == "__main__":
    main()
