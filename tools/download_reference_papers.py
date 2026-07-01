#!/usr/bin/env python3
"""Download open-access/reference PDFs listed in paper/literature/reference_papers.csv."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download open PDFs for the GNSS spoofing literature collection.")
    parser.add_argument("--manifest-csv", default="paper/literature/reference_papers.csv")
    parser.add_argument("--output-dir", default="paper/literature/papers")
    parser.add_argument("--summary-json", default="paper/literature/reference_papers_downloaded.json")
    parser.add_argument("--timeout-s", type=float, default=45.0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Return non-zero if any download fails.")
    return parser.parse_args()


def resolve(path: str | Path) -> Path:
    value = Path(path).expanduser()
    if not value.is_absolute():
        value = PROJECT_ROOT / value
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def looks_like_pdf(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 1024:
        return False
    with path.open("rb") as handle:
        return handle.read(5) == b"%PDF-"


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def download(url: str, destination: Path, timeout_s: float) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 GNSS literature downloader (open-access references)",
            "Accept": "application/pdf,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        data = response.read()
    destination.write_bytes(data)


def main() -> int:
    args = parse_args()
    manifest_path = resolve(args.manifest_csv)
    output_dir = resolve(args.output_dir)
    summary_path = resolve(args.summary_json)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = read_manifest(manifest_path)
    summary: list[dict[str, object]] = []
    for row in rows:
        key = row.get("key", "").strip()
        url = row.get("pdf_url", "").strip()
        filename = row.get("filename", f"{key}.pdf").strip()
        destination = output_dir / filename
        item: dict[str, object] = {
            "key": key,
            "title": row.get("title", ""),
            "url": url,
            "file": display_path(destination),
            "license_note": row.get("license_note", ""),
        }
        if not url:
            item["status"] = "skipped_no_url"
            summary.append(item)
            print(f"skip {key}: no URL")
            continue
        if destination.exists() and looks_like_pdf(destination) and not args.force:
            item["status"] = "exists"
            item["bytes"] = destination.stat().st_size
            item["sha256"] = sha256_file(destination)
            summary.append(item)
            print(f"exists {key}: {destination}")
            continue
        try:
            download(url, destination, args.timeout_s)
            if not looks_like_pdf(destination):
                item["status"] = "failed_not_pdf"
                item["bytes"] = destination.stat().st_size if destination.exists() else 0
                print(f"failed {key}: response is not a PDF")
            else:
                item["status"] = "downloaded"
                item["bytes"] = destination.stat().st_size
                item["sha256"] = sha256_file(destination)
                print(f"downloaded {key}: {destination}")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            item["status"] = "failed"
            item["error"] = str(exc)
            print(f"failed {key}: {exc}", file=sys.stderr)
        summary.append(item)

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    downloaded = sum(1 for item in summary if item.get("status") in {"downloaded", "exists"})
    failed = sum(1 for item in summary if str(item.get("status", "")).startswith("failed"))
    print(f"Reference PDF download summary: {downloaded}/{len(summary)} available, {failed} failed")
    print(f"summary: {summary_path}")
    return 2 if args.strict and failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
