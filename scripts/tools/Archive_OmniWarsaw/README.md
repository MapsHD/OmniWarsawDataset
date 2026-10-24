# Download OmniWarsaw from Internet Archive

**Start downloading:** [Use four connections and keep retrying temporary failures](#use-four-connections-and-keep-retrying-temporary-failures)
for a command you can copy and run immediately.

For requirements, setup, all available options, and troubleshooting, continue
reading below.

Download [warszawa.zip](https://archive.org/download/OmniWarsaw-lidar/warszawa.zip)
from the [OmniWarsaw-lidar dataset](https://archive.org/details/OmniWarsaw-lidar)
with parallel connections, resumable downloads, progress reporting, and MD5
verification. The archive is not extracted automatically.

Metadata checked on October 24, 2026:

| Property | Value |
| --- | --- |
| Internet Archive item | `OmniWarsaw-lidar` |
| Archive filename | `warszawa.zip` |
| Size | 181,673,765,490 bytes, approximately 181.7 GB / 169.2 GiB |
| MD5 | `c7b6439e53c8d455fb99238806956c12` |

The script reads the size and checksum from the Internet Archive metadata API at
startup. The values above are a reference; the API response determines the
expected file size and checksum for each run.

## Requirements

- Python **3.10 or newer**, available as `python` or through the Windows `py`
  launcher. Only the Python standard library is used; no packages need installing.
- Windows PowerShell for the `.ps1` and `.cmd` launchers.
- An Internet connection for the download and the initial metadata lookup.
- An NTFS or exFAT destination drive with at least approximately **182 GB free**
  for a new download, preferably with additional space available. FAT32 cannot
  store this archive. Extracting the dataset requires additional space.

Check your Python installation in PowerShell or Command Prompt:

```text
python --version
```

If `python` is unavailable, try `py -3 --version`. The Windows launcher tries
`python` first and falls back to `py -3` if the `python` command is absent.

## Quick start: copy and paste

Open **PowerShell or Command Prompt in the repository root**, the folder
containing the main `README.md` and the `scripts` directory. Paste this single
line to download the dataset into `D:\OmniWarsaw` using four connections and
unlimited retries for temporary failures:

```text
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\tools\Archive_OmniWarsaw\Download-Archive_OmniWarsaw.ps1" -Destination "D:\OmniWarsaw" -Jobs 4 -Retries -1
```

Replace the destination with your preferred folder. The script creates it if
necessary. Keep quotation marks around paths, especially when they contain
spaces. The execution-policy override applies to this PowerShell process;
it does not change the saved execution policy.

To resume a stopped download, **run the same command with the same destination**.

You can also double-click `Download-Archive_OmniWarsaw.cmd`. Without arguments,
it downloads into the following folder inside the script directory and waits
for a key press before closing:

```text
scripts\tools\Archive_OmniWarsaw\data\OmniWarsaw-lidar
```

For portable use, copy these three files together into a folder:

- `download_archive_omniwarsaw.py`
- `Download-Archive_OmniWarsaw.ps1`
- `Download-Archive_OmniWarsaw.cmd`

## Windows launcher options

These options apply to both the PowerShell and Command Prompt launchers:

| Option | Default | Description |
| --- | --- | --- |
| `-Destination "PATH"` | `data\OmniWarsaw-lidar` inside the script directory | Output folder. Reuse it to resume. Relative paths are resolved from the current working directory. |
| `-Jobs N` | `4` | Concurrent download workers, from `1` to `8`. Can be changed when resuming. |
| `-Retries N` | `8` | Retries per segment after the initial attempt. Use `0` for no retries or `-1` for unlimited retries of retryable failures. |
| `-List` | Off | Display metadata for the target ZIP without downloading it. Writes the metadata cache and lock file in the destination. |
| `-Status` | Off | Display the latest saved status without network access. Requires an existing status snapshot. |

Use the list and status options separately. If both are supplied, status takes
precedence. Only one downloader may use a destination folder at a time.

## Command examples

All examples below assume that your current directory is the repository root.

### Check metadata before downloading

Print the archive name, size, MD5 checksum, and URL without transferring the ZIP:

```text
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\tools\Archive_OmniWarsaw\Download-Archive_OmniWarsaw.ps1" -Destination "D:\OmniWarsaw" -List
```

### Download or resume with four connections

With Python 3.10+ installed and approximately **182 GB free**, open PowerShell or
Command Prompt **in the repository root** and paste this command. Replace
`D:\OmniWarsaw` with your preferred download folder:

```text
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\tools\Archive_OmniWarsaw\Download-Archive_OmniWarsaw.ps1" -Destination "D:\OmniWarsaw" -Jobs 4
```

To resume, run the same command with the same destination. Keep both
`warszawa.zip.part` and `warszawa.zip.part.json` until the download finishes.

### Use four connections and keep retrying temporary failures

With Python 3.10+ installed and approximately **182 GB free**, open PowerShell or
Command Prompt **in the repository root** and paste this command. Replace
`D:\OmniWarsaw` with your preferred download folder:

```text
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\tools\Archive_OmniWarsaw\Download-Archive_OmniWarsaw.ps1" -Destination "D:\OmniWarsaw" -Jobs 4 -Retries -1
```

`-Retries -1` keeps retrying temporary segment failures until the transfer
succeeds or you stop it. To resume, run the same command with the same
destination, keeping both `warszawa.zip.part` and `warszawa.zip.part.json`.

You can change `-Jobs` to any value from `1` to `8`. More connections do not
guarantee a faster download. Speed depends on Internet Archive, your connection,
and the destination disk.

### Use one connection

```text
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\tools\Archive_OmniWarsaw\Download-Archive_OmniWarsaw.ps1" -Destination "D:\OmniWarsaw" -Jobs 1
```

### Read the latest saved status

This can run in another terminal while the downloader is active, or after it has
stopped. It prints a snapshot rather than continuously refreshing:

```text
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\tools\Archive_OmniWarsaw\Download-Archive_OmniWarsaw.ps1" -Destination "D:\OmniWarsaw" -Status
```

### Use the Command Prompt launcher

Run this from **Command Prompt**. It pauses for a key press after completion:

```bat
.\scripts\tools\Archive_OmniWarsaw\Download-Archive_OmniWarsaw.cmd -Destination "D:\OmniWarsaw" -Jobs 4 -Retries 8
```

### Run Python directly

This exposes the additional options listed in the next section:

```text
python ".\scripts\tools\Archive_OmniWarsaw\download_archive_omniwarsaw.py" --destination "D:\OmniWarsaw" --jobs 4 --timeout 30 --retries 8
```

If needed, replace `python` with `py -3`.

## Python command-line options

The Python script accepts the following options. The Windows launchers expose
only the options in the Windows launcher table above.

| Option | Default | Description |
| --- | --- | --- |
| `--destination PATH` | `data/OmniWarsaw-lidar` inside the script directory | Output folder, created if necessary. |
| `--item IDENTIFIER` | `OmniWarsaw-lidar` | Internet Archive item identifier. |
| `--file NAME` | `warszawa.zip` | Exact filename from the item's metadata. Must be a single safe filename without directory components, with a positive size and an MD5 entry in the metadata. |
| `--jobs N` | `4` | Concurrent download workers, from `1` to `8`. |
| `--timeout SECONDS` | `30` | Positive socket timeout for network operations, not a limit on the total download duration. |
| `--retries N` | `8` | Retries per segment: `0` disables retries; `-1` allows unlimited retries of retryable failures. |
| `--list` | Off | Display metadata for the selected file without downloading its contents. |
| `--status` | Off | Display the latest local status snapshot without network access. |
| `-h`, `--help` | Off | Show command-line help and exit. |

Display the built-in help:

```text
python ".\scripts\tools\Archive_OmniWarsaw\download_archive_omniwarsaw.py" --help
```

To test a complete download and checksum verification with a small file from the
same item, use a separate destination:

```text
python ".\scripts\tools\Archive_OmniWarsaw\download_archive_omniwarsaw.py" --destination ".\download-test" --file "OmniWarsaw-lidar_archive.torrent" --jobs 1
```

This downloads the torrent descriptor only. It does not start a BitTorrent
client or download the dataset through BitTorrent. Use a separate destination
for each item or target file because metadata cache and status filenames are
shared within a destination.

## Progress and output files

By default, four workers download **64 MiB segments** into one partial file.
There is no additional full-size copy for assembling the segments.

Console progress appears approximately every **10 seconds** and includes the
current phase, percentage, bytes processed, average speed, estimated remaining
time, completed segments, and active segment details. During MD5 verification,
the progress and ETA describe hashing rather than network transfer.

The status JSON is updated approximately every **second** while the session
runs. It contains the state, downloaded and durably saved bytes, completed
segments, active workers, verification progress, speed, ETA, and any errors.

| File in the destination | Purpose |
| --- | --- |
| `warszawa.zip.part` | Archive data written so far. Its apparent size is not a reliable measure of progress because segments may finish out of order. |
| `warszawa.zip.part.json` | Resume checkpoint identifying the archive and segments saved to disk. Keep it together with the partial file. |
| `download-status.json` | Latest progress snapshot. The checkpoint determines resume behavior. |
| `.archive-metadata.json` | Cached metadata, used if the API is unavailable after startup retries. |
| `.archive-download.lock` | Operating-system lock preventing concurrent downloaders in the same folder. The file may remain after exit; the operating system releases the lock when the process ends. |
| `warszawa.zip` | Final archive, named only after successful size and MD5 verification. |

## Stop, resume, and verify

1. Press **Ctrl+C** to request a controlled stop. An active network operation may
   take approximately the configured timeout to return, normally 30 seconds.
2. Keep the partial archive and its matching checkpoint in the same destination.
3. Run the original command again. Completed segments are skipped; incomplete
   segments restart from their beginning. You may change the number of workers.

A segment is recorded as complete only after its data has been synchronized to
disk. Completed segments can therefore be reused after closing the terminal,
terminating the process, or restarting Windows. With the default segment size,
up to 64 MiB per active worker may need to be downloaded again.

Windows must remain awake for the transfer to continue. The script does not
change sleep settings or restart automatically after sign-in.

After all segments are saved, the script reads the entire file to verify its
size and MD5 checksum. For an approximately 182 GB archive, this step can take
significant time even after the network transfer reaches 100%. On success, it
renames the partial file to the final archive, removes the checkpoint, and
reports `OK` and `Archive downloaded and MD5 verified.`

If the final archive already exists, running the download command verifies it
instead of downloading it again. Startup still attempts to read metadata, with
the local cache available as a fallback.

## Connection failures and retries

By default, each segment gets one initial attempt and up to **eight retries**
for connection failures and HTTP `408`, `429`, `500`, `502`, `503`, and `504`.
Backoff starts at two seconds and increases to 60 seconds. An HTTP `Retry-After`
header can request a longer delay. Saved segments are preserved if retries are
exhausted.

Unlimited retries keep retrying retryable segment failures until the transfer
succeeds or you stop it. They do not bypass permanent HTTP errors such as
`403`/`404`, invalid range responses, checksum failures, or checkpoint errors.
Permission-denied and disk-full errors also stop the transfer.

Metadata retrieval has a separate policy: up to **three startup attempts**,
followed by the local metadata cache if available. Unlimited segment retries do
not make metadata retrieval retry indefinitely. On the first run, a successful
metadata lookup is required.

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| Python is missing or the Microsoft Store opens | Install Python 3.10+ and ensure the Python version command works, or use the Python launcher with the direct Python command. |
| Not enough disk space | Choose a drive with sufficient free space. To move an interrupted download, stop the downloader and move the entire destination folder before resuming with its new path. |
| Another downloader is already running in this folder | Stop the other process or choose another destination. Deleting the lock file is not a substitute for stopping the process. |
| Status reports a missing file | A status snapshot has not been created in that destination. Listing metadata alone does not create one. |
| Metadata is unavailable and no cache exists | Retry when the API and your connection are available. |
| HTTP 403 or 404 | Check access to the item and whether the requested file still exists. Unlimited retries do not bypass these errors. |
| The server did not honor the requested byte range | The response is rejected before writing. Retry later or check whether a proxy or server is changing range responses. |
| Checkpoint mismatch, missing partial file, or invalid segment list | Files are preserved. Restore the matching partial file and checkpoint pair, or move both out of the destination and start a new download. |
| MD5 mismatch | The file is preserved and is not accepted as a verified archive. Stop the downloader, move the affected partial file and checkpoint pair, or the existing final archive, elsewhere, then run again to download a fresh copy. |

Exit codes are `0` for success, `1` for a download or runtime error, `2` for
Python argument validation errors, and `130` for a handled interruption. Launcher
errors or forced termination may produce other exit codes. The Command Prompt
launcher prints the exit code before waiting for a key press.

## Local tests

Run the included test suite from the repository root:

```text
python -m unittest discover -s ".\scripts\tools\Archive_OmniWarsaw" -p "test_*.py" -v
```

The tests use a local HTTP server and temporary files. They do not contact
Internet Archive or download the full dataset. They cover parallel transfers,
resume after process termination, checksum verification, transient failures,
invalid range responses, metadata caching, status reporting, and destination
locking.
