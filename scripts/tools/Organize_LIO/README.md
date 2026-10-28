# Organize LIO files

`move_files.py` is the English version of `muta_fisiere.py`. It uses only the
Python standard library.

For each immediate subfolder of the input directory, the script moves regular
files whose names contain `lio` (case-insensitive) into a destination inside
that subfolder:

| Source subfolder | Destination inside it |
| --- | --- |
| `name1234` | `1234_lio_0` |
| `name_0012` | `0012_lio_0` |
| `scan` | `SLAM_lio_0` |

The trailing digits determine the index, including any leading zeros. Files
directly in the input directory and files in deeper subfolders are left in
place. Symbolic links and junctions are skipped. A destination folder is created
even if there are no matching files.

From the repository root, preview the changes first:

```text
python ".\scripts\tools\Organize_LIO\move_files.py" "D:\warszawa" --dry-run
```

Then run the move:

```text
python ".\scripts\tools\Organize_LIO\move_files.py" "D:\warszawa"
```

Replace `D:\warszawa` with the directory containing your scan folders.
`--dry-run` creates no folders and moves no files. Existing destination files
are skipped. Exit codes are `0` for success, `1` for errors or skipped conflicts,
and `2` for invalid command-line arguments.

Run the included checks on temporary files:

```text
python -B -m unittest discover -s ".\scripts\tools\Organize_LIO" -p "test_*.py" -v
```

## Author and license

Author: Daniel-Marian Craciun. Copyright (c) 2026.

`move_files.py` and `test_move_files.py` are distributed under the MIT License.
The full copyright and permission notice is included in each Python file and
must accompany copies. This license applies to these scripts, not to the dataset
or the rest of the repository.
