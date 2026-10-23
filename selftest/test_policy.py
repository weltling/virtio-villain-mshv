#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Private launch policy checks using the shared appliance interface."""

import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "virtio-villain/lib/python"))
from villain import appliance  # noqa: E402


class PolicyTests(unittest.TestCase):
    def test_source_listing_without_an_appliance_binary(self):
        output = io.StringIO()
        with patch.object(appliance.subprocess, "run",
                          side_effect=AssertionError("Listing must not execute a binary")), \
             contextlib.redirect_stdout(output):
            status = appliance.main([
                "--suite", str(ROOT),
                "--binary", "/nonexistent/mshv-init", "--list"])
        self.assertEqual(status, 0)
        entries = appliance.parse_catalog(output.getvalue())
        self.assertEqual(list(entries), [
            "ML001", "ML002", "ML003", "ML004", "MR001", "MR002", "MR003"])
        self.assertTrue(all(entries.values()))
        self.assertTrue(all(not description[0].islower() for description in entries.values()))

    def test_nested_execution_without_external_control(self):
        suite = appliance.load_suite(ROOT)
        with tempfile.TemporaryDirectory() as work:
            image = Path(work) / "image"
            image.write_bytes(b"image")
            args = appliance.parse_args(suite, [
                "--kernel", str(image), "--initramfs", str(image),
                "--vmm", "/local/cloud-hypervisor", "--jobs", "16", "ML001"])
        self.assertEqual(args.jobs, 16)
        self.assertFalse(suite.requires_control)
        self.assertIsNone(args.control)
        errors = io.StringIO()
        with patch.object(os, "open", return_value=42) as opened, \
             patch.object(os, "close") as closed, \
             contextlib.redirect_stderr(errors):
            suite.preflight(args)
        opened.assert_called_once_with(
            "/dev/mshv", os.O_RDWR | os.O_CLOEXEC)
        closed.assert_called_once_with(42)
        self.assertEqual(errors.getvalue(), "")
        command = suite.build_command(args, ["ML001"], "token")
        self.assertEqual(command[0], "/local/cloud-hypervisor")
        self.assertEqual(command[command.index("--cpus") + 1], "boot=2,nested=on")
        self.assertIn("vv.tests=ML001", command[command.index("--cmdline") + 1])
        self.assertIn("vv.shutdown=host", command[command.index("--cmdline") + 1])
        self.assertTrue(suite.host_shutdown)

    def test_external_control_remains_available(self):
        suite = appliance.load_suite(ROOT)
        with tempfile.TemporaryDirectory() as work:
            image = Path(work) / "image"
            image.write_bytes(b"image")
            args = appliance.parse_args(suite, [
                "--kernel", str(image), "--initramfs", str(image),
                "--control", "/external/control", "--launcher", "/external/launcher"])
        errors = io.StringIO()
        with patch.object(os, "open") as opened, \
             contextlib.redirect_stderr(errors):
            suite.preflight(args)
        opened.assert_not_called()
        self.assertEqual(args.control, "/external/control")
        self.assertEqual(errors.getvalue(), "")
