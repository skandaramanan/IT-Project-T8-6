"""Rebuild public scan mappings and metadata from authoritative Google Drive files.

Requires SURVEY_REVIEW_DRIVE_API_KEY. Never downloads or changes PDFs.
Local archival PDFs are never used to establish source metadata.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from threading import Event

from survey.cli import load_env
from survey.records import safe_pdf
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


def build(root=None, client=None):
    # Keep build(root, client) compatible with older maintenance callers.
    if client is None:
        client = root
    batches = []
    regions = set()
    for folder in children(client, ROOT_ID):
        region = folder["name"]
        if folder["mimeType"] != "application/vnd.google-apps.folder" or not (
            len(region) == 6 and region.isdigit()
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
        if (
            not safe_pdf(pdf["name"])
            or not re.fullmatch(r"[0-9]{1,20}", str(pdf.get("size", "")))
            or int(pdf["size"]) <= 0
            or not re.fullmatch(r"[0-9a-f]{32}", str(pdf.get("md5Checksum", "")))
        ):
            raise ValueError(f"Region {region}: invalid Drive PDF metadata")
        batches.append(
            {
                "region": region,
                "folder_id": folder["id"],
                "file_id": pdf["id"],
                "pdf": pdf["name"],
                "size": int(pdf["size"]),
                "md5": pdf["md5Checksum"],
                "resource_key": pdf.get("resourceKey"),
            }
        )
    if not batches:
        raise ValueError("No region PDFs found in Drive")
    return {
        "version": 1,
        "root_id": ROOT_ID,
        "batches": sorted(batches, key=lambda batch: batch["region"]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "scan_root", type=Path, nargs="?", help="Deprecated; local PDFs are not checked"
    )
    parser.add_argument("--output", type=Path, default=CATALOGUE)
    args = parser.parse_args()
    if args.scan_root is not None:
        print(
            "The scan_root argument is deprecated and ignored; Drive is authoritative.",
            file=sys.stderr,
        )
    load_env()
    try:
        catalogue = build(
            client=DriveClient(os.environ.get("SURVEY_REVIEW_DRIVE_API_KEY")),
        )
        args.output.write_text(json.dumps(catalogue, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    print(f"Recorded {len(catalogue['batches'])} Drive region PDFs in {args.output}")
