"""On-demand local scans. A later Drive adapter can implement get_scan(ref)."""

import logging
import os
import tempfile
from pathlib import Path
from threading import Lock
from typing import Protocol

from pypdf import PageObject, PdfReader
from pypdf.errors import PyPdfError
from pypdf.generic import ContentStream

from survey.records import Reference, ReviewError, digest
from survey.segmentation.pdf_pages import extract_image

log = logging.getLogger(__name__)


class ScanSource(Protocol):
    def probe(self, ref: Reference) -> None: ...

    def get_scan(self, ref: Reference) -> Path: ...


class LocalScanSource:
    def __init__(self, root: Path, cache: Path):
        self.root = root.resolve()
        self.cache = cache.resolve()
        self.lock = Lock()
        self.metadata = {}
        self.render_errors = {}

    def source(self, ref: Reference) -> tuple[Path, str]:
        pdf = (self.root / ref.region / ref.pdf).resolve()
        if not pdf.is_relative_to(self.root / ref.region):
            raise ReviewError("invalid_scan_path", "Scan path escapes its region")
        if not pdf.is_file():
            raise ReviewError("missing_scan", "Referenced PDF is missing", 404)
        try:
            stat = pdf.stat()
        except OSError as error:
            raise ReviewError(
                "unreadable_scan", "Cannot read original PDF", 404
            ) from error
        fingerprint = digest(
            f"{pdf}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}".encode()
        )
        return pdf, fingerprint

    def revision(self, region: str, pdf: str):
        """Cheap invalidation token for cached batch availability."""
        try:
            _, fingerprint = self.source(Reference(region, pdf, 1, "/"))
        except ReviewError:
            fingerprint = None
        return fingerprint, len(self.render_errors)

    @staticmethod
    def has_image(container, reader, seen=None):
        """Inspect resources/content without decoding compressed image pixels."""
        seen = set() if seen is None else seen
        if id(container) in seen:
            return False
        seen.add(id(container))
        resources = (
            container.get("/Resources", {}).get_object()
            if "/Resources" in container
            else {}
        )
        objects = resources.get("/XObject", {})
        if hasattr(objects, "get_object"):
            objects = objects.get_object()
        for reference in objects.values():
            obj = reference.get_object()
            if obj.get("/Subtype") == "/Image":
                return True
            if obj.get("/Subtype") == "/Form" and LocalScanSource.has_image(
                obj, reader, seen
            ):
                return True
        contents = (
            container.get_contents() if isinstance(container, PageObject) else container
        )
        return bool(contents) and any(
            operator == b"INLINE IMAGE"
            for _, operator in ContentStream(contents, reader).operations
        )

    def probe_locked(self, ref, pdf, fingerprint):
        known = self.metadata.get(pdf)
        if not known or known[0] != fingerprint:
            try:
                with pdf.open("rb") as stream:
                    reader = PdfReader(stream)
                    pages = len(reader.pages)
                    images = set()
                    for number, page in enumerate(reader.pages, 1):
                        try:
                            if self.has_image(page, reader):
                                images.add(number)
                        except (
                            PyPdfError,
                            ValueError,
                            TypeError,
                            KeyError,
                            AttributeError,
                        ) as error:
                            # One malformed page must not hide other valid cards.
                            log.warning(
                                "Invalid image metadata on PDF page %s (%s)",
                                number,
                                type(error).__name__,
                            )
                known = (fingerprint, pages, images)
                self.metadata[pdf] = known
            except Exception as error:
                raise ReviewError(
                    "unreadable_scan", "Original PDF is unreadable", 404
                ) from error
        key = digest(f"{fingerprint}:{ref.page}".encode())
        if ref.page > known[1] or ref.page not in known[2] or key in self.render_errors:
            raise ReviewError(
                "unreadable_scan",
                "Original PDF page is out of bounds, unreadable, or has no scan image",
                404,
            )
        return key

    def probe(self, ref: Reference) -> None:
        pdf, fingerprint = self.source(ref)
        with self.lock:
            self.probe_locked(ref, pdf, fingerprint)

    def get_scan(self, ref: Reference) -> Path:
        pdf, fingerprint = self.source(ref)
        with self.lock:
            tmp = None
            try:
                key = self.probe_locked(ref, pdf, fingerprint)
                target = self.cache / f"{key}.png"
                if target.is_file():
                    return target
                self.cache.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    dir=self.cache, suffix=".png", delete=False
                ) as stream:
                    tmp = Path(stream.name)
                try:
                    extract_image(pdf, ref.page, tmp)
                except Exception:
                    self.render_errors[key] = True
                    raise
                os.replace(tmp, target)
                return target
            except ReviewError:
                raise
            except Exception as error:
                raise ReviewError(
                    "unreadable_scan",
                    "Original PDF page is out of bounds, unreadable, or has no scan image",
                    404,
                ) from error
            finally:
                if tmp:
                    tmp.unlink(missing_ok=True)
