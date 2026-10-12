"""On-demand local scans. A later Drive adapter can implement get_scan(ref)."""

import os
import tempfile
from pathlib import Path
from threading import Lock
from typing import Protocol

from survey.records import Reference, ReviewError, digest
from survey.segmentation.pdf_pages import extract_image


class ScanSource(Protocol):
    def get_scan(self, ref: Reference) -> Path: ...


class LocalScanSource:
    def __init__(self, root: Path, cache: Path):
        self.root = root.resolve()
        self.cache = cache.resolve()
        self.lock = Lock()

    def get_scan(self, ref: Reference) -> Path:
        pdf = (self.root / ref.region / ref.pdf).resolve()
        if not pdf.is_relative_to(self.root / ref.region):
            raise ReviewError("invalid_scan_path", "Scan path escapes its region")
        if not pdf.is_file():
            raise ReviewError("missing_scan", "Referenced PDF is missing", 404)
        with self.lock:
            tmp = None
            try:
                stat = pdf.stat()
                key = digest(
                    f"{pdf}:{ref.page}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}".encode()
                )
                target = self.cache / f"{key}.png"
                if target.is_file():
                    return target
                self.cache.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    dir=self.cache, suffix=".png", delete=False
                ) as stream:
                    tmp = Path(stream.name)
                extract_image(pdf, ref.page, tmp)
                os.replace(tmp, target)
                return target
            except Exception as error:
                raise ReviewError(
                    "unreadable_scan",
                    "Original PDF page is out of bounds, unreadable, or has no scan image",
                    404,
                ) from error
            finally:
                if tmp:
                    tmp.unlink(missing_ok=True)
