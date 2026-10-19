"""Public Drive scans: current-source transfer integrity and local rendering."""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from threading import Event, RLock, Thread
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from survey.records import REGION, ReviewError, safe_pdf

CATALOGUE = Path(__file__).with_name("drive-catalogue.json")
CHUNK = 1024 * 1024
MAX_IMPORT_BYTES = 1024**3


class DriveClient:
    def __init__(self, key):
        self.key = key

    def request(self, path, params, resource_key=None, file_id=None):
        if not self.key:
            raise ReviewError(
                "drive_not_configured",
                "Automatic downloads need a Drive API key. Use Open in Drive and import instead.",
                503,
            )
        headers = {}
        if resource_key:
            headers["X-Goog-Drive-Resource-Keys"] = f"{file_id}/{resource_key}"
        # Never log request URLs: they contain the application key.
        return Request(
            "https://www.googleapis.com/drive/v3/"
            + path
            + "?"
            + urlencode({**params, "key": self.key}),
            headers=headers,
        )

    def open(self, request, cancel):
        for attempt in range(3):
            if cancel.is_set():
                raise ReviewError("download_cancelled", "Download cancelled")
            try:
                return urlopen(request, timeout=20)
            except HTTPError as error:
                retry = error.code in {429, 500, 502, 503, 504}
                if error.code == 403:
                    try:
                        reasons = (
                            json.loads(error.read()).get("error", {}).get("errors", [])
                        )
                        retry = any(
                            e.get("reason")
                            in {"rateLimitExceeded", "userRateLimitExceeded"}
                            for e in reasons
                        )
                    except (ValueError, OSError):
                        pass
                if not retry:
                    raise ReviewError(
                        "drive_access_failed",
                        "Drive access failed. Check public sharing and download permissions, or use the manual download option.",
                        502,
                    ) from None
            except (URLError, TimeoutError, OSError):
                pass
            if attempt == 2:
                raise ReviewError(
                    "drive_unavailable",
                    "Drive is not responding. Retry or download manually.",
                    502,
                )
            cancel.wait(2**attempt)

    def metadata(self, batch, cancel):
        request = self.request(
            f"files/{batch['file_id']}",
            {"fields": "id,name,mimeType,size,md5Checksum,capabilities(canDownload)"},
            batch.get("resource_key"),
            batch["file_id"],
        )
        with self.open(request, cancel) as response:
            return json.load(response)

    def chunks(self, batch, cancel):
        request = self.request(
            f"files/{batch['file_id']}",
            {"alt": "media"},
            batch.get("resource_key"),
            batch["file_id"],
        )
        with self.open(request, cancel) as response:
            while chunk := response.read(CHUNK):
                if cancel.is_set():
                    raise ReviewError("download_cancelled", "Download cancelled")
                yield chunk


class BatchDownloads:
    def __init__(self, service, key=None, catalogue=CATALOGUE, *, root=None):
        self.service = service
        self.root = (root if root is not None else service.scans.root).resolve()
        raw = json.loads(Path(catalogue).read_text(encoding="utf-8"))
        if raw.get("version") != 1:
            raise ReviewError("invalid_catalogue", "Unsupported scan catalogue version")
        self.batches = {}
        for batch in raw["batches"]:
            region = batch["region"]
            if (
                not REGION.fullmatch(region)
                or not safe_pdf(batch["pdf"])
                or not isinstance(batch["size"], int)
                or batch["size"] <= 0
                or len(batch["md5"]) != 32
                or not all(c in "0123456789abcdef" for c in batch["md5"])
                or not all(c.isalnum() or c in "_-" for c in batch["file_id"])
                or not batch["file_id"]
                or region in self.batches
            ):
                raise ReviewError(
                    "invalid_catalogue", "Invalid or duplicate scan catalogue entry"
                )
            self.batches[region] = batch
        self.client = DriveClient(key)
        self.enabled = bool(key)
        self.lock = RLock()
        self.cancel_event = Event()
        self.worker = None
        self.active = None
        self.jobs = {}
        self.verified = {}

    def batch(self, region):
        batch = self.batches.get(region)
        with self.service.store.lock:
            entries = self.service.store.regions.get(region)
            pdfs = (
                {
                    card["image"]
                    for record in entries[0]
                    for card in self.service.physical_cards(record)
                }
                if entries
                else set()
            )
            pdfs.update(
                ref.pdf for ref in self.service.region_references.get(region, [])
            )
        if not batch or pdfs != {batch["pdf"]}:
            raise ReviewError(
                "batch_not_available",
                "No unambiguous Drive PDF matches this region's review records",
                404,
            )
        return batch

    def target(self, batch):
        folder = self.root / batch["region"]
        target = folder / batch["pdf"]
        with self.lock:
            if (
                folder.is_symlink()
                or target.is_symlink()
                or not target.resolve().is_relative_to(self.root)
            ):
                raise ReviewError(
                    "invalid_scan_path",
                    "Scan destination must stay inside its real region folder",
                )
        return target

    @staticmethod
    def signature(path):
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        return (
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )

    def required_pages(self, region):
        with self.service.store.lock:
            records = self.service.store.regions[region][0]
            pages = [
                card.get("page")
                for record in records
                for card in self.service.physical_cards(record)
            ]
            refs = self.service.region_references.get(region, [])
            pages.extend(ref.page for ref in refs)
            pages.extend(ref.front_page for ref in refs if ref.front_page is not None)
        return pages

    @staticmethod
    def page_count(path):
        try:
            with path.open("rb") as stream:
                reader = PdfReader(stream)
                if reader.is_encrypted:
                    raise ValueError("encrypted PDF")
                return len(reader.pages)
        except (PyPdfError, OSError, ValueError, TypeError, KeyError):
            raise ReviewError("unreadable_scan", "File is not a readable PDF") from None

    def check_pages(self, region, count):
        pages = self.required_pages(region)
        if not pages or any(
            not isinstance(p, int) or not 1 <= p <= count for p in pages
        ):
            raise ReviewError(
                "scan_page_mismatch", "Review records reference pages outside this PDF"
            )

    def local_ready(self, batch):
        target = self.target(batch)
        if not target.is_file():
            return False
        signature = self.signature(target)
        known = self.verified.get(target)
        if not known or known[0] != signature:
            try:
                count = self.page_count(target)
            except ReviewError:
                count = None
            if self.signature(target) != signature:
                return False
            known = signature, count
            self.verified[target] = known
        if known[1] is None:
            return False
        try:
            self.check_pages(batch["region"], known[1])
        except ReviewError:
            return False
        return True

    def status(self, region):
        batch = self.batch(region)
        with self.lock:
            job = dict(self.jobs.get(region, {}))
            active = self.active
        # Only reparse changed files; polling never hashes PDFs or contacts Drive.
        ready = self.local_ready(batch)
        signature = self.signature(self.target(batch))
        ready = ready and signature is not None
        state = job.get("state", "missing")
        if state == "ready" and not ready:
            state = "missing"
        if ready and state in {"missing", "ready"}:
            state = "ready"
        transferring = state in {"downloading", "importing", "validating"}
        size = (
            signature[2]
            if ready and not transferring
            else job.get("size") or batch["size"]
        )
        return {
            "region": region,
            "pdf": batch["pdf"],
            "size": size,
            "drive_url": f"https://drive.google.com/file/d/{batch['file_id']}/view"
            + (
                "?" + urlencode({"resourcekey": batch["resource_key"]})
                if batch.get("resource_key")
                else ""
            ),
            "state": state,
            "downloaded": size
            if ready and not transferring
            else job.get("downloaded", 0),
            "error": job.get("error"),
            "automatic_download": self.enabled,
            "active_region": active,
            "local_file_exists": self.target(batch).exists(),
            "local_ready": ready,
        }

    @staticmethod
    def import_size(value):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,20}", value):
            raise ReviewError("invalid_scan_size", "Supply the PDF upload size")
        size = int(value)
        if not 0 < size <= MAX_IMPORT_BYTES:
            raise ReviewError(
                "invalid_scan_size", "Import a PDF between 1 byte and 1 GiB"
            )
        return size

    def claim(self, region, state, size=None):
        batch = self.batch(region)
        with self.lock:
            if self.active:
                raise ReviewError(
                    "download_busy",
                    f"A scan transfer is already running for {self.active}",
                    409,
                )
            if self.target(batch).exists():
                raise ReviewError(
                    "scan_exists",
                    "A PDF already exists for this region. Move it out of the scan folder before downloading or importing. Use Open scan folder to find it.",
                    409,
                )
            self.active = region
            self.cancel_event = Event()
            self.jobs[region] = {
                "state": state,
                "downloaded": 0,
                "size": size,
                "md5": None,
            }

    def open_folder(self, region):
        # Only open a catalogue-derived folder inside the configured scan root.
        folder = self.target(self.batch(region)).parent
        if not folder.is_dir():
            raise ReviewError("missing_scan_folder", "Scan folder does not exist", 404)
        try:
            if sys.platform == "win32":
                os.startfile(str(folder))
            else:
                command = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.run([command, str(folder)], check=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            raise ReviewError(
                "scan_folder_open_failed",
                f"Could not open the scan folder. Open it manually: {folder}",
                500,
            ) from None
        return {"opened": True}

    def start(self, region):
        self.batch(region)
        with self.lock:
            running = self.active == region
        if running:
            return self.status(region)
        if not self.enabled:
            raise ReviewError(
                "drive_not_configured",
                "Use Open in Drive and import, or configure a Drive API key",
                503,
            )
        try:
            self.claim(region, "downloading")
        except ReviewError:
            with self.lock:
                running = self.active == region
            if not running:
                raise
            return self.status(region)
        with self.lock:
            self.worker = Thread(
                target=self.download, args=(region,), name="scan-download", daemon=True
            )
            self.worker.start()
        return self.status(region)

    def check_remote(self, batch):
        metadata = self.client.metadata(batch, self.cancel_event)
        if (
            metadata.get("mimeType") != "application/pdf"
            or not re.fullmatch(r"[0-9]{1,20}", str(metadata.get("size", "")))
            or int(metadata["size"]) <= 0
            or not re.fullmatch(r"[0-9a-f]{32}", str(metadata.get("md5Checksum", "")))
        ):
            raise ReviewError(
                "invalid_drive_metadata",
                "Drive did not return valid PDF size/checksum metadata",
                502,
            )
        if metadata.get("capabilities", {}).get("canDownload") is False:
            raise ReviewError(
                "download_restricted", "Drive has disabled downloading this PDF", 403
            )
        return {"size": int(metadata["size"]), "md5": metadata["md5Checksum"]}

    def download(self, region):
        try:
            batch = self.batch(region)
            for attempt in range(2):
                expected = self.check_remote(batch)
                with self.lock:
                    self.jobs[region].update(
                        expected, state="downloading", downloaded=0
                    )
                try:
                    with self.staging(batch) as (path, stream):
                        for chunk in self.client.chunks(batch, self.cancel_event):
                            self.write_chunk(region, stream, chunk)
                        self.finish_stream(stream)
                        if self.check_remote(batch) != expected:
                            raise ReviewError(
                                "source_changed", "Drive changed during transfer", 409
                            )
                        self.publish(region, path)
                    break
                except ReviewError as error:
                    changed = error.code == "source_changed" or (
                        error.code in {"scan_size_mismatch", "scan_checksum_mismatch"}
                        and self.check_remote(batch) != expected
                    )
                    if not changed:
                        raise
                    if attempt == 1:
                        raise ReviewError(
                            "source_changed",
                            "Drive keeps changing during transfer. Retry the download.",
                            409,
                        ) from None
        except Exception as error:  # noqa: BLE001 -- every worker exit must report a terminal state
            self.fail(region, error)
        finally:
            self.release(region)

    @contextmanager
    def staging(self, batch):
        # Windows resolve() can retain a device prefix if a missing parent
        # appears midway through resolution. Keep status path checks from
        # racing directory creation and falsely rejecting an in-root path.
        with self.lock:
            target = self.target(batch)
            if target.exists() and not target.is_file():
                raise ReviewError(
                    "invalid_scan_path", "Scan destination must be a regular file"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            self.target(batch)
        path = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=target.parent, prefix=".scan-", suffix=".part", delete=False
            ) as stream:
                path = Path(stream.name)
                yield path, stream
        finally:
            if path:
                path.unlink(missing_ok=True)

    @staticmethod
    def finish_stream(stream):
        stream.flush()
        os.fsync(stream.fileno())
        stream.close()

    def write_chunk(self, region, stream, chunk):
        if self.cancel_event.is_set():
            raise ReviewError("download_cancelled", "Transfer cancelled")
        with self.lock:
            job = self.jobs[region]
            limit = job["size"] if job["size"] is not None else MAX_IMPORT_BYTES
            if job["downloaded"] + len(chunk) > limit:
                raise ReviewError(
                    "scan_size_mismatch", "PDF exceeds the declared transfer size"
                )
            stream.write(chunk)
            job["downloaded"] += len(chunk)

    def publish(self, region, path):
        batch = self.batch(region)
        with self.lock:
            self.jobs[region]["state"] = "validating"
            job = dict(self.jobs[region])
        if job["size"] is None or path.stat().st_size != job["size"]:
            raise ReviewError(
                "scan_size_mismatch", "Incomplete PDF. Retry or download manually."
            )
        if job["md5"] is not None:
            with path.open("rb") as stream:
                checksum = hashlib.file_digest(stream, "md5").hexdigest()
            if checksum != job["md5"]:
                raise ReviewError(
                    "scan_checksum_mismatch",
                    "Downloaded bytes do not match Drive. Retry the download.",
                )
        self.check_pages(region, self.page_count(path))
        with self.service.store.lock, self.lock:
            if self.cancel_event.is_set():
                raise ReviewError("download_cancelled", "Transfer cancelled")
            target = self.target(batch)
            try:
                os.link(path, target)
            except FileExistsError:
                raise ReviewError(
                    "scan_exists",
                    "A PDF appeared during transfer; it was not overwritten. Move it out of the scan folder before retrying.",
                    409,
                ) from None
            self.jobs[region]["state"] = "ready"
            self.verified.pop(target, None)
            self.service.rebuild_progress({region})

    def fail(self, region, error):
        with self.lock:
            cancelled = self.cancel_event.is_set() or (
                isinstance(error, ReviewError) and error.code == "download_cancelled"
            )
            self.jobs[region].update(
                state="cancelled" if cancelled else "failed",
                error={
                    "code": "download_cancelled"
                    if cancelled
                    else getattr(error, "code", "scan_transfer_failed"),
                    "message": "Transfer cancelled"
                    if cancelled
                    else (
                        str(error)
                        if isinstance(error, ReviewError)
                        else "Transfer failed. Check connection, disk space and folder permissions; then retry."
                    ),
                },
            )

    def release(self, region):
        with self.lock:
            if self.active == region:
                self.active = None

    def cancel(self, region):
        with self.lock:
            if self.active == region:
                self.cancel_event.set()
        return self.status(region)

    def close(self):
        self.cancel_event.set()
        if self.worker:
            self.worker.join(timeout=25)
