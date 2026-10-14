"""Public Drive scans: explicit transfers, pinned source bytes, local rendering."""

import hashlib
import json
import os
import tempfile
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

    def local_ready(self, batch):
        target = self.target(batch)
        if not target.is_file():
            return False
        stat = target.stat()
        signature = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        if stat.st_size != batch["size"]:
            return False
        if self.verified.get(target) != signature:
            with target.open("rb") as stream:
                if hashlib.file_digest(stream, "md5").hexdigest() != batch["md5"]:
                    return False
            self.verified[target] = signature
        return True

    def status(self, region):
        batch = self.batch(region)
        with self.lock:
            job = dict(self.jobs.get(region, {}))
            active = self.active
        # Hash outside the job lock so polling does not block transfer progress.
        ready = self.local_ready(batch)
        state = job.get("state", "missing")
        if state == "ready" and not ready:
            state = "missing"
        if ready and state not in {"downloading", "importing", "validating"}:
            state = "ready"
        return {
            "region": region,
            "pdf": batch["pdf"],
            "size": batch["size"],
            "drive_url": f"https://drive.google.com/file/d/{batch['file_id']}/view"
            + (
                "?" + urlencode({"resourcekey": batch["resource_key"]})
                if batch.get("resource_key")
                else ""
            ),
            "state": state,
            "downloaded": job.get("downloaded", batch["size"] if ready else 0),
            "error": job.get("error"),
            "automatic_download": self.enabled,
            "active_region": active,
            "local_file_exists": self.target(batch).exists(),
        }

    def claim(self, region, state):
        self.batch(region)
        with self.lock:
            if self.active:
                raise ReviewError(
                    "download_busy",
                    f"A scan transfer is already running for {self.active}",
                    409,
                )
            self.active = region
            self.cancel_event = Event()
            self.jobs[region] = {"state": state, "downloaded": 0}

    def start(self, region):
        batch = self.batch(region)
        with self.lock:
            if self.active == region:
                return self.status(region)
        if self.local_ready(batch):
            return self.status(region)
        if not self.enabled:
            raise ReviewError(
                "drive_not_configured",
                "Use Open in Drive and import, or configure a Drive API key",
                503,
            )
        with self.lock:
            if self.active == region:
                return self.status(region)
            self.claim(region, "downloading")
            self.worker = Thread(
                target=self.download, args=(region,), name="scan-download", daemon=True
            )
            self.worker.start()
        return self.status(region)

    def check_remote(self, batch):
        metadata = self.client.metadata(batch, self.cancel_event)
        if (
            metadata.get("name") != batch["pdf"]
            or metadata.get("mimeType") != "application/pdf"
            or str(metadata.get("size")) != str(batch["size"])
            or metadata.get("md5Checksum") != batch["md5"]
        ):
            raise ReviewError(
                "source_changed",
                "The Drive PDF differs from the approved source. Ask the team to reconcile the scan catalogue.",
                409,
            )
        if metadata.get("capabilities", {}).get("canDownload") is False:
            raise ReviewError(
                "download_restricted", "Drive has disabled downloading this PDF", 403
            )

    def download(self, region):
        try:
            batch = self.batch(region)
            self.check_remote(batch)
            with self.staging(batch) as (path, stream):
                for chunk in self.client.chunks(batch, self.cancel_event):
                    self.write_chunk(region, stream, chunk)
                self.finish_stream(stream)
                self.publish(region, path)
        except Exception as error:  # noqa: BLE001 -- every worker exit must report a terminal state
            self.fail(region, error)
        finally:
            self.release(region)

    def staging(self, batch):
        from contextlib import contextmanager

        @contextmanager
        def staged():
            target = self.target(batch)
            if target.exists():
                raise ReviewError(
                    "scan_exists",
                    "A different PDF already exists. Move it aside before importing or downloading.",
                    409,
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

        return staged()

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
            if job["downloaded"] + len(chunk) > self.batches[region]["size"]:
                raise ReviewError(
                    "scan_size_mismatch", "PDF is larger than the approved source"
                )
            stream.write(chunk)
            job["downloaded"] += len(chunk)

    def publish(self, region, path):
        batch = self.batch(region)
        with self.lock:
            self.jobs[region]["state"] = "validating"
        if path.stat().st_size != batch["size"]:
            raise ReviewError(
                "scan_size_mismatch", "Incomplete PDF. Retry or download manually."
            )
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "md5").hexdigest() != batch["md5"]:
                raise ReviewError(
                    "scan_checksum_mismatch",
                    "PDF does not match the approved original source",
                )
        try:
            reader = PdfReader(path)
            if reader.is_encrypted:
                raise ValueError("encrypted PDF")
            count = len(reader.pages)
        except (PyPdfError, OSError, ValueError, TypeError, KeyError):
            raise ReviewError(
                "unreadable_scan", "Downloaded file is not a readable PDF"
            ) from None
        with self.service.store.lock:
            records = self.service.store.regions[region][0]
            pages = [
                card["page"]
                for record in records
                for card in self.service.physical_cards(record)
            ]
            pages.extend(
                ref.page for ref in self.service.region_references.get(region, [])
            )
            pages.extend(
                ref.front_page
                for ref in self.service.region_references.get(region, [])
                if ref.front_page is not None
            )
        if not pages or any(
            not isinstance(p, int) or not 1 <= p <= count for p in pages
        ):
            raise ReviewError(
                "scan_page_mismatch", "Review records reference pages outside this PDF"
            )
        with self.lock:
            if self.cancel_event.is_set():
                raise ReviewError("download_cancelled", "Transfer cancelled")
            # Atomic creation, never overwriting a file that appeared during transfer.
            try:
                os.link(path, self.target(batch))
            except FileExistsError:
                raise ReviewError(
                    "scan_exists",
                    "A PDF appeared during transfer; it was not overwritten",
                    409,
                ) from None
            self.jobs[region]["state"] = "ready"
        with self.service.store.lock:
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
