"""Local HTTP integration tests; no Internet or full dataset downloads."""

from contextlib import contextmanager
from email.message import Message
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import download_archive_omniwarsaw as dl


DATA = bytes(range(256)) * 32768
TEST_CHUNK = 512 * 1024


@contextmanager
def server(mode="range", slow=False):
    ranges = []
    counts = {}
    active = [0, 0]
    guard = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            start, end = map(int, self.headers["Range"][6:].split("-"))
            with guard:
                ranges.append((start, end))
                counts[start] = counts.get(start, 0) + 1
                first = counts[start] == 1
                active[0] += 1
                active[1] = max(active)
            try:
                if mode in ("rate-limit", "unavailable") and first:
                    self.send_response(429 if mode == "rate-limit" else 503)
                    self.send_header("Retry-After", "0")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if mode == "missing":
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200 if mode == "ignore-range" else 206)
                reported = start + 1 if mode == "wrong-range" else start
                self.send_header("Content-Range", f"bytes {reported}-{end}/{len(DATA)}")
                self.send_header("Content-Length", str(end - start + 1))
                self.end_headers()
                actual_end = start + 64 * 1024 if mode == "drop-once" and first else end + 1
                for offset in range(start, actual_end, 64 * 1024):
                    block = DATA[offset:min(offset + 64 * 1024, actual_end)]
                    if mode == "corrupt":
                        block = b"X" * len(block)
                    self.wfile.write(block)
                    self.wfile.flush()
                    if slow:
                        time.sleep(0.01)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                with guard:
                    active[0] -= 1

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}/warszawa.zip", ranges, active
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


class DownloaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.destination = Path(self.temp.name)
        self.stop = threading.Event()

    def tearDown(self):
        self.temp.cleanup()

    def file(self, url):
        return dl.Archive("OmniWarsaw-lidar", "warszawa.zip", len(DATA),
                          hashlib.md5(DATA).hexdigest(), url)

    def session(self, url):
        return dl.Session(self.file(url), self.destination, chunk_size=TEST_CHUNK)

    def test_parallel_download_and_final_checksum(self):
        with server(slow=True) as (url, ranges, active):
            session = self.session(url)
            self.assertEqual(dl.run_session(session, self.stop, 4, 2, 0), 0)
            self.assertEqual(session.final.read_bytes(), DATA)
            self.assertFalse(session.part.exists())
            self.assertFalse(session.checkpoint.exists())
            self.assertGreaterEqual(active[1], 2)
            self.assertEqual(len(ranges), session.count)
            with patch("builtins.print"):
                session.report(force=True)
            report = dl.read_json(self.destination / "download-status.json")
            self.assertEqual(report["state"], "OK")
            self.assertEqual(report["saved_bytes"], len(DATA))

    def test_existing_archive_is_verified_without_requests(self):
        session = self.session("http://127.0.0.1:1/not-needed")
        session.final.write_bytes(DATA)
        self.assertEqual(dl.run_session(session, self.stop, 4, 2, 0), 0)
        self.assertEqual(session.verified_bytes, len(DATA))

    def test_verification_eta_uses_hash_progress_instead_of_completed_download(self):
        session = self.session("http://127.0.0.1:1/not-needed")
        session.state = "checking MD5"
        session.received = session.file.size
        session.started = 0  # A long download must not affect verification speed.
        session.verification_started = 1000
        for verified, now, expected_eta in ((2 * dl.MIB, 1020, 60),
                                            (4 * dl.MIB, 1040, 40),
                                            (6 * dl.MIB, 1060, 20)):
            with self.subTest(verified=verified):
                session.verified_bytes = verified
                with patch.object(dl.time, "monotonic", return_value=now), patch("builtins.print") as output:
                    session.report(force=True)
                report = dl.read_json(self.destination / "download-status.json")
                self.assertEqual(report["downloaded_bytes"], session.file.size)
                self.assertEqual(report["verification_bytes_per_second"], dl.MIB / 10)
                self.assertEqual(report["verification_eta_seconds"], expected_eta)
                self.assertEqual(report["eta_seconds"], expected_eta)
                header = output.call_args_list[0].args[0]
                self.assertIn(f"{verified / session.file.size * 100:.2f}%", header)
                self.assertIn("102.4 KiB/s", header)
                self.assertIn(f"ETA 00:00:{expected_eta:02d}" if expected_eta < 60 else "ETA 00:01:00", header)
                self.assertNotIn("100.00%", header)

    def test_verification_eta_is_unknown_until_hashing_starts(self):
        session = self.session("http://127.0.0.1:1/not-needed")
        session.state = "checking MD5"
        session.received = session.file.size
        session.verification_started = 1000
        with patch.object(dl.time, "monotonic", return_value=1000), patch("builtins.print") as output:
            session.report(force=True)
        report = dl.read_json(self.destination / "download-status.json")
        self.assertIsNone(report["verification_eta_seconds"])
        self.assertIsNone(report["eta_seconds"])
        self.assertEqual(report["verification_bytes_per_second"], 0)
        self.assertIn("checking MD5 | 0.00%", output.call_args_list[0].args[0])
        self.assertIn("ETA --", output.call_args_list[0].args[0])

    def test_verification_timer_starts_with_hashing_and_freezes_on_completion(self):
        session = self.session("http://127.0.0.1:1/not-needed")
        session.final.write_bytes(DATA)
        with patch.object(dl.time, "monotonic", side_effect=[1000, 1004]):
            dl.verify(session, session.final, self.stop)
        with patch.object(dl.time, "monotonic", return_value=6000), patch("builtins.print") as output:
            session.report(force=True)
        report = dl.read_json(self.destination / "download-status.json")
        self.assertEqual(report["verified_bytes"], len(DATA))
        self.assertEqual(report["verification_bytes_per_second"], len(DATA) / 4)
        self.assertEqual(report["verification_eta_seconds"], 0)
        self.assertIn("100.00%", output.call_args_list[0].args[0])
        self.assertIn("ETA 00:00:00", output.call_args_list[0].args[0])

    def test_download_eta_still_uses_download_progress(self):
        session = self.session("http://127.0.0.1:1/not-needed")
        session.state = "downloading"
        session.started = 1000
        session.completed = set(range(session.count // 2))
        session.received = session.file.size // 2
        with patch.object(dl.time, "monotonic", return_value=1020), patch("builtins.print") as output:
            session.report(force=True)
        report = dl.read_json(self.destination / "download-status.json")
        self.assertEqual(report["eta_seconds"], 20)
        self.assertIsNone(report["verification_eta_seconds"])
        self.assertIn("downloading | 50.00%", output.call_args_list[0].args[0])
        self.assertIn("ETA 00:00:20", output.call_args_list[0].args[0])

    def test_main_download_records_final_status(self):
        with server() as (url, _, _):
            with patch.object(dl, "load_archive", return_value=self.file(url)), patch("builtins.print"):
                result = dl.main(["--destination", str(self.destination), "--jobs", "2"])
            self.assertEqual(result, 0)
            self.assertEqual((self.destination / "warszawa.zip").read_bytes(), DATA)
            self.assertEqual(dl.read_json(self.destination / "download-status.json")["state"], "OK")

    def test_completed_segments_survive_process_kill(self):
        with server(slow=True) as (url, ranges, _):
            session = self.session(url)
            code = """
import sys,pathlib,threading
sys.path.insert(0,sys.argv[1])
import download_archive_omniwarsaw as d
f=d.Archive('OmniWarsaw-lidar','warszawa.zip',int(sys.argv[4]),sys.argv[5],sys.argv[3])
s=d.Session(f,pathlib.Path(sys.argv[2]),chunk_size=int(sys.argv[6]))
commit=s.commit
def announce_commit(index):
 commit(index)
 (s.destination/'first-segment-saved').touch()
s.commit=announce_commit
d.run_session(s,threading.Event(),3,2,0)
"""
            process = subprocess.Popen([sys.executable, "-c", code, str(Path(dl.__file__).parent),
                                        str(self.destination), url, str(session.file.size),
                                        session.file.md5, str(TEST_CHUNK)])
            marker = self.destination / "first-segment-saved"
            try:
                deadline = time.monotonic() + 10
                # Avoid holding the checkpoint open during its atomic replacement on Windows.
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.005)
                self.assertTrue(marker.exists())
            finally:
                process.kill()
                process.wait(timeout=5)
            completed = dl.read_json(session.checkpoint)["completed"]
            self.assertLess(len(completed), session.count)
            boundary = len(ranges)
            resumed = self.session(url)
            self.assertEqual(dl.run_session(resumed, self.stop, 2, 2, 0), 0)
            resumed_starts = {start for start, end in ranges[boundary:]}
            self.assertTrue(all(index * TEST_CHUNK not in resumed_starts for index in completed))
            self.assertEqual(resumed.final.read_bytes(), DATA)

    def test_connection_drop_and_temporary_errors_are_retried(self):
        for mode in ("drop-once", "rate-limit", "unavailable"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp, server(mode) as (url, ranges, _):
                session = dl.Session(self.file(url), Path(temp), TEST_CHUNK)
                with patch.object(dl, "retry_delay", return_value=0):
                    self.assertEqual(dl.run_session(session, threading.Event(), 3, 2, 1), 0)
                self.assertEqual(session.final.read_bytes(), DATA)
                self.assertEqual(len(ranges), session.count * 2)

    def test_unlimited_retries_recovers(self):
        with server("unavailable") as (url, ranges, _):
            with patch.object(dl, "retry_delay", return_value=0):
                self.assertEqual(dl.run_session(self.session(url), self.stop, 2, 2, -1), 0)

    def test_wrong_range_and_404_leave_checkpoint_uncommitted(self):
        for mode in ("ignore-range", "wrong-range", "missing"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp, server(mode) as (url, ranges, _):
                session = dl.Session(self.file(url), Path(temp), TEST_CHUNK)
                self.assertEqual(dl.run_session(session, threading.Event(), 1, 2, 8), 1)
                self.assertEqual(dl.read_json(session.checkpoint)["completed"], [])
                self.assertEqual(session.part.stat().st_size, 0)
                self.assertEqual(len(ranges), 1)

    def test_corruption_is_not_promoted_to_final(self):
        with server("corrupt") as (url, _, _):
            session = self.session(url)
            self.assertEqual(dl.run_session(session, self.stop, 3, 2, 0), 1)
            self.assertTrue(session.part.exists())
            self.assertFalse(session.final.exists())
            self.assertIn("MD5 mismatch", session.errors[0])

    def test_no_commit_before_fsync_and_checkpoint_is_durable(self):
        with server() as (url, _, _):
            session = self.session(url)
            session.prepare()
            real_sync = dl.os.fsync
            synced = []
            def record_sync(fd):
                synced.append(fd)
                return real_sync(fd)
            real_commit = session.commit
            def checked_commit(index):
                self.assertTrue(synced)
                real_commit(index)
            with patch.object(dl.os, "fsync", side_effect=record_sync), patch.object(session, "commit", side_effect=checked_commit):
                dl.transfer_segment(session, 0, self.stop, 2)
            self.assertEqual(dl.read_json(session.checkpoint)["completed"], [0])
            reloaded = self.session(url)
            reloaded.prepare()
            self.assertEqual(reloaded.completed, {0})

    def test_metadata_identity_mismatch_preserves_partial(self):
        session = self.session("http://127.0.0.1:1/not-needed")
        session.prepare()
        session.part.write_bytes(b"preserved")
        value = dl.read_json(session.checkpoint)
        value["archive"]["md5"] = "0" * 32
        dl.atomic_json(session.checkpoint, value)
        self.assertEqual(dl.run_session(self.session(session.file.url), self.stop, 1, 2, 0), 1)
        self.assertEqual(session.part.read_bytes(), b"preserved")

    def test_missing_partial_with_completed_checkpoint_is_rejected(self):
        session = self.session("http://127.0.0.1:1/not-needed")
        session.prepare()
        value = dl.read_json(session.checkpoint)
        value["completed"] = [0]
        dl.atomic_json(session.checkpoint, value)
        session.part.unlink()
        with self.assertRaises(dl.InvalidDownload):
            self.session(session.file.url).prepare()

    def test_offline_metadata_falls_back_to_cache(self):
        record = {"metadata": {"identifier": "OmniWarsaw-lidar"}, "files": [
            {"name": "warszawa.zip", "size": str(len(DATA)), "md5": hashlib.md5(DATA).hexdigest()}]}
        dl.atomic_json(self.destination / ".archive-metadata.json", record)
        with patch.object(dl, "request", side_effect=dl.urllib.error.URLError("offline")), \
                patch.object(dl, "retry_delay", return_value=0), patch("builtins.print"):
            file = dl.load_archive("OmniWarsaw-lidar", "warszawa.zip", self.destination, 1, self.stop)
        self.assertEqual(file.size, len(DATA))

    def test_offline_snapshot_via_cli(self):
        value = {"state": "stopped", "saved_bytes": 12345}
        dl.atomic_json(self.destination / "download-status.json", value)
        with patch("builtins.print"), patch.object(dl, "request", side_effect=AssertionError("Network forbidden")):
            self.assertEqual(dl.main(["--destination", str(self.destination), "--status"]), 0)

    def test_stop_during_retry_is_immediate(self):
        session = self.session("http://127.0.0.1:1/not-needed")
        with patch.object(dl, "request", side_effect=dl.urllib.error.URLError("offline")):
            timer = threading.Timer(0.1, self.stop.set)
            timer.start()
            try:
                started = time.monotonic()
                self.assertEqual(dl.run_session(session, self.stop, 2, 1, -1), 130)
                self.assertLess(time.monotonic() - started, 1)
                self.assertTrue(session.part.exists())
            finally:
                timer.cancel()

    def test_destination_lock_blocks_second_process(self):
        code = """
import sys,pathlib
sys.path.insert(0,sys.argv[1])
import download_archive_omniwarsaw as d
with d.destination_lock(pathlib.Path(sys.argv[2])): pass
"""
        with dl.destination_lock(self.destination):
            result = subprocess.run([sys.executable, "-c", code, str(Path(dl.__file__).parent),
                                     str(self.destination)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Another downloader", result.stderr)
        with dl.destination_lock(self.destination):
            pass

    def test_retry_after_honored_and_backoff_stays_bounded(self):
        headers = Message()
        headers["Retry-After"] = "120"
        error = dl.urllib.error.HTTPError("http://test", 429, "Rate limited", headers, None)
        self.assertEqual(dl.retry_delay(error, 1), 120)
        error.close()
        self.assertEqual(dl.retry_delay(ConnectionError(), 1000000), 60)


if __name__ == "__main__":
    unittest.main()
