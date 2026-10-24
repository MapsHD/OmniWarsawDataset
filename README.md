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
