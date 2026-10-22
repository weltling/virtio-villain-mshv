#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Private launch policy checks using the shared appliance interface."""

import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "virtio-villain"))
from lib import appliance  # noqa: E402
import suite as mshv_suite  # noqa: E402


class PolicyTests(unittest.TestCase):
    def test_nested_execution_without_external_control(self):
        suite = mshv_suite.create_suite()
        with tempfile.TemporaryDirectory() as work:
            image = Path(work) / "image"
            image.write_bytes(b"image")
            args = appliance.parse_args(suite, [
                "--kernel", str(image), "--initramfs", str(image),
                "--vmm", "/local/cloud-hypervisor", "ML001"])
        self.assertFalse(suite.requires_control)
        self.assertIsNone(args.control)
        errors = io.StringIO()
        with patch.object(mshv_suite.os, "open", return_value=42) as opened, \
             patch.object(mshv_suite.os, "close") as closed, \
             contextlib.redirect_stderr(errors):
            suite.preflight(args)
        opened.assert_called_once_with(
            "/dev/mshv", mshv_suite.os.O_RDWR | mshv_suite.os.O_CLOEXEC)
        closed.assert_called_once_with(42)
        self.assertEqual(errors.getvalue(), "")
        command = suite.build_command(args, ["ML001"], "token")
        self.assertEqual(command[0], "/local/cloud-hypervisor")
        self.assertEqual(command[command.index("--cpus") + 1], "boot=2,nested=on")
        self.assertIn("vv.tests=ML001", command[command.index("--cmdline") + 1])
        self.assertIn("vv.shutdown=host", command[command.index("--cmdline") + 1])
        self.assertTrue(suite.host_shutdown)

    def test_external_control_remains_available(self):
        suite = mshv_suite.create_suite()
        with tempfile.TemporaryDirectory() as work:
            image = Path(work) / "image"
            image.write_bytes(b"image")
            args = appliance.parse_args(suite, [
                "--kernel", str(image), "--initramfs", str(image),
                "--control", "/external/control", "--launcher", "/external/launcher"])
        errors = io.StringIO()
        with patch.object(mshv_suite.os, "open") as opened, \
             contextlib.redirect_stderr(errors):
            suite.preflight(args)
        opened.assert_not_called()
        self.assertEqual(args.control, "/external/control")
        self.assertEqual(errors.getvalue(), "")
