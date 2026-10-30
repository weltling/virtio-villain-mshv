# SPDX-License-Identifier: Apache-2.0
"""Prepare pinned public MSVM firmware for OpenVMM."""

import argparse
import fcntl
from http.client import HTTPException
from pathlib import Path
import shutil
import tarfile
import tempfile

from .boot_image import _validate_firmware
from .esp import download, verify

ARCHIVE_NAME = "RELEASE-X64-VS2022-artifacts.tar.gz"
ARCHIVE_URL = (
    "https://github.com/microsoft/mu_msvm/releases/download/v26.0.22/" + ARCHIVE_NAME)
ARCHIVE_SHA256 = "e5a2477ee3e730a7310b24a43068f89129e9b82b183f0a5901fcc1d206c577b7"
FIRMWARE_SHA256 = "660899fafe7fb955de6ebe5ed2135430dffd845841c6e07ad19774ccf273e9a3"


def fetch(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    firmware = output / "MSVM.fd"
    with (output / ".lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if firmware.exists():
            verify(firmware, FIRMWARE_SHA256)
            return firmware
        package = download(ARCHIVE_NAME, ARCHIVE_SHA256, output, url=ARCHIVE_URL)
        with tempfile.TemporaryDirectory(prefix=".extract-", dir=output) as temporary:
            staged = Path(temporary) / "MSVM.fd"
            with tarfile.open(package, "r:gz") as archive:
                member = archive.getmember("./FV/MSVM.fd")
                if not member.isfile():
                    raise RuntimeError(f"Expected a regular firmware file in {package}: FV/MSVM.fd")
                source = archive.extractfile(member)
                if source is None:
                    raise RuntimeError(f"Cannot read firmware from {package}: FV/MSVM.fd")
                with source, staged.open("wb") as stream:
                    shutil.copyfileobj(source, stream)
            verify(staged, FIRMWARE_SHA256)
            with staged.open("rb") as stream:
                _validate_firmware(stream, staged.stat().st_size)
            staged.replace(firmware)
    return firmware


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="Directory containing the firmware archive and MSVM.fd")
    args = parser.parse_args(argv)
    try:
        firmware = fetch(args.output)
    except (OSError, RuntimeError, ValueError, KeyError, tarfile.TarError, HTTPException) as error:
        parser.exit(2, f"OpenVMM firmware preparation failed: {error}\n")
    print(f"OpenVMM firmware: {firmware}")


if __name__ == "__main__":
    main()
