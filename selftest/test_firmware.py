# SPDX-License-Identifier: Apache-2.0
"""Verify public OpenVMM firmware acquisition and local reuse."""

import contextlib
import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from lib import esp, firmware
from test_boot_image import firmware_volume


def firmware_archive(data, name="./FV/MSVM.fd", kind=tarfile.REGTYPE):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        member = tarfile.TarInfo(name)
        member.type = kind
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    return buffer.getvalue()


class FirmwareFetchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name) / "firmware"
        self.image = firmware_volume()
        self.archive = firmware_archive(self.image)
        patches = (
            ("image_digest", patch.object(firmware, "FIRMWARE_SHA256",
                                          hashlib.sha256(self.image).hexdigest())),
            ("archive_digest", patch.object(firmware, "ARCHIVE_SHA256",
                                            hashlib.sha256(self.archive).hexdigest())),
            ("network", patch.object(esp, "urlopen", side_effect=self.response)),
        )
        for name, patcher in patches:
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def response(self, request, timeout):
        self.assertEqual(request.full_url, firmware.ARCHIVE_URL)
        self.assertEqual(timeout, 30)
        return io.BytesIO(self.archive)

    def fetch(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return firmware.fetch(self.output)

    def test_downloads_and_extracts_the_pinned_public_firmware(self):
        selected = self.fetch()
        self.assertEqual(selected, self.output / "MSVM.fd")
        self.assertEqual(selected.read_bytes(), self.image)
        self.assertEqual((self.output / firmware.ARCHIVE_NAME).read_bytes(), self.archive)
        self.network.assert_called_once()
        self.assertFalse(list(self.output.glob(".download-*")))
        self.assertFalse(list(self.output.glob(".extract-*")))

    def test_verified_firmware_is_reused_without_network_access(self):
        selected = self.fetch()
        self.network.reset_mock()
        self.network.side_effect = AssertionError("Cache reuse must not download")
        self.assertEqual(self.fetch(), selected)
        self.network.assert_not_called()

    def test_verified_archive_can_restore_missing_firmware_without_downloading(self):
        self.fetch().unlink()
        self.network.reset_mock()
        self.assertEqual(self.fetch().read_bytes(), self.image)
        self.network.assert_not_called()

    def test_corrupted_download_is_not_cached_or_published(self):
        self.archive = b"corrupted"
        with self.assertRaisesRegex(RuntimeError, "SHA256 mismatch"):
            self.fetch()
        self.assertFalse((self.output / firmware.ARCHIVE_NAME).exists())
        self.assertFalse((self.output / "MSVM.fd").exists())
        self.assertFalse(list(self.output.glob(".download-*")))

    def test_corrupted_cached_archive_is_not_silently_replaced(self):
        self.output.mkdir()
        (self.output / firmware.ARCHIVE_NAME).write_bytes(b"corrupted")
        with self.assertRaisesRegex(RuntimeError, "SHA256 mismatch"):
            self.fetch()
        self.network.assert_not_called()
        self.assertFalse((self.output / "MSVM.fd").exists())

    def test_existing_firmware_is_verified_and_not_overwritten(self):
        selected = self.fetch()
        selected.write_bytes(b"existing file")
        self.network.reset_mock()
        with self.assertRaisesRegex(RuntimeError, "SHA256 mismatch"):
            self.fetch()
        self.assertEqual(selected.read_bytes(), b"existing file")
        self.network.assert_not_called()

    def test_network_failure_does_not_publish_partial_firmware(self):
        self.network.side_effect = OSError("Network unavailable")
        with self.assertRaisesRegex(OSError, "Network unavailable"):
            self.fetch()
        self.assertFalse((self.output / firmware.ARCHIVE_NAME).exists())
        self.assertFalse((self.output / "MSVM.fd").exists())
        self.assertFalse(list(self.output.glob(".download-*")))

    def test_missing_firmware_member_is_an_error(self):
        self.archive = firmware_archive(self.image, name="other-file")
        with patch.object(firmware, "ARCHIVE_SHA256",
                          hashlib.sha256(self.archive).hexdigest()), \
             self.assertRaises(KeyError):
            self.fetch()
        self.assertFalse((self.output / "MSVM.fd").exists())
        self.assertFalse(list(self.output.glob(".extract-*")))

    def test_firmware_link_is_not_followed(self):
        self.archive = firmware_archive(b"", kind=tarfile.SYMTYPE)
        with patch.object(firmware, "ARCHIVE_SHA256",
                          hashlib.sha256(self.archive).hexdigest()), \
             self.assertRaisesRegex(RuntimeError, "Expected a regular firmware file"):
            self.fetch()
        self.assertFalse((self.output / "MSVM.fd").exists())

    def test_invalid_firmware_format_is_not_published(self):
        image = b"invalid firmware"
        self.archive = firmware_archive(image)
        with patch.object(firmware, "ARCHIVE_SHA256",
                          hashlib.sha256(self.archive).hexdigest()), \
             patch.object(firmware, "FIRMWARE_SHA256", hashlib.sha256(image).hexdigest()), \
             self.assertRaises(ValueError):
            self.fetch()
        self.assertFalse((self.output / "MSVM.fd").exists())

    def test_extracted_firmware_digest_must_match_the_pin(self):
        self.archive = firmware_archive(b"wrong firmware")
        with patch.object(firmware, "ARCHIVE_SHA256",
                          hashlib.sha256(self.archive).hexdigest()), \
             self.assertRaisesRegex(RuntimeError, "SHA256 mismatch"):
            self.fetch()
        self.assertFalse((self.output / "MSVM.fd").exists())

    def test_cli_reports_download_errors(self):
        errors = io.StringIO()
        with patch.object(firmware, "fetch", side_effect=OSError("Network unavailable")), \
             contextlib.redirect_stderr(errors), \
             self.assertRaises(SystemExit) as exit:
            firmware.main(["--output", str(self.output)])
        self.assertEqual(exit.exception.code, 2)
        self.assertIn("OpenVMM firmware preparation failed", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
