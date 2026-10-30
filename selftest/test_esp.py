# SPDX-License-Identifier: Apache-2.0
"""Verify pinned boot package downloads, extraction and local reuse."""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from lib import esp
from test_boot_image import pe_image

ROOT = Path(__file__).resolve().parents[1]


class EspTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "inputs"
        self.payloads = {f"packages/fixture-{index}.rpm": f"RPM {index}".encode()
                         for index in range(5)}
        packages = {name: hashlib.sha256(data).hexdigest()
                    for name, data in self.payloads.items()}
        mocks = (
            ("PACKAGES", patch.object(esp, "PACKAGES", packages)),
            ("network", patch.object(esp, "urlopen", side_effect=self.response)),
            ("extractor", patch.object(esp.subprocess, "run", side_effect=self.extract)),
            ("tool", patch.object(esp.shutil, "which", return_value="/usr/bin/bsdtar")),
        )
        for name, patcher in mocks:
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def response(self, request, timeout):
        self.assertEqual(timeout, 30)
        return io.BytesIO(self.payloads[request.full_url.removeprefix(esp.PACKAGE_URL)])

    def extract(self, command, *, check):
        self.assertTrue(check)
        self.assertEqual(command[:2], ["bsdtar", "-xf"])
        root = Path(command[command.index("-C") + 1])
        for name in esp.ESP_COMPONENTS.values():
            path = root / "boot/efi" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(pe_image())
        for name in esp.FILES:
            if name.startswith("licenses/"):
                path = root / "usr/share" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture license")

    def fetch(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return esp.fetch(self.output)

    def test_downloads_verifies_and_extracts_complete_components_and_licenses(self):
        directory = self.fetch()
        self.assertEqual(directory, self.output / "esp")
        self.assertEqual(self.network.call_count, 5)
        self.assertEqual(self.extractor.call_count, 5)
        manifest = json.loads((directory / "manifest.json").read_text())
        self.assertEqual(manifest["packages"], self.PACKAGES)
        self.assertEqual(set(manifest["files"]), set(esp.FILES))
        for name, digest in manifest["files"].items():
            self.assertEqual(esp.sha256(directory / name), digest)
        self.assertFalse(list(self.output.glob(".extract-*")))
        self.assertFalse(list((self.output / "rpms").glob(".download-*")))

    def test_prepared_components_work_without_network_or_extraction_tools(self):
        first = self.fetch()
        self.network.reset_mock()
        self.network.side_effect = AssertionError("Cache reuse must not download")
        self.extractor.reset_mock()
        self.tool.return_value = None
        self.assertEqual(self.fetch(), first)
        self.network.assert_not_called()
        self.extractor.assert_not_called()

    def test_existing_manual_components_are_verified_before_adoption(self):
        self.output.mkdir()
        for name, data in self.payloads.items():
            (self.output / Path(name).name).write_bytes(data)
        unpacked = self.root / "manual"
        self.extract(["bsdtar", "-xf", "/fixture", "-C", str(unpacked)], check=True)
        shutil.copytree(unpacked / "boot/efi", self.output / "esp")
        original = {name: (self.output / "esp" / name).read_bytes()
                    for name in esp.ESP_COMPONENTS.values()}
        directory = self.fetch()
        self.network.assert_not_called()
        self.assertTrue((directory / "manifest.json").is_file())
        self.assertTrue((directory / "licenses/mshv/EULA.txt").is_file())
        for name, data in original.items():
            self.assertEqual((directory / name).read_bytes(), data)

    def test_existing_manual_components_are_not_overwritten_on_mismatch(self):
        directory = self.output / "esp"
        directory.mkdir(parents=True)
        original = directory / "EFI/BOOT/bootx64.efi"
        original.parent.mkdir(parents=True)
        original.write_bytes(b"existing boot component")
        with self.assertRaisesRegex(RuntimeError, "SHA256 mismatch"):
            self.fetch()
        self.assertEqual(original.read_bytes(), b"existing boot component")
        self.assertFalse((directory / "manifest.json").exists())
        self.assertFalse((directory / "licenses").exists())

    def test_corrupted_download_is_not_cached_or_published(self):
        self.payloads[next(iter(self.payloads))] = b"corrupted"
        with self.assertRaisesRegex(RuntimeError, "SHA256 mismatch"):
            self.fetch()
        self.assertFalse((self.output / "esp").exists())
        self.assertEqual(list((self.output / "rpms").iterdir()), [])
        self.extractor.assert_not_called()

    def test_corrupted_cached_rpm_fails_without_network_access(self):
        cache = self.output / "rpms"
        cache.mkdir(parents=True)
        (cache / Path(next(iter(self.PACKAGES))).name).write_bytes(b"corrupted")
        with self.assertRaisesRegex(RuntimeError, "SHA256 mismatch"):
            self.fetch()
        self.network.assert_not_called()
        self.extractor.assert_not_called()
        self.assertFalse((self.output / "esp").exists())

    def test_network_failure_does_not_publish_partial_components(self):
        self.network.side_effect = OSError("Network unavailable")
        with self.assertRaisesRegex(OSError, "Network unavailable"):
            self.fetch()
        self.assertFalse((self.output / "esp").exists())
        self.assertEqual(list((self.output / "rpms").iterdir()), [])
        self.extractor.assert_not_called()

    def test_extraction_failure_can_retry_using_verified_cached_rpms(self):
        self.extractor.side_effect = subprocess.CalledProcessError(1, ["bsdtar"])
        with self.assertRaises(subprocess.CalledProcessError):
            self.fetch()
        self.assertFalse((self.output / "esp").exists())
        self.assertFalse(list(self.output.glob(".extract-*")))
        self.network.reset_mock()
        self.extractor.side_effect = self.extract
        self.assertTrue(self.fetch().is_dir())
        self.network.assert_not_called()

    def test_invalid_component_is_not_published(self):
        def invalid(command, *, check):
            self.extract(command, check=check)
            root = Path(command[command.index("-C") + 1])
            (root / "boot/efi/HvLoader.efi").write_bytes(b"invalid")

        self.extractor.side_effect = invalid
        with self.assertRaises(ValueError):
            self.fetch()
        self.assertFalse((self.output / "esp").exists())
        self.assertFalse(list(self.output.glob(".extract-*")))

    def test_modified_prepared_component_is_an_error_not_a_download_trigger(self):
        directory = self.fetch()
        (directory / "HvLoader.efi").write_bytes(b"modified")
        self.network.reset_mock()
        self.extractor.reset_mock()
        with self.assertRaisesRegex(RuntimeError, "SHA256 mismatch"):
            self.fetch()
        self.network.assert_not_called()
        self.extractor.assert_not_called()

    def test_invalid_manifest_is_not_replaced(self):
        directory = self.fetch()
        manifest = directory / "manifest.json"
        manifest.write_text("{}")
        self.network.reset_mock()
        with self.assertRaisesRegex(RuntimeError, "metadata does not match"):
            self.fetch()
        self.assertEqual(manifest.read_text(), "{}")
        self.network.assert_not_called()

    def test_missing_extraction_tool_fails_before_downloads(self):
        self.tool.return_value = None
        with self.assertRaisesRegex(RuntimeError, "Missing RPM extraction tool: bsdtar"):
            self.fetch()
        self.network.assert_not_called()

    def test_cli_reports_preparation_errors(self):
        errors = io.StringIO()
        with patch.object(esp, "fetch", side_effect=OSError("Network unavailable")), \
             contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(errors), \
             self.assertRaises(SystemExit) as exit:
            esp.main(["--output", str(self.output)])
        self.assertEqual(exit.exception.code, 2)
        self.assertIn("Boot component preparation failed: Network unavailable", errors.getvalue())


@unittest.skipUnless(shutil.which("make"), "Make required for ESP target checks")
class EspMakeTests(unittest.TestCase):
    def test_make_input_targets_use_the_selected_output_without_building_an_appliance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            suite = root / "suite"
            library = suite / "lib"
            library.mkdir(parents=True)
            shutil.copyfile(ROOT / "Makefile", suite / "Makefile")
            record = root / "arguments.json"
            for name in ("esp", "firmware"):
                (library / f"{name}.py").write_text(
                    "import json, sys\n"
                    "from pathlib import Path\n"
                    f"Path({str(record)!r}).write_text(json.dumps(sys.argv[1:]))\n")
            for goal, directory, target in (
                    (goal, directory, target)
                    for goal, directory in (
                        ("esp", "mshv-boot-inputs"), ("openvmm-firmware", "openvmm-firmware"))
                    for target in ("target", str(root / "custom output"))):
                with self.subTest(goal=goal, target=target):
                    result = subprocess.run([
                        "make", "--no-print-directory", "-C", str(suite),
                        "-j", goal, goal, f"TARGET={target}",
                    ], capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    expected = Path(target)
                    if not expected.is_absolute():
                        expected = suite / expected
                    arguments = json.loads(record.read_text())
                    self.assertEqual(arguments[0], "--output")
                    output = Path(arguments[1])
                    if not output.is_absolute():
                        output = suite / output
                    self.assertEqual(output, expected / directory)
            self.assertFalse((suite / "target/mshv/init").exists())


if __name__ == "__main__":
    unittest.main()
