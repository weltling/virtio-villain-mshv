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
    def test_execution_help_exposes_environment_and_build_help(self):
        with contextlib.redirect_stdout(io.StringIO()) as output, \
             self.assertRaises(SystemExit) as exit:
            appliance.main(["--suite", str(ROOT), "--help"])
        self.assertEqual(exit.exception.code, 0)
        text = " ".join(output.getvalue().split())
        for expected in ("MSHV_VMM", "make help", "--kernel"):
            self.assertIn(expected, text)

    def test_default_kernel_matches_the_suite_build_output(self):
        suite = appliance.load_suite(ROOT)
        expected = ROOT / "target/kernel-microsoft/images/bzImage-x86_64"
        self.assertEqual(suite.kernel, expected)
        self.assertIn(f"make -C {ROOT} kernel,", suite.kernel_build_hint)
        self.assertEqual(appliance.parse_args(suite, ["--list"]).kernel, expected)
        with tempfile.TemporaryDirectory() as work:
            kernel = Path(work) / "built-kernel"
            archive = Path(work) / "archive"
            kernel.write_bytes(b"kernel")
            archive.write_bytes(b"archive")
            suite.kernel = kernel
            suite.initramfs = archive
            args = appliance.parse_args(suite, ["ML001"])
            command = suite.build_command(args, ["ML001"], "token")
            self.assertEqual(command[command.index("--kernel") + 1], str(kernel))

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
        self.assertEqual(command[:3], [
            sys.executable, str(Path(appliance.__file__).with_name("suite_exec.py")),
            str(ROOT / "lib/suite.py")])
        self.assertEqual(command[command.index("--vmm") + 1], "/local/cloud-hypervisor")
        self.assertEqual(command[command.index("--run-id") + 1], "token")
        self.assertIn("vv.tests=ML001", command[command.index("--cmdline") + 1])
        self.assertIn("vv.shutdown=host", command[command.index("--cmdline") + 1])
        self.assertTrue(suite.host_shutdown)

    def test_external_control_uses_the_same_nested_environment(self):
        suite = appliance.load_suite(ROOT)
        with tempfile.TemporaryDirectory() as work:
            image = Path(work) / "image"
            image.write_bytes(b"image")
            args = appliance.parse_args(suite, [
                "--kernel", str(image), "--initramfs", str(image),
                "--control", "/external/control"])
        errors = io.StringIO()
        with patch.object(os, "open", return_value=42) as opened, \
             patch.object(os, "close") as closed, \
             contextlib.redirect_stderr(errors):
            suite.preflight(args)
        opened.assert_called_once_with("/dev/mshv", os.O_RDWR | os.O_CLOEXEC)
        closed.assert_called_once_with(42)
        self.assertEqual(args.control, "/external/control")
        self.assertEqual(errors.getvalue(), "")

    def test_default_nested_boot_needs_no_launcher_selection(self):
        suite = appliance.load_suite(ROOT)
        for override in (None, "/alternate/cloud-hypervisor"):
            with self.subTest(override=override), \
                 patch.dict(os.environ, {}, clear=True):
                if override:
                    os.environ["MSHV_VMM"] = override
                args = appliance.parse_args(suite, ["--list"])
                expected = override or str(
                    ROOT.parent / "cloud-hypervisor/target/release/cloud-hypervisor")
                self.assertEqual(args.vmm, expected)
                self.assertFalse(hasattr(args, "launcher"))

    def test_explicit_vmm_overrides_the_environment_default(self):
        suite = appliance.load_suite(ROOT)
        with patch.dict(os.environ, {"MSHV_VMM": "/environment/vmm"}):
            args = appliance.parse_args(suite, ["--list", "--vmm", "cloud-hypervisor"])
        self.assertEqual(args.vmm, "cloud-hypervisor")
