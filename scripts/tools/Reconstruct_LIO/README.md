# Reconstruct a LIO session from CSV and LAZ files

Use [reconstruct_lio_session.py](reconstruct_lio_session.py) when a processed
LIO folder contains trajectory CSV files and scan LAZ/LAS files but is missing
`session.json` or the registration files.

The script is standalone. Only this Python file and its installed dependencies
are needed; no other HDMapping scripts or application build are required.

**Default behavior:** results are written into the input directory, missing
headers are inserted into the original trajectory CSV files, and no CSV backups
are created. Existing output files are replaced only after confirmation.

## Installation

Use Python 3.10 or newer and install the dependencies:

```powershell
python -m pip install numpy scipy laspy lazrs
```

The script detects missing or unusable dependencies and checks that the lazrs
LAZ backend is available. If a dependency check fails, it stops before changing
files and prints an installation command for the exact Python interpreter
running the script. It does not install packages automatically.

`--help` works even when the external dependencies are missing.

## Quick start

From the repository root, run:

```powershell
python scripts/tools/Reconstruct_LIO/reconstruct_lio_session.py --input "E:\OmniWarsaw\continousScanning_0010\0000_lio_0"
```

Replace the example input path with your processed LIO folder.

To insert missing CSV headers and keep backups of the affected originals:

```powershell
python scripts/tools/Reconstruct_LIO/reconstruct_lio_session.py `
  --input "E:\OmniWarsaw\continousScanning_0010\0000_lio_0" `
  --backup
```

To leave the original CSV files unchanged and write results to a separate folder:

```powershell
python scripts/tools/Reconstruct_LIO/reconstruct_lio_session.py `
  --input "E:\OmniWarsaw\continousScanning_0010\0000_lio_0" `
  --output-dir "E:\OmniWarsaw\reconstructed_0010" `
  --no-add-header
```

If you distribute the script on its own, run the same commands from its directory
using `python reconstruct_lio_session.py` instead of the repository-relative path.

## Required input

The input directory must contain matching pairs such as:

```text
trajectory_lio_0.csv
scan_lio_0.laz
trajectory_lio_1.csv
scan_lio_1.laz
...
```

LAS scans, zero-padded indices and a shared session prefix are also supported.
Segments are sorted by numeric index. Missing indices, missing or ambiguous
scans, mixed session prefixes, non-increasing timestamps and overlapping segment
intervals are rejected.

CSV files can have an optional header and use spaces, tabs or commas as
separators. Native layouts with 13, 14, 17 or 18 columns are supported: LiDAR
timestamp, a row-major 3x4 pose matrix, and optional Unix timestamp, IMU angles
and NDT epoch. Headerless native LIO timestamps are treated as nanoseconds.

Only trajectory CSVs and the corresponding LAS/LAZ headers are read as recovery
inputs. Existing JSON/REG files, logs and acquisition RAW files are not used.
The LiDAR point payload is not loaded or rewritten.

## Options

| Option | Behavior | Default |
| --- | --- | --- |
| `--input PATH` | Processed LIO folder containing the matching pairs. | Required |
| `--output-dir PATH` | Directory for reconstructed outputs. | Same as `--input` |
| `--method METHOD` | `endpoint_se3`, `constant_velocity` or `ahrs_velocity`. | `endpoint_se3` |
| `--trajectory-scale METERS` | Requested XYZ quantization step for trajectory LAZ. | `0.0001` |
| `--add-header` / `--no-add-header` | Insert missing headers into original CSV files, or leave them untouched. | Add headers |
| `--backup` / `--no-backup` | Save each CSV about to receive a header as `<name>.csv.bak`. | No backup |
| `--help` | Show command-line help. | |

Header insertion copies all data rows byte for byte. Existing headers are not
duplicated, and CSV files that already have a header are not rewritten or backed
up. An existing `.csv.bak` for a file requiring a new header stops a backup-enabled
run before source files are changed. `--backup` has no effect with `--no-add-header`.
No `trajectories/` directory or duplicate trajectory CSV files are created.

When generated output files already exist, the script lists them and asks:

```text
Confirm overwrite? [y/N]:
```

Enter `y` or `yes` to replace the listed outputs, including any existing trajectory
LAZ/CSV and report. Enter, a negative response or end-of-input cancels the run
without changes. Unrelated files are left untouched.

## Generated files

| File | Contents |
| --- | --- |
| `session.json` | Step 2 session with embedded segment poses and absolute paths to the original scans and trajectory CSVs. |
| `poses.reg` | Reconstructed scan transforms. |
| `lio_initial_poses.reg` | The reconstructed transforms used as the new session's initial baseline. |
| `complete_trajectory.laz` | One point per CSV pose, with the reconstructed segment transform applied and no downsampling. |
| `complete_trajectory.csv` | Reconstructed positions, quaternions, timestamps and segment/pose indices. |
| `reconstruction_report.json` | Recovery assumptions, input manifests, validation results, header changes and backup paths. |
| `boundaries.csv` | Timing gaps and reconstructed spatial connections between segments. |

The scan LAZ files remain in their original locations. Their transforms are
stored in JSON/REG; this script does not export transformed scan point clouds.
Keep the original inputs accessible because the session uses absolute paths.

The trajectory LAZ includes LiDAR time in seconds as `gps_time`, an explicit
time-unit VLR, the rounded nanosecond timestamp as `timestamp_ns`, segment and
pose indices, quaternions, and colors that distinguish segments. The requested
XYZ scale is a storage quantization step, not a claim of reconstruction accuracy.

## Reconstruction assumptions

The default `endpoint_se3` method assumes that the last pose of a segment and
the first pose of the next segment describe the same spatial pose:

```text
B_0 = Identity
B_(i+1) = B_i * C_i(last) * inverse(C_(i+1)(first))
```

`C_i` is the local CSV pose and `B_i` is the transform applied to both the
segment trajectory and its scan. This composes full rotations and translations.

Use `constant_velocity` to extrapolate motion across a boundary time gap.
`ahrs_velocity` also uses IMU orientation and requires IMU angle columns.

These methods produce an estimated reconstruction. Continuity alone cannot
uniquely determine motion during missing boundary samples. The first segment
defines the output coordinate frame; absolute georeferencing and the original
source/reset pose seeds are not recovered. The session explicitly marks its
initial poses as reconstructed baselines, rather than original source seeds.
No point-cloud registration or loop-closure optimization is performed.

## Validation and opening the session

Before publishing the outputs, the script reads back every trajectory LAZ point
and verifies XYZ, timestamps, quaternions, indices and total point count. It checks
the source file manifests before inserting any requested CSV headers. New outputs
are generated and validated in a temporary directory, then published with
`session.json` last. A generation or validation failure preserves previous results.
A failed first run leaves an `INCOMPLETE.txt` marker instead of a completed session.

Open the generated `session.json` in the HDMapping/SLAM-DanC Step 2 application.
In versions that provide these controls, use C024 to load the session, or C024A
to inspect metadata and trajectories without loading all scan points into RAM.
The trajectory LAZ can also be opened separately in a point-cloud viewer.

Step 2 versions that skip the first CSV line require a header. To use
`--no-add-header` with headerless input, use a Step 2 build that supports
headerless LIO trajectories.

## Author and license

Author: Daniel-Marian Craciun. Copyright (c) 2026.

The script is distributed under the MIT License. The full copyright and
permission notice is included in the Python file and must accompany copies.
Third-party dependencies retain their own licenses.
