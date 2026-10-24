#!/usr/bin/env python3
"""Internet Archive downloader with parallel ranges, durable resume and MD5 checking."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import http.client
import json
import math
import ntpath
import os
from pathlib import Path, PureWindowsPath
import queue
import re
import shutil
import signal
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


MIB = 1024 * 1024
CHUNK_SIZE = 64 * MIB
USER_AGENT = "HDMapping-Archive-Downloader/1.0"
is_reserved = getattr(ntpath, "isreserved", lambda name: PureWindowsPath(name).is_reserved())


class Stopped(Exception):
    pass


class InvalidDownload(Exception):
    pass


def atomic_json(path, value):
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def read_json(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def request(url, timeout, headers=None):
    return urllib.request.urlopen(urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept-Encoding": "identity", **(headers or {})}), timeout=timeout)


def safe_filename(name):
    return (bool(name) and name not in (".", "..")
            and not re.search(r'[\\/:<>"|?*\x00-\x1f]', name)
            and not name.endswith((".", " ")) and not is_reserved(name))


@dataclass(frozen=True)
class Archive:
    item: str
    name: str
    size: int
    md5: str
    url: str

    def identity(self):
        return {"item": self.item, "name": self.name, "size": self.size, "md5": self.md5}


def archive_from_metadata(record, item, name):
    if record.get("metadata", {}).get("identifier") != item:
        raise ValueError("Metadata does not match the requested item identifier.")
    if not safe_filename(name):
        raise ValueError("Unsafe filename.")
    matches = [entry for entry in record.get("files", []) if entry.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one metadata entry for archive {name!r}.")
    entry = matches[0]
    size = int(entry["size"])
    md5 = entry["md5"].lower()
    if size <= 0 or not re.fullmatch(r"[0-9a-f]{32}", md5):
        raise ValueError("Invalid file size or MD5 checksum.")
    url = f"https://archive.org/download/{urllib.parse.quote(item, safe='')}/{urllib.parse.quote(name, safe='')}"
    return Archive(item, name, size, md5, url)


def retry_delay(exc, attempt):
    delay = min(60, 2 ** min(attempt, 6))
    if isinstance(exc, urllib.error.HTTPError):
        value = exc.headers.get("Retry-After", "")
        if value.isdigit():
            delay = max(delay, int(value))
        else:
            from email.utils import parsedate_to_datetime
            try:
                delay = max(delay, parsedate_to_datetime(value).timestamp() - time.time())
            except (ValueError, TypeError, OverflowError):
                pass
    return delay


def load_archive(item, name, destination, timeout, stop):
    cache = destination / ".archive-metadata.json"
    last_error = None
    for attempt in range(3):
        if stop.is_set():
            raise Stopped()
        try:
            with request(f"https://archive.org/metadata/{urllib.parse.quote(item, safe='')}", timeout) as response:
                record = json.load(response)
            file = archive_from_metadata(record, item, name)
            atomic_json(cache, record)
            return file
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, KeyError) as exc:
            last_error = exc
            delay = retry_delay(exc, attempt + 1)
            if isinstance(exc, urllib.error.HTTPError):
                exc.close()
            if attempt < 2 and stop.wait(delay):
                raise Stopped()
    if cache.exists():
        file = archive_from_metadata(read_json(cache), item, name)
        print(f"Metadata unavailable; using the local copy. ({last_error})", flush=True)
        return file
    raise RuntimeError(f"Unable to retrieve Internet Archive metadata: {last_error}")


@contextmanager
def destination_lock(destination):
    # The operating system releases this lock even when the process is killed.
    with (destination / ".archive-download.lock").open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Another downloader is already running in this folder.") from exc
        yield


def human(value):
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024


def format_eta(seconds):
    if seconds is None:
        return "--"
    hours, remainder = divmod(math.ceil(max(0, seconds)), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class Session:
    def __init__(self, file, destination, chunk_size=CHUNK_SIZE):
        self.file = file
        self.destination = destination
        self.final = destination / file.name
        self.part = destination / (file.name + ".part")
        self.checkpoint = destination / (file.name + ".part.json")
        self.lock = threading.Lock()
        self.chunk_size = chunk_size
        self.completed = set()
        self.active = {}
        self.errors = []
        self.received = 0
        self.state = "waiting"
        self.verified_bytes = 0
        self.verification_started = None
        self.verification_finished = None
        self.started = time.monotonic()
        self.last_print = 0

    @property
    def count(self):
        return (self.file.size + self.chunk_size - 1) // self.chunk_size

    def bounds(self, index):
        start = index * self.chunk_size
        return start, min(self.file.size, start + self.chunk_size)

    def saved_bytes(self):
        return sum(self.bounds(index)[1] - self.bounds(index)[0] for index in self.completed)

    def checkpoint_value(self):
        return {"version": 1, "archive": self.file.identity(),
                "chunk_size": self.chunk_size, "completed": sorted(self.completed)}

    def prepare(self):
        if self.checkpoint.exists():
            value = read_json(self.checkpoint)
            if value.get("version") != 1 or value.get("archive") != self.file.identity():
                raise InvalidDownload("The .part metadata does not match. Existing files have been preserved.")
            size = value.get("chunk_size")
            if type(size) is not int or size <= 0:
                raise InvalidDownload("Invalid segment size in the checkpoint.")
            self.chunk_size = size
            completed = value.get("completed")
            if (not isinstance(completed, list)
                    or any(type(index) is not int or not 0 <= index < self.count for index in completed)
                    or len(set(completed)) != len(completed)):
                raise InvalidDownload("Invalid segment list in the checkpoint.")
            self.completed = set(completed)
            if self.completed and not self.part.exists():
                raise InvalidDownload("The .part file is missing, but the checkpoint contains completed segments.")
        elif self.part.exists() and self.part.stat().st_size:
            raise InvalidDownload("The .part file has no checkpoint. File preserved; move it elsewhere to start a new download.")
        if self.part.exists():
            actual_size = self.part.stat().st_size
            if (actual_size > self.file.size
                    or any(self.bounds(index)[1] > actual_size for index in self.completed)):
                raise InvalidDownload("The .part file size does not match the checkpoint. File preserved.")
        else:
            with self.part.open("xb") as stream:
                stream.flush()
                os.fsync(stream.fileno())
        atomic_json(self.checkpoint, self.checkpoint_value())

    def active_update(self, index, **changes):
        with self.lock:
            self.active.setdefault(index, {"bytes": 0, "state": "connecting", "detail": ""}).update(changes)

    def advance(self, index, count):
        with self.lock:
            self.active[index]["bytes"] += count
            self.received += count

    def commit(self, index):
        # Called only after data fsync. Crash before this commit merely replays a chunk.
        with self.lock:
            updated = self.checkpoint_value()
            updated["completed"] = sorted(self.completed | {index})
            atomic_json(self.checkpoint, updated)
            self.completed.add(index)
            self.active.pop(index, None)

    def report(self, force=False):
        with self.lock:
            checking = self.state == "checking MD5"
            saved = self.file.size if self.state == "OK" or checking else self.saved_bytes()
            active = {str(index): dict(row) for index, row in self.active.items()}
            downloaded = min(self.file.size, saved + sum(row["bytes"] for row in active.values()))
            now = time.monotonic()
            elapsed = max(0.001, now - self.started)
            rate = self.received / elapsed
            download_eta = max(0, self.file.size - downloaded) / rate if rate else None
            verification_rate = 0
            if self.verification_started is not None:
                end = self.verification_finished if self.verification_finished is not None else now
                verification_elapsed = max(0.001, end - self.verification_started)
                verification_rate = self.verified_bytes / verification_elapsed
            verification_eta = (max(0, self.file.size - self.verified_bytes) / verification_rate
                                if verification_rate else None)
            phase_bytes = self.verified_bytes if checking else downloaded
            phase_rate = verification_rate if checking else rate
            eta = verification_eta if checking else download_eta
            report = {"updated_utc": datetime.now(timezone.utc).isoformat(),
                      "archive": self.file.identity(), "state": self.state,
                      "downloaded_bytes": downloaded, "saved_bytes": saved,
                      "completed_segments": len(self.completed), "total_segments": self.count,
                      "verified_bytes": self.verified_bytes, "bytes_per_second": rate,
                      "verification_bytes_per_second": verification_rate,
                      "verification_eta_seconds": verification_eta, "eta_seconds": eta,
                      "active": active, "errors": list(self.errors)}
        atomic_json(self.destination / "download-status.json", report)
        if not force and time.monotonic() - self.last_print < 10:
            return
        self.last_print = time.monotonic()
        print(f"\n{report['state']} | {phase_bytes / self.file.size * 100:.2f}% | "
              f"{human(phase_bytes)} / {human(self.file.size)} | {human(phase_rate)}/s | "
              f"ETA {format_eta(eta)}", flush=True)
        if not checking:
            print(f"Saved segments: {report['completed_segments']}/{self.count}", flush=True)
        for index, row in active.items():
            print(f"  Segment {int(index) + 1}: {row['state']} | {human(row['bytes'])} | {row['detail']}", flush=True)
        for error in report["errors"]:
            print(f"  ERROR: {error}", flush=True)


def transfer_segment(session, index, stop, timeout):
    start, end = session.bounds(index)
    session.active_update(index, bytes=0, state="connecting", detail="")
    with request(session.file.url, timeout, {"Range": f"bytes={start}-{end - 1}"}) as response:
        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
        if (response.status != 206 or not match
                or tuple(map(int, match.groups())) != (start, end - 1, session.file.size)):
            raise InvalidDownload("The server did not honor the requested byte range; the response will not be written.")
        if response.headers.get("Content-Encoding", "identity") != "identity":
            raise InvalidDownload("HTTP-compressed response; the byte range cannot be used.")
        length = response.headers.get("Content-Length")
        if length is not None and int(length) != end - start:
            raise InvalidDownload("Content-Length does not match the requested segment.")
        session.active_update(index, state="downloading")
        with session.part.open("r+b", buffering=0) as stream:
            stream.seek(start)
            remaining = end - start
            synced = 0
            try:
                while remaining:
                    if stop.is_set():
                        raise Stopped()
                    data = response.read(min(MIB, remaining))
                    if not data:
                        raise ConnectionError("Connection closed before the segment finished")
                    written = stream.write(data)
                    if written != len(data):
                        raise OSError("Incomplete disk write")
                    session.advance(index, written)
                    remaining -= written
                    synced += written
                    if synced >= 8 * MIB:
                        os.fsync(stream.fileno())
                        synced = 0
            finally:
                os.fsync(stream.fileno())
    session.commit(index)


def worker(session, pending, stop, timeout, retries):
    while not stop.is_set():
        try:
            index = pending.get_nowait()
        except queue.Empty:
            return
        try:
            attempt = 0
            while True:
                if stop.is_set():
                    raise Stopped()
                try:
                    transfer_segment(session, index, stop, timeout)
                    break
                except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
                    delay = retry_delay(exc, attempt + 1)
                    if isinstance(exc, urllib.error.HTTPError):
                        exc.close()
                        if exc.code not in (408, 429, 500, 502, 503, 504):
                            raise
                    if isinstance(exc, OSError) and exc.errno in (13, 28):
                        raise
                    if retries >= 0 and attempt >= retries:
                        raise
                    attempt += 1
                    session.active_update(index, bytes=0, state="retrying", detail=f"{exc}; waiting {delay:.0f}s")
                    if stop.wait(delay):
                        raise Stopped()
        except Stopped:
            session.active_update(index, bytes=0, state="stopped", detail="This segment will restart on the next run.")
            return
        except Exception as exc:
            with session.lock:
                session.errors.append(f"Segment {index + 1}: {exc}")
                session.active.pop(index, None)
            # Avoid thousands of queued requests after a server-wide failure.
            stop.set()
            return
        finally:
            pending.task_done()


def verify(session, path, stop):
    if path.stat().st_size != session.file.size:
        raise InvalidDownload("Incorrect final file size; the file has been preserved.")
    with session.lock:
        session.state = "checking MD5"
        session.verified_bytes = 0
        session.verification_started = time.monotonic()
        session.verification_finished = None
    digest = hashlib.md5(usedforsecurity=False)
    try:
        with path.open("rb") as stream:
            while True:
                if stop.is_set():
                    raise Stopped()
                data = stream.read(4 * MIB)
                if not data:
                    break
                digest.update(data)
                with session.lock:
                    session.verified_bytes += len(data)
    finally:
        with session.lock:
            session.verification_finished = time.monotonic()
    if digest.hexdigest() != session.file.md5:
        instruction = ("move the .part and .part.json files elsewhere" if path == session.part else "move the final archive elsewhere")
        raise InvalidDownload(f"MD5 mismatch for {path.name}. File preserved; {instruction} to download it again.")


def run_session(session, stop, jobs, timeout, retries):
    try:
        if session.final.exists():
            verify(session, session.final, stop)
        else:
            session.prepare()
            remaining = session.file.size - session.saved_bytes()
            if shutil.disk_usage(session.destination).free < remaining + 16 * MIB:
                raise RuntimeError(f"Not enough disk space: approximately this much more is required: {human(remaining)}.")
            pending = queue.Queue()
            for index in range(session.count):
                if index not in session.completed:
                    pending.put(index)
            session.state = "downloading"
            with ThreadPoolExecutor(max_workers=jobs) as pool:
                futures = [pool.submit(worker, session, pending, stop, timeout, retries) for _ in range(jobs)]
                for future in futures:
                    future.result()
            if session.errors:
                session.state = "ERROR"
                return 1
            if stop.is_set():
                raise Stopped()
            if len(session.completed) != session.count:
                raise InvalidDownload("Some segments are incomplete. Resume using the same command.")
            verify(session, session.part, stop)
            if stop.is_set():
                raise Stopped()
            session.part.replace(session.final)
            session.checkpoint.unlink(missing_ok=True)
        session.state = "OK"
        return 0
    except Stopped:
        session.state = "stopped"
        return 130
    except Exception as exc:
        session.errors.append(str(exc))
        session.state = "ERROR"
        stop.set()
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=Path(__file__).resolve().parent / "data" / "OmniWarsaw-lidar")
    parser.add_argument("--item", default="OmniWarsaw-lidar")
    parser.add_argument("--file", default="warszawa.zip")
    parser.add_argument("--jobs", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--retries", type=int, default=8, help="Retries per segment; -1 = unlimited")
    parser.add_argument("--list", action="store_true", help="Show metadata without downloading the archive")
    parser.add_argument("--status", action="store_true", help="Show the latest local snapshot without network access")
    args = parser.parse_args(argv)
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+", args.item) or args.item in (".", "..")
            or not safe_filename(args.file) or args.timeout <= 0 or args.retries < -1):
        parser.error("Invalid item or filename, nonpositive timeout, or retries < -1.")
    destination = args.destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()

    def interrupt(signum, frame):
        if not stop.is_set():
            print("\nStop requested; preserving saved segments...", flush=True)
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupt)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, interrupt)
    if args.status:
        print(json.dumps(read_json(destination / "download-status.json"), indent=2, ensure_ascii=False))
        print("Saved snapshot; the .part.json checkpoint determines which segments will resume.")
        return 0
    with destination_lock(destination):
        print(f"Destination: {destination}\nReading Internet Archive metadata...", flush=True)
        file = load_archive(args.item, args.file, destination, args.timeout, stop)
        print(f"{file.name}: {file.size:,} bytes ({human(file.size)}) | MD5 {file.md5}\n{file.url}", flush=True)
        if args.list:
            return 0
        print(f"{args.jobs} connections; {human(CHUNK_SIZE)} segments. Press Ctrl+C to stop.\n"
              "Keep .part and .part.json. The same command resumes incomplete segments.\n"
              "Progress every 10s; download-status.json every 1s. OK = MD5 verified.", flush=True)
        session = Session(file, destination)
        with ThreadPoolExecutor(max_workers=1) as coordinator:
            future = coordinator.submit(run_session, session, stop, args.jobs, args.timeout, args.retries)
            try:
                while not future.done():
                    session.report()
                    time.sleep(1)
            finally:
                if not future.done():
                    stop.set()
                result = future.result()
                session.report(force=True)
        if result == 0:
            print("Archive downloaded and MD5 verified.", flush=True)
        else:
            print("Download incomplete; files have been preserved. Run the same command again.", flush=True)
        return result


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Stopped:
        sys.exit(130)
    except (Exception, KeyboardInterrupt) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
