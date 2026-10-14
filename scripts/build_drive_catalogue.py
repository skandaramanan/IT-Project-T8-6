"""Rebuild pinned public scan metadata after checking the local extraction source.

Requires SURVEY_REVIEW_DRIVE_API_KEY. Never downloads or changes PDFs.
A mismatch aborts the entire build, leaving the existing catalogue unchanged.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
from threading import Event

from survey.cli import load_env
from survey.review.drive import CATALOGUE, DriveClient

ROOT_ID = "1z8_i1IYzUCZYtE5NxB9xQ8kAQ_rh-DMV"


def children(client, folder_id, resource_key=None):
    page_token = None
    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": "nextPageToken,files(id,name,mimeType,size,md5Checksum,resourceKey)",
            "pageSize": 1000,
        }
        if page_token:
            params["pageToken"] = page_token
        request = client.request("files", params, resource_key, folder_id)
        with client.open(request, Event()) as response:
            page = json.load(response)
        yield from page.get("files", [])
        page_token = page.get("nextPageToken")
        if not page_token:
            break


def build(root, client):
    batches = []
    regions = set()
    for folder in children(client, ROOT_ID):
        region = folder["name"]
        if (
            folder["mimeType"] != "application/vnd.google-apps.folder"
            or not (len(region) == 6 and region.isdigit())
            or not (root / region).is_dir()
        ):
            continue
        if region in regions:
            raise ValueError(f"Duplicate region folder: {region}")
        regions.add(region)
        files = [
            file
            for file in children(client, folder["id"], folder.get("resourceKey"))
            if file["mimeType"] == "application/pdf"
        ]
        if len(files) != 1:
            raise ValueError(f"Region {region} must contain exactly one PDF")
        pdf = files[0]
        # Bind the Drive file to the existing extraction source, never a guessed file.
        local = root / region / pdf["name"]
        if not local.resolve().is_relative_to((root / region).resolve()):
            raise ValueError(f"Unsafe PDF filename for {region}")
        with local.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "md5").hexdigest()
        if local.stat().st_size != int(pdf["size"]) or checksum != pdf["md5Checksum"]:
            raise ValueError(
                f"Region {region}: Drive differs from local extraction source; reconcile before rebuilding"
            )
        batches.append(
            {
                "region": region,
                "folder_id": folder["id"],
                "file_id": pdf["id"],
                "pdf": pdf["name"],
                "size": int(pdf["size"]),
                "md5": checksum,
                "resource_key": pdf.get("resourceKey"),
            }
        )
    if not batches:
        raise ValueError("No region PDFs matched the local scan root")
    return {
        "version": 1,
        "root_id": ROOT_ID,
        "batches": sorted(batches, key=lambda batch: batch["region"]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scan_root", type=Path)
    parser.add_argument("--output", type=Path, default=CATALOGUE)
    args = parser.parse_args()
    load_env()
    try:
        catalogue = build(
            args.scan_root.resolve(),
            DriveClient(os.environ.get("SURVEY_REVIEW_DRIVE_API_KEY")),
        )
        args.output.write_text(json.dumps(catalogue, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    print(f"Pinned {len(catalogue['batches'])} verified region PDFs in {args.output}")
