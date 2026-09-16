"""Shared assertions used by more than one test module."""

from pathlib import Path


def assert_intact_jpeg(path: Path) -> None:
    # Seeks rather than reading the whole file: the fixtures are 1-2 MB scans,
    # so the suite would otherwise slurp ~9 MB to inspect five bytes.
    with path.open("rb") as file:
        assert file.read(3) == b"\xff\xd8\xff", f"{path.name} is not a JPEG"
        file.seek(-2, 2)
        assert file.read() == b"\xff\xd9", f"{path.name} is truncated"
