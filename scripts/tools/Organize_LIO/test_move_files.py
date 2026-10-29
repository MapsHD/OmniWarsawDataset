#!/usr/bin/env python3
# Author: Daniel-Marian Craciun
# SPDX-License-Identifier: MIT
#
# Run tests (PowerShell, from the repository root):
#   python -B -m unittest discover -s scripts/tools/Organize_LIO -p "test_*.py" -v
# From this script's directory: python -B test_move_files.py -v
# Tests use temporary files; no real dataset is needed.
#
# MIT License
#
# Copyright (c) 2026 Daniel-Marian Craciun
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Small filesystem checks for bulk lio organization; no real input data."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

import move_files


class OrganizeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def run_organize(self, dry_run=False):
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            return move_files.organize(self.root, dry_run=dry_run)

    def test_bulk_move_keeps_root_files_nested_files_and_nonmatching_files(self):
        (self.root / "root_lio.txt").write_text("root")
        for name, expected in (("name0012", "0012_lio_0"), ("name_3456", "3456_lio_0"),
                               ("scan without index", "SLAM_lio_0")):
            folder = self.root / name
            folder.mkdir()
            for filename in ("scan_lio.laz", "LIO date!.txt", "lio", "notes.txt"):
                (folder / filename).write_text(filename)
            nested = folder / "nested_lio"
            nested.mkdir()
            (nested / "nested_lio.laz").write_text("nested")
        self.assertEqual(self.run_organize(), 0)
        self.assertTrue((self.root / "root_lio.txt").is_file())
        for name, expected in (("name0012", "0012_lio_0"), ("name_3456", "3456_lio_0"),
                               ("scan without index", "SLAM_lio_0")):
            folder = self.root / name
            for filename in ("scan_lio.laz", "LIO date!.txt", "lio"):
                self.assertEqual((folder / expected / filename).read_text(), filename)
                self.assertFalse((folder / filename).exists())
            self.assertTrue((folder / "notes.txt").is_file())
            self.assertTrue((folder / "nested_lio" / "nested_lio.laz").is_file())
        self.assertEqual(self.run_organize(), 0)
        self.assertFalse((self.root / "name0012" / "0012_lio_0" / "0_lio_0").exists())

    def test_existing_destination_never_overwrites_and_other_folders_continue(self):
        for name in ("name1", "name2"):
            folder = self.root / name
            folder.mkdir()
            (folder / "scan_lio.laz").write_text("new")
        target = self.root / "name1" / "1_lio_0"
        target.mkdir()
        (target / "scan_lio.laz").write_text("existing")
        self.assertEqual(self.run_organize(), 1)
        self.assertEqual((target / "scan_lio.laz").read_text(), "existing")
        self.assertEqual((target.parent / "scan_lio.laz").read_text(), "new")
        self.assertEqual((self.root / "name2" / "2_lio_0" / "scan_lio.laz").read_text(), "new")

    def test_empty_directory_still_gets_destination(self):
        (self.root / "scan").mkdir()
        self.assertEqual(self.run_organize(), 0)
        self.assertTrue((self.root / "scan" / "SLAM_lio_0").is_dir())

    def test_dry_run_creates_nothing_and_moves_nothing(self):
        folder = self.root / "name0123"
        folder.mkdir()
        source = folder / "scan_lio.laz"
        source.write_text("data")
        self.assertEqual(self.run_organize(dry_run=True), 0)
        self.assertTrue(source.is_file())
        self.assertFalse((folder / "0123_lio_0").exists())

    def test_destination_that_is_a_file_is_reported_without_moving_sources(self):
        folder = self.root / "name1"
        folder.mkdir()
        (folder / "1_lio_0").write_text("blocked")
        (folder / "scan_lio.txt").write_text("data")
        self.assertEqual(self.run_organize(), 1)
        self.assertEqual((folder / "scan_lio.txt").read_text(), "data")

    def test_invalid_input_returns_failure(self):
        with redirect_stderr(StringIO()):
            self.assertEqual(move_files.main([str(self.root / "missing")]), 1)
            source = self.root / "file.txt"
            source.write_text("data")
            self.assertEqual(move_files.main([str(source)]), 1)


if __name__ == "__main__":
    unittest.main()
