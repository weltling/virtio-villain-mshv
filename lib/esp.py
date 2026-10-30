# SPDX-License-Identifier: Apache-2.0
"""Fetch and extract pinned Azure Linux boot components without installation."""

import argparse
import fcntl
from http.client import HTTPException
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.request import Request, urlopen

from .boot_image import ESP_COMPONENTS, _validate_pe, sha256

PACKAGE_URL = "https://packages.microsoft.com/azurelinux/3.0/prod/"
PACKAGES = {
    "base/x86_64/Packages/s/shim-16.1-1.azl3.x86_64.rpm":
        "96b829294cc11ee5e0e08178bd544adf2a8033df4ce95650b2183234ae4d40b3",
    "base/x86_64/Packages/g/grub2-efi-binary-2.06-27.azl3.x86_64.rpm":
        "c47d6e5becf63971609dd198035f8bc30fac9271d3a0367d01380b466601303d",
    "base/x86_64/Packages/h/hvloader-1.0.1-5.azl3.x86_64.rpm":
        "5363ff63b0774db99fa8ddf1a5ab4f5387fbe628e6f23a8ba713d104748e7400",
    "ms-non-oss/x86_64/Packages/m/mshv-26100.9444.2609032029.1-1.azl3.x86_64.rpm":
        "95a95671546fc29488ffd8b61c00d9869928ceca25005f5c1ca3beaaf83d9385",
    "ms-non-oss/x86_64/Packages/m/"
    "mshv-bootloader-lx-26100.9444.2609032029.1-1.azl3.x86_64.rpm":
        "cf75cc2633df5d35484ea75aacea7d308a1b18f4064c0e159d99e0e20c48df63",
}
FILES = (
    *ESP_COMPONENTS.values(),
    "licenses/hvloader/LICENSE",
    "licenses/mshv/EULA.txt",
    "licenses/mshv-bootloader-lx/EULA.txt",
)


def verify(path, expected):
    actual = sha256(path)
    if actual != expected:
        raise RuntimeError(f"SHA256 mismatch for {path}: expected {expected}, actual {actual}")


def download(name, expected, cache):
    path = cache / Path(name).name
    for cached in (path, cache.parent / path.name):
        if cached.exists():
            verify(cached, expected)
            return cached
    print(f"Downloading {path.name}", flush=True)
    request = Request(PACKAGE_URL + name, headers={"User-Agent": "virtio-villain-mshv"})
    with tempfile.TemporaryDirectory(prefix=".download-", dir=cache) as temporary:
        partial = Path(temporary) / path.name
        with urlopen(request, timeout=30) as response, partial.open("wb") as stream:
            shutil.copyfileobj(response, stream)
        verify(partial, expected)
        partial.replace(path)
    return path


def fetch(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    esp = output / "esp"
    with (output / ".lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (esp / "manifest.json").exists():
            manifest = json.loads((esp / "manifest.json").read_text())
            if (not isinstance(manifest, dict) or manifest.get("packages") != PACKAGES
                    or not isinstance(manifest.get("files"), dict)
                    or set(manifest["files"]) != set(FILES)):
                raise RuntimeError(f"Boot component metadata does not match pinned RPMs: {esp}")
            for name in FILES:
                verify(esp / name, manifest["files"][name])
            return esp

        if not shutil.which("bsdtar"):
            raise RuntimeError("Missing RPM extraction tool: bsdtar")
        cache = output / "rpms"
        cache.mkdir(exist_ok=True)
        packages = [download(name, digest, cache) for name, digest in PACKAGES.items()]
        with tempfile.TemporaryDirectory(prefix=".extract-", dir=output) as temporary:
            root = Path(temporary)
            for package in packages:
                subprocess.run(["bsdtar", "-xf", str(package), "-C", str(root)], check=True)
            prepared = root / "boot/efi"
            for name in ESP_COMPONENTS.values():
                path = prepared / name
                with path.open("rb") as stream:
                    _validate_pe(stream, path.stat().st_size)
            shutil.copytree(root / "usr/share/licenses", prepared / "licenses")
            (prepared / "manifest.json").write_text(json.dumps({
                "packages": PACKAGES,
                "files": {name: sha256(prepared / name) for name in FILES},
            }, indent=2) + "\n")
            if esp.exists():
                if (not esp.is_dir() or esp.is_symlink()
                        or any(path.is_symlink() for path in esp.rglob("*"))):
                    raise RuntimeError(
                        f"Existing ESP must be a directory without symbolic links: {esp}")
                for name in FILES:
                    path = esp / name
                    if path.exists() or name in ESP_COMPONENTS.values():
                        verify(path, sha256(prepared / name))
                for name in FILES:
                    path = esp / name
                    if not path.exists():
                        path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(prepared / name, path)
                (prepared / "manifest.json").replace(esp / "manifest.json")
            else:
                prepared.rename(esp)
    return esp


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="Directory containing cached RPMs and extracted ESP files")
    args = parser.parse_args(argv)
    print("MSHV use requires an active Microsoft Azure agreement. Review the package EULAs.",
          flush=True)
    try:
        esp = fetch(args.output)
    except (OSError, RuntimeError, ValueError, HTTPException, subprocess.SubprocessError) as error:
        parser.exit(2, f"Boot component preparation failed: {error}\n")
    print(f"Boot components: {esp}")


if __name__ == "__main__":
    main()
