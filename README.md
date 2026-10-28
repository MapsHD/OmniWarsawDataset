# OmniWarsawDataset

Scanning plans, documentation of the process:

https://github.com/miloszwojciechowski/Warsaw-model/tree/main

[Final report](https://github.com/miloszwojciechowski/Warsaw-model/blob/main/Warsaw_scanning_updates/Warsaw_scanning_report.pdf)

Opensource open-hardware:

https://github.com/JanuszBedkowski/mandeye_controller

## Download dataset

The Lidar data can be downloaded from:

https://archive.org/details/OmniWarsaw-lidar

For resumable downloads with parallel connections, progress reporting and MD5 verification,
see the [Windows downloader instructions](scripts/tools/Archive_OmniWarsaw/README.md).

From PowerShell or Command Prompt in the repository root, copy and run:

```text
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\tools\Archive_OmniWarsaw\Download-Archive_OmniWarsaw.ps1" -Destination "D:\OmniWarsaw" -Jobs 4 -Retries -1
```

Replace `D:\OmniWarsaw` with your download folder. Run the same command again to
resume. This uses four connections and unlimited retries for temporary failures.
Python 3.10+ and approximately 182 GB of free disk space are required.

## Organize LIO files

Move LIO files into numbered scan subfolders. See the
[organizer instructions](scripts/tools/Organize_LIO/README.md) for naming rules
and options. Preview the changes before moving files:

```powershell
python scripts/tools/Organize_LIO/move_files.py "E:\OmniWarsaw" --dry-run
```

Replace the input path with the directory containing your scan folders. Remove
`--dry-run` to move the files.

## Reconstruct a processed LIO session

If a processed folder contains `trajectory_lio_*.csv` and `scan_lio_*.laz` but is
missing `session.json` or registration files, use the standalone reconstruction
script. See the [reconstruction guide](scripts/tools/Reconstruct_LIO/README.md) for
installation, CSV header and backup options, output files and recovery assumptions.

```powershell
python scripts/tools/Reconstruct_LIO/reconstruct_lio_session.py --input "E:\OmniWarsaw\continousScanning_0010\0000_lio_0"
```

By default, results are written into the input folder and missing headers are
inserted into the original trajectory CSV files without backups. Existing results
require overwrite confirmation.
