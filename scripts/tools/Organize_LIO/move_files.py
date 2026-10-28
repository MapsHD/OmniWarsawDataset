#!/usr/bin/env python3
# Author: Daniel-Marian Craciun
# SPDX-License-Identifier: MIT
#
# Quick start (PowerShell, from the repository root):
#   Preview: python scripts/tools/Organize_LIO/move_files.py "D:\warszawa" --dry-run
#   Move:    python scripts/tools/Organize_LIO/move_files.py "D:\warszawa"
# From this script's directory: python move_files.py "D:\warszawa" --dry-run
# Dependencies: Python standard library only.
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

"""Organize files containing 'lio' in the immediate subfolders of a directory.

Example: python move_files.py "D:\\warszawa"
Preview without changes: add --dry-run.

name1234 or name_1234 -> 1234_lio_0; no trailing number -> SLAM_lio_0.
The index is the trailing sequence of digits; leading zeros are preserved.
All immediate subfolders are processed, without recursion into them.
"""

import argparse
from pathlib import Path
import re
import sys


def destination_name(folder_name):
    match = re.search(r"([0-9]+)$", folder_name)
    index = match.group(1) if match else "SLAM"
    return f"{index}_lio_0"


def is_link(path):
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def organize(root, dry_run=False):
    """Return 1 for errors or conflicts, otherwise 0. Never overwrite files."""
    root = Path(root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {root}")
    folders = sorted(root.iterdir(), key=lambda path: path.name.casefold())
    processed = moved = skipped = errors = 0
    for folder in folders:
        if is_link(folder) or not folder.is_dir():
            continue
        processed += 1
        target = folder / destination_name(folder.name)
        try:
            # The destination must remain a direct child of the source folder.
            if is_link(target) or target.resolve().parent != folder.resolve():
                raise ValueError(f"Destination redirects outside the source folder: {target}")
            if target.exists() and not target.is_dir():
                raise NotADirectoryError(f"Destination already exists as a file: {target}")
            files = sorted(folder.iterdir(), key=lambda path: path.name.casefold())
            if not dry_run:
                target.mkdir(exist_ok=True)
            print(f"FOLDER: {folder.name} -> {target.name}")
        except (OSError, ValueError) as error:
            print(f"ERROR: {folder}: {error}", file=sys.stderr)
            errors += 1
            continue

        for source in files:
            if "lio" not in source.name.casefold() or is_link(source) or not source.is_file():
                continue
            destination = target / source.name
            try:
                if destination.exists() or destination.is_symlink():
                    print(f"SKIPPED (already exists): {destination}")
                    skipped += 1
                    continue
                if dry_run:
                    print(f"WOULD MOVE: {source} -> {destination}")
                else:
                    source.rename(destination)
                    print(f"MOVED: {source.name}")
                moved += 1
            except OSError as error:
                print(f"ERROR: {source}: {error}", file=sys.stderr)
                errors += 1

    label = "to move" if dry_run else "moved"
    print(f"Folders: {processed}; files {label}: {moved}; skipped: {skipped}; errors: {errors}.")
    return int(bool(errors or skipped))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", type=Path, help="Directory containing the subfolders to process")
    parser.add_argument("--dry-run", action="store_true", help="Preview operations without creating or moving anything")
    args = parser.parse_args(argv)
    try:
        return organize(args.path, dry_run=args.dry_run)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
