#!/usr/bin/env python3
# Author: Daniel-Marian Craciun
# SPDX-License-Identifier: MIT
#
# Quick start (PowerShell):
#   From the repository root:
#     python scripts/tools/Reconstruct_LIO/reconstruct_lio_session.py --input "E:\data\0000_lio_0"
#   After deployment, from the directory containing this script:
#     python reconstruct_lio_session.py --input "E:\data\0000_lio_0"
#
# Defaults: outputs in --input, missing CSV headers inserted, no backups.
# Optional arguments:
#   --backup                  Save modified CSV originals as .csv.bak.
#   --no-add-header           Leave the original CSV files unchanged.
#   --output-dir "E:\output"  Write outputs to a separate directory.
# Existing outputs are overwritten only after confirmation.
# Dependencies: python -m pip install numpy scipy laspy lazrs
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

"""Reconstruct a reviewable session and trajectory using only local LIO CSV/LAZ pairs.

Author: Daniel-Marian Craciun. License: MIT (full notice in this file).

No session JSON, REG, logs, basis or acquisition RAW is read. Source scans are
referenced, never rewritten. Initial poses in the new session/REG are explicitly
RECONSTRUCTED baselines; unavailable original source/reset seeds are not claimed.
The output directory defaults to the input directory; replacing existing outputs
requires interactive confirmation. Missing trajectory CSV headers are inserted in the originals by
default, without backup. Use --no-add-header to leave CSVs untouched, or --backup
to save each changed CSV as <name>.csv.bak before insertion.
This file is standalone; no other project scripts are required.
"""
from __future__ import annotations

import argparse
import colorsys
import csv
import importlib
import json
import math
import os
import shutil
import shlex
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

def dependency_install_command(packages):
    command = [sys.executable, "-m", "pip", "install", *packages]
    return "& " + subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)


def load_dependencies():
    """Check dependencies before touching source/output files; keep --help usable."""
    global laspy, np, Rotation
    modules = {}
    failures = {}
    for package, module in (("numpy", "numpy"), ("scipy", "scipy.spatial.transform"),
                            ("laspy", "laspy"), ("lazrs", "lazrs")):
        try:
            modules[package] = importlib.import_module(module)
        except (ImportError, OSError) as error:
            failures[package] = str(error)
    if failures:
        details = "\n".join(f"  {package}: {error}" for package, error in failures.items())
        raise RuntimeError("Missing or unusable Python dependencies: " + ", ".join(failures) +
                           ".\nInstall them for the Python interpreter running this script:\n  " +
                           dependency_install_command(failures) + "\nDetails:\n" + details)
    laspy, np, Rotation = modules["laspy"], modules["numpy"], modules["scipy"].Rotation
    if not {laspy.LazBackend.Lazrs, laspy.LazBackend.LazrsParallel}.intersection(laspy.LazBackend.detect_available()):
        raise RuntimeError("laspy could not detect a working lazrs backend for LAZ files.\n"
                           "Check the laspy/lazrs installation for this Python interpreter:\n  " +
                           dependency_install_command(("laspy", "lazrs")))


@dataclass
class Segment:
    path: Path
    index: int
    time_ns: np.ndarray
    poses: np.ndarray
    imu_rotation: np.ndarray | None
    scan: Path | None
    has_header: bool = True
    delimiter: str | None = None
    columns: tuple[str, ...] = ()


def trajectory_columns(width):
    columns = ["timestamp_nanoseconds"] + [f"pose{r}{c}" for r in range(3) for c in range(4)]
    if width in (14, 17, 18):
        columns.append("timestampUnix_nanoseconds")
    if width in (17, 18):
        columns += ["om_rad", "fi_rad", "ka_rad"]
    if width == 18:
        columns.append("ndt_epoch")
    if len(columns) != width:
        raise ValueError(f"Unsupported trajectory column count: {width}")
    return tuple(columns)


def load_segments(directory: Path) -> list[Segment]:
    entries = list(directory.iterdir())
    paths = [p for p in entries if "trajectory_lio_" in p.stem and p.suffix.lower() == ".csv"]
    scans_by_stem = {}
    for path in entries:
        if path.suffix.lower() in (".las", ".laz"):
            scans_by_stem.setdefault(path.stem, []).append(path)
    if not paths:
        raise ValueError(f"No trajectory_lio CSVs in {directory}")
    prefixes = {p.stem.rsplit("trajectory_lio_", 1)[0] for p in paths}
    if len(prefixes) != 1:
        raise ValueError("Multiple source session prefixes; reconstruct each session separately")
    paths.sort(key=lambda p: int(p.stem.rsplit("_", 1)[1]))
    result = []
    for path in paths:
        with path.open(encoding="utf-8-sig") as stream:
            first_line = stream.readline().strip()
        delimiter = "," if "," in first_line else None
        fields = [s.strip() for s in first_line.split(delimiter)]
        try:
            float(fields[0])
            has_header = False
        except (ValueError, IndexError):
            has_header = True
        raw = np.loadtxt(path, skiprows=int(has_header), delimiter=delimiter, ndmin=2,
                         dtype=np.longdouble, encoding="utf-8-sig")
        if raw.shape[1] < 13 or len(raw) < 1 or not np.isfinite(raw[:, :13]).all():
            raise ValueError(f"Invalid/short trajectory: {path}")
        columns = tuple(fields) if has_header else trajectory_columns(raw.shape[1])
        times = raw[:, 0].copy()
        if np.any(np.diff(times) <= 0):
            raise ValueError(f"Non-increasing timestamps inside {path}")
        poses = np.repeat(np.eye(4)[None], len(raw), axis=0)
        poses[:, :3, :] = np.asarray(raw[:, 1:13], dtype=np.float64).reshape(-1, 3, 4)
        imu = None
        if all(name in columns for name in ("om_rad", "fi_rad", "ka_rad")):
            angles = np.asarray(raw[:, [columns.index(name) for name in ("om_rad", "fi_rad", "ka_rad")]], dtype=float)
            if np.isfinite(angles).all():
                # Legacy om/fi/ka use Rx(om)*Ry(fi)*Rz(ka), matching C++.
                imu = Rotation.from_euler("XYZ", angles).as_matrix()
        scans = scans_by_stem.get(path.stem.replace("trajectory_lio_", "scan_lio_"), [])
        if len(scans) > 1:
            raise ValueError(f"Ambiguous scan for {path.name}")
        result.append(Segment(path, int(path.stem.rsplit("_", 1)[1]), times, poses, imu,
                              scans[0] if scans else None, has_header, delimiter, columns))
    if any(b.index != a.index + 1 for a, b in zip(result, result[1:])):
        raise ValueError("Missing segment indices: do not bridge an unknown time interval silently")
    return result


def recover(segments: list[Segment], method: str):
    """Recover full rigid transforms from CSV samples only."""
    if method not in ("endpoint_se3", "constant_velocity", "ahrs_velocity"):
        raise ValueError("Choose a full rigid-transform reconstruction method")
    roots = [np.eye(4)]
    for previous, following in zip(segments, segments[1:]):
        gap = float((following.time_ns[0] - previous.time_ns[-1]) * np.longdouble("1e-9"))
        if gap < 0:
            raise ValueError("Overlapping time intervals require matched-pose recovery; only disjoint/touching segments are supported")
        last, first = previous.poses[-1], following.poses[0]
        predicted = last.copy()
        if method in ("constant_velocity", "ahrs_velocity"):
            if len(previous.poses) < 2 or (method == "ahrs_velocity" and len(following.poses) < 2):
                raise ValueError("Velocity recovery requires at least two endpoint samples")
            before = previous.poses[-2]
            dt = float((previous.time_ns[-1] - previous.time_ns[-2]) * np.longdouble("1e-9"))
            velocity = (last[:3, 3] - before[:3, 3]) / dt
            delta = Rotation.from_matrix(before[:3, :3].T @ last[:3, :3]).as_rotvec()
            predicted[:3, :3] = last[:3, :3] @ Rotation.from_rotvec(delta * gap / dt).as_matrix()
            predicted[:3, 3] += velocity * gap
            if method == "ahrs_velocity":
                if previous.imu_rotation is None or following.imu_rotation is None:
                    raise ValueError("Missing AHRS angle columns")
                after = following.poses[1]
                predicted[:3, :3] = last[:3, :3] @ previous.imu_rotation[-1].T @ following.imu_rotation[0]
                dt_next = float((following.time_ns[1] - following.time_ns[0]) * np.longdouble("1e-9"))
                next_velocity = (after[:3, 3] - first[:3, 3]) / dt_next
                next_rotation = predicted[:3, :3] @ first[:3, :3].T
                predicted[:3, 3] = last[:3, 3] + (velocity + next_rotation @ next_velocity) * gap * .5
        roots.append(roots[-1] @ predicted @ np.linalg.inv(first))
    return np.stack(roots)


def write_reg(path, segments, roots):
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(f"{len(segments)}\n")
        for segment, matrix in zip(segments, roots):
            stream.write((segment.scan.name if segment.scan else segment.path.stem.replace("trajectory_lio_", "scan_lio_") + ".laz") + "\n")
            for row in matrix:
                stream.write(" ".join(format(float(value), ".17g") for value in row) + "\n")


OUTPUT_NAMES = ("session.json", "poses.reg", "lio_initial_poses.reg", "complete_trajectory.laz",
                "complete_trajectory.csv", "reconstruction_report.json", "boundaries.csv",
                "INCOMPLETE.txt")


def existing_outputs(output_dir):
    paths = [output_dir / name for name in OUTPUT_NAMES
             if (output_dir / name).exists() or (output_dir / name).is_symlink()]
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise FileExistsError(f"Reconstruction target is not a regular file: {path}")
    return paths


def confirm_output_overwrite(paths):
    print("The following output files already exist and will be overwritten:", flush=True)
    for path in paths:
        print(f"  {path}", flush=True)
    try:
        return input("Confirm overwrite? [y/N]: ").strip().casefold() in ("yes", "y")
    except (EOFError, KeyboardInterrupt):
        return False


def snapshot(path):
    stat = path.stat()
    return {"path": str(path.resolve()), "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def header_targets(segments, add_header, backup):
    targets = [segment for segment in segments if add_header and not segment.has_header]
    if backup:
        for segment in targets:
            backup_path = Path(str(segment.path.resolve()) + ".bak")
            if backup_path.exists() or backup_path.is_symlink():
                raise FileExistsError(f"CSV backup will not be overwritten: {backup_path}")
    return targets


def insert_header(segment, backup):
    """Prepend only a header; copy every original data byte without reformatting."""
    path = segment.path.resolve()
    backup_path = Path(str(path) + ".bak") if backup else None
    temporary = None
    try:
        with path.open("rb") as source:
            first_line = source.readline()
            newline = b"\r\n" if first_line.endswith(b"\r\n") else b"\n"
            header = (segment.delimiter or " ").join(trajectory_columns(len(segment.columns))).encode("utf-8") + newline
            source.seek(0)
            with tempfile.NamedTemporaryFile(mode="wb", prefix=path.name + ".", suffix=".tmp",
                                             dir=path.parent, delete=False) as destination:
                temporary = Path(destination.name)
                prefix = source.read(3)
                if prefix == b"\xef\xbb\xbf":
                    destination.write(prefix + header)
                else:
                    destination.write(header + prefix)
                shutil.copyfileobj(source, destination)
                destination.flush()
                os.fsync(destination.fileno())
        shutil.copymode(path, temporary)
        if backup_path is not None:
            # Exclusive creation protects any existing user backup, even after preflight.
            with backup_path.open("xb") as destination:
                try:
                    with path.open("rb") as source:
                        shutil.copyfileobj(source, destination)
                    destination.flush()
                    os.fsync(destination.fileno())
                except BaseException:
                    destination.close()
                    backup_path.unlink()
                    raise
        os.replace(temporary, path)
        return {"path": str(path), "backup_path": str(backup_path) if backup_path is not None else None,
                "header": header.decode("utf-8").rstrip("\r\n")}
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def color(index):
    return colorsys.hsv_to_rgb((index * .618033988749895) % 1, .65, .95)


def world_poses(segment, root):
    return root[None, :, :] @ segment.poses


def write_complete_trajectory(output, segments, roots, method, requested_scale, progress):
    lower = np.full(3, np.inf)
    upper = -lower
    length = 0.0
    previous = None
    for segment, root in zip(segments, roots):
        xyz = world_poses(segment, root)[:, :3, 3]
        lower = np.minimum(lower, xyz.min(axis=0)); upper = np.maximum(upper, xyz.max(axis=0))
        length += float(np.linalg.norm(np.diff(xyz, axis=0), axis=1).sum())
        if previous is not None:
            length += float(np.linalg.norm(xyz[0] - previous))
        previous = xyz[-1]
    scale = max(requested_scale, float((upper - lower).max()) / 4e9)
    header = laspy.LasHeader(point_format=3, version="1.4")
    header.scales = np.full(3, scale)
    header.offsets = lower + (upper - lower) * .5
    header.generating_software = "HDMapping LIO recovery"
    header.system_identifier = "Reconstructed trajectory"
    header.vlrs.append(laspy.VLR(user_id="hdmapping", record_id=65001,
        description="GPS-Time units per second", record_data=struct.pack("<d", 1.0)))
    header.vlrs.append(laspy.VLR(user_id="hdmapping", record_id=65002,
        description="Trajectory recovery provenance", record_data=json.dumps({
            "clock": "lidar_seconds", "timestamp_ns": "original LiDAR timestamp rounded to integer nanoseconds",
            "method": method, "estimated": True, "frame": "first_segment_local_frame",
            "original_source_initial_poses_available": False}).encode("utf-8")))
    extra = [("segment_id", np.uint32), ("pose_in_segment", np.uint32), ("pose_id", np.uint32),
             ("timestamp_ns", np.uint64), ("qx", np.float64), ("qy", np.float64),
             ("qz", np.float64), ("qw", np.float64)]
    header.add_extra_dims([laspy.ExtraBytesParams(name=name, type=kind) for name, kind in extra])
    next_id = 0
    stride = max(1, len(segments) // 20)
    with laspy.open(output / "complete_trajectory.laz", mode="w", header=header, do_compress=True) as writer, \
            (output / "complete_trajectory.csv").open("w", encoding="utf-8", newline="") as csv_stream:
        csv_writer = csv.writer(csv_stream)
        csv_writer.writerow(["segment_id", "pose_in_segment", "pose_id", "timestamp_nanoseconds",
                             "x", "y", "z", "qx", "qy", "qz", "qw"])
        for index, (segment, root) in enumerate(zip(segments, roots)):
            world = world_poses(segment, root)
            xyz = world[:, :3, 3]
            quaternions = Rotation.from_matrix(world[:, :3, :3]).as_quat()
            count = len(world)
            points = laspy.ScaleAwarePointRecord.zeros(count, header=header)
            points.x, points.y, points.z = xyz.T
            points.gps_time = np.asarray(segment.time_ns * np.longdouble("1e-9"), dtype=float)
            points.return_number = points.number_of_returns = np.ones(count, dtype=np.uint8)
            points.intensity = np.full(count, segment.index % 65536, dtype=np.uint16)
            points.point_source_id = np.full(count, segment.index % 65536, dtype=np.uint16)
            for channel, value in zip(("red", "green", "blue"), color(segment.index)):
                points[channel] = np.full(count, round(value * 65535), dtype=np.uint16)
            points["segment_id"] = np.full(count, segment.index, dtype=np.uint32)
            points["pose_in_segment"] = np.arange(count, dtype=np.uint32)
            points["pose_id"] = np.arange(next_id, next_id + count, dtype=np.uint32)
            rounded_time = np.rint(segment.time_ns)
            if np.any(rounded_time < 0) or np.any(rounded_time >= np.longdouble(2) ** 64):
                raise ValueError("Timestamp does not fit the unsigned nanosecond attribute")
            points["timestamp_ns"] = rounded_time.astype(np.uint64)
            for channel, values in zip(("qx", "qy", "qz", "qw"), quaternions.T):
                points[channel] = values
            writer.write_points(points)
            csv_writer.writerows((segment.index, i, next_id + i, np.format_float_positional(timestamp, trim="-"),
                                 *position, *quaternion)
                                for i, (timestamp, position, quaternion) in enumerate(zip(segment.time_ns, xyz, quaternions)))
            next_id += count
            if index % stride == 0 or index + 1 == len(segments):
                progress(f"Trajectory: {index + 1}/{len(segments)} segments, {next_id} poses")
    return {"point_count": next_id, "scale_m": scale, "bounds_min": lower.tolist(), "bounds_max": upper.tolist(),
            "length_m": length, "gps_time_units_per_second": 1, "time_clock": "LiDAR", "downsampled": False}


def validate_trajectory(path, segments, roots, scale):
    """Read every output point and verify XYZ, clock, orientation and row IDs."""
    checked = 0
    max_xyz_error = 0.0
    with laspy.open(path) as reader:
        if reader.header.point_count != sum(len(segment.poses) for segment in segments):
            raise ValueError("Trajectory LAZ point count differs from the CSV row count")
        for segment, root in zip(segments, roots):
            points = reader.read_points(len(segment.poses))
            expected = world_poses(segment, root)
            xyz = np.column_stack((points.x, points.y, points.z))
            error = float(np.max(np.abs(xyz - expected[:, :3, 3])))
            if error > scale * .501 + 1e-8:
                raise ValueError(f"Trajectory LAZ XYZ mismatch in segment {segment.index}")
            max_xyz_error = max(max_xyz_error, error)
            if not np.array_equal(points["segment_id"], np.full(len(points), segment.index)) or \
                    not np.array_equal(points["pose_in_segment"], np.arange(len(points))) or \
                    not np.array_equal(points["pose_id"], np.arange(checked, checked + len(points))):
                raise ValueError("Trajectory LAZ row/segment IDs changed")
            np.testing.assert_array_equal(points["timestamp_ns"], np.rint(segment.time_ns).astype(np.uint64))
            np.testing.assert_allclose(points.gps_time, np.asarray(segment.time_ns * np.longdouble("1e-9"), dtype=float), rtol=0, atol=0)
            actual_q = np.column_stack([points[name] for name in ("qx", "qy", "qz", "qw")])
            np.testing.assert_allclose(actual_q, Rotation.from_matrix(expected[:, :3, :3]).as_quat(), rtol=0, atol=1e-14)
            checked += len(points)
    return {"checked_points": checked, "max_xyz_axis_error_m": max_xyz_error,
            "checked": ["XYZ", "GPS time", "nanosecond timestamp", "quaternion", "segment and pose indices"]}


def reconstruct(input_dir, output_dir=None, method="endpoint_se3", trajectory_scale=.0001, progress=print,
                *, add_header=True, backup=False, confirm_overwrite=None):
    load_dependencies()
    input_dir = Path(input_dir).resolve()
    output_dir = input_dir if output_dir is None else Path(output_dir).resolve()
    if output_dir.exists() and not output_dir.is_dir():
        raise NotADirectoryError(f"Output path is not a directory: {output_dir}")
    conflicts = existing_outputs(output_dir)
    if conflicts and (confirm_overwrite is None or not confirm_overwrite(tuple(conflicts))):
        raise FileExistsError(f"Overwrite not confirmed; existing reconstruction targets will not be overwritten in {output_dir}. Choose another --output-dir or confirm replacement.")
    if method not in ("endpoint_se3", "constant_velocity", "ahrs_velocity"):
        raise ValueError("Choose a full rigid-transform reconstruction method")
    if not math.isfinite(trajectory_scale) or trajectory_scale <= 0:
        raise ValueError("Trajectory scale must be finite and positive")
    progress("Reading only trajectory_lio CSVs and scan_lio LAS/LAZ headers...")
    segments = load_segments(input_dir)
    manifest = []
    scan_points = 0
    for segment in segments:
        if segment.scan is None:
            raise ValueError(f"Missing corresponding scan for {segment.path.name}")
        trajectory_columns(len(segment.columns))
        manifest += [snapshot(segment.path), snapshot(segment.scan)]
        with laspy.open(segment.scan) as reader:
            scan_points += reader.header.point_count
    roots = recover(segments, method)
    if not np.isfinite(roots).all():
        raise ValueError("Reconstructed poses are not finite")
    total = sum(len(segment.poses) for segment in segments)
    if total > np.iinfo(np.uint32).max:
        raise ValueError("Too many poses for the output pose_id attribute")
    targets = header_targets(segments, add_header, backup)
    progress(f"Input: {len(segments)} pairs, {total} poses, {scan_points} source LiDAR points")
    output_dir.mkdir(parents=True, exist_ok=True)
    staging = tempfile.TemporaryDirectory(prefix=".lio_reconstruction_", dir=output_dir)
    working_dir = Path(staging.name)
    incomplete = working_dir / "INCOMPLETE.txt"
    with incomplete.open("x", encoding="utf-8") as marker:
        marker.write("Reconstruction not yet validated. Do not use incomplete outputs.\n")
    try:
        records = []
        for segment, root in zip(segments, roots):
            matrix = {"format": "resso_matrix3x4_v1", "m": root[:3].ravel().tolist()}
            rgb = list(color(segment.index))
            records.append({"file_name": str(segment.scan.resolve()), "trajectory_file_name": str(segment.path.resolve()),
                "original_trajectory_file_name": str(segment.path.resolve()), "pose": matrix, "initial_pose": matrix,
                "initial_pose_status": "reconstructed_baseline", "source_initial_pose_status": "unavailable",
                "source_segment_relation": "reconstructed", "source_segment_index": segment.index,
                "show_original_point_color": False, "render_color": rgb, "default_render_color": rgb,
                "trajectory_render_color": rgb, "default_trajectory_render_color": rgb, "visible": True, "point_size": 1})
        progress("Session references original trajectory CSVs directly; no copies created")
        write_reg(working_dir / "poses.reg", segments, roots)
        write_reg(working_dir / "lio_initial_poses.reg", segments, roots)
        trajectory = write_complete_trajectory(working_dir, segments, roots, method, trajectory_scale, progress)
        progress("Validating every point in complete_trajectory.laz...")
        validation = validate_trajectory(working_dir / "complete_trajectory.laz", segments, roots, trajectory["scale_m"])
        for original in manifest:
            if snapshot(Path(original["path"])) != original:
                raise ValueError(f"Input changed during reconstruction: {original['path']}")
        # Only change source headers after the reconstructed trajectory has passed validation.
        header_updates = []
        for segment in targets:
            header_updates.append(insert_header(segment, backup))
        progress(f"CSV headers inserted: {len(header_updates)}; backups: {'enabled' if backup else 'disabled'}")
        updated_manifest = [snapshot(Path(original["path"])) for original in manifest]
        boundary_rows = []
        for i, (a, b) in enumerate(zip(segments, segments[1:])):
            tail, head = roots[i] @ a.poses[-1], roots[i + 1] @ b.poses[0]
            gap_ms = float((b.time_ns[0] - a.time_ns[-1]) * np.longdouble("1e-6"))
            boundary_rows.append({"from_segment": a.index, "to_segment": b.index, "gap_ms": gap_ms,
                "reconstructed_translation_gap_m": float(np.linalg.norm(head[:3, 3] - tail[:3, 3])),
                "reconstructed_rotation_gap_deg": float(np.degrees(Rotation.from_matrix(tail[:3, :3].T @ head[:3, :3]).magnitude()))})
        provenance = {"method": method, "approximate": True, "input_types": ["trajectory_lio CSV", "scan_lio LAS/LAZ"],
            "frame": "first_segment_local_frame", "absolute_georeferencing_recovered": False,
            "original_source_initial_poses_available": False,
            "initial_pose_policy": "initial_pose and lio_initial_poses.reg are explicitly reconstructed baselines, not recovered original reset seeds",
            "boundary_assumption": "consecutive segment endpoint poses coincide" if method == "endpoint_se3" else "motion extrapolation across the missing boundary interval",
            "registration_performed": False}
        session = {"Session Settings": {"offset_x": 0., "offset_y": 0., "offset_z": 0., "ground_truth": False,
                "folder_name": str(input_dir), "out_folder_name": str(output_dir),
                "poses_file_name": str(output_dir / "poses.reg"), "initial_poses_file_name": str(output_dir / "lio_initial_poses.reg"),
                "out_poses_file_name": str(output_dir / "poses.reg"), "load_cache_mode": False, "copc_max_depth": -1},
            "step2_session_schema": {"schema_version": 4, "authoritative_pose_source": "laz_file_names.pose+initial_pose",
                                     "per_segment_pose_format": "resso_matrix3x4_v1", "original_source_initial_poses_available": False},
            "laz_file_names": records, "loop_closure_edges": [], "ground_control_points": [], "control_points": [],
            "sub_session_refs": [], "provenance_time_settings": {"auto_resolve_overlaps": False, "gap_seconds": 10.0},
            "reconstruction": provenance}
        report = {"status": "complete_and_validated", "input_directory": str(input_dir), "output_directory": str(output_dir),
                  "segment_count": len(segments), "trajectory_pose_count": total, "source_lidar_point_count": scan_points,
                  "headerless_csv_count": sum(not segment.has_header for segment in segments),
                  "trajectory": trajectory, "trajectory_validation": validation,
                  "source_files_unchanged": not header_updates, "source_numeric_data_unchanged": True,
                  "trajectory_csv_headers": {"add_if_missing": add_header, "backup_requested": backup,
                                             "inserted_count": len(header_updates), "updated_files": header_updates},
                  "reconstruction": provenance, "boundaries": boundary_rows, "input_files": manifest,
                  "input_files_after_header_update": updated_manifest}
        (working_dir / "reconstruction_report.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
        with (working_dir / "boundaries.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(boundary_rows[0]) if boundary_rows else ["from_segment"])
            writer.writeheader(); writer.writerows(boundary_rows)
        (working_dir / "session.json").write_text(json.dumps(session, indent=2, allow_nan=False), encoding="utf-8")
        # Preserve existing results throughout generation and validation. Publish
        # the entry point last, and never replace a newly appeared unapproved file.
        unexpected = [path for path in existing_outputs(output_dir) if path not in conflicts]
        if unexpected:
            raise FileExistsError(f"Unconfirmed reconstruction targets appeared during processing: {unexpected}")
        for name in (*[name for name in OUTPUT_NAMES if name not in ("session.json", "INCOMPLETE.txt")], "session.json"):
            os.replace(working_dir / name, output_dir / name)
        (output_dir / "INCOMPLETE.txt").unlink(missing_ok=True)
        return report
    except Exception as error:
        if not conflicts:
            # Do not invalidate a previously saved session on a failed rerun.
            marker = output_dir / "INCOMPLETE.txt"
            if not marker.exists():
                with marker.open("x", encoding="utf-8") as stream:
                    stream.write("Reconstruction failed; outputs are incomplete.\n" + str(error) + "\n")
        raise
    finally:
        staging.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, help="Output directory (default: --input); replacing existing outputs requires confirmation")
    parser.add_argument("--method", choices=("endpoint_se3", "constant_velocity", "ahrs_velocity"), default="endpoint_se3")
    parser.add_argument("--trajectory-scale", type=float, default=.0001, help="Requested trajectory XYZ quantization in metres")
    parser.add_argument("--add-header", action=argparse.BooleanOptionalAction, default=True,
                        help="Insert a missing header in original trajectory CSVs (default: enabled); --no-add-header leaves them untouched")
    parser.add_argument("--backup", action=argparse.BooleanOptionalAction, default=False,
                        help="Before header insertion, save the original CSV as <name>.csv.bak (default: disabled); existing backups are never overwritten")
    args = parser.parse_args()
    try:
        result = reconstruct(args.input, args.output_dir, args.method, args.trajectory_scale,
                             progress=lambda message: print(message, flush=True),
                             add_header=args.add_header, backup=args.backup,
                             confirm_overwrite=confirm_output_overwrite)
        print(f"SUCCESS: {result['segment_count']} segments, {result['trajectory_pose_count']} trajectory points")
        output_dir = Path(result["output_directory"])
        print("Session:", output_dir / "session.json")
        print("Trajectory:", output_dir / "complete_trajectory.laz")
        print("Estimated frame: first segment. Initial REG poses are reconstructed baselines; original source seeds remain unavailable.")
        return 0
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
