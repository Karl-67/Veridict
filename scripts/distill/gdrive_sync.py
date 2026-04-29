#!/usr/bin/env python3
"""
gdrive_sync.py — Download labeled Kira training data from Google Drive.

Downloads all .jsonl files from the shared Drive folder to data/kira/labeled/.
Uses gdown for unauthenticated shared-folder access.

Usage:
  python -m scripts.distill.gdrive_sync
  python -m scripts.distill.gdrive_sync --folder-id 1FWhdw0eM2a3iyc_c3hpCCiWnFmBHvfgL
  python -m scripts.distill.gdrive_sync --dry-run
"""

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
GDRIVE_FOLDER_ID = "1FWhdw0eM2a3iyc_c3hpCCiWnFmBHvfgL"
LABELED_DIR = ROOT / "data" / "kira" / "labeled"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _check_gdown() -> None:
    try:
        import gdown  # noqa: F401
    except ImportError:
        sys.exit("gdown not installed. Run: pip install gdown")


def _list_folder(folder_id: str) -> list[dict]:
    """List files in a shared Google Drive folder via gdown."""
    import gdown
    url = f"https://drive.google.com/drive/folders/{folder_id}"
    try:
        files = gdown.download_folder(url, quiet=True, use_cookies=False, output=str(LABELED_DIR))
        return files or []
    except Exception as exc:
        log.error("Failed to list/download folder: %s", exc)
        return []


def sync(folder_id: str = GDRIVE_FOLDER_ID, dry_run: bool = False) -> int:
    """
    Download all .jsonl files from the Drive folder to LABELED_DIR.
    Returns the number of files downloaded.
    """
    _check_gdown()
    import gdown

    LABELED_DIR.mkdir(parents=True, exist_ok=True)

    url = f"https://drive.google.com/drive/folders/{folder_id}"
    log.info("Syncing from Google Drive folder: %s", url)
    log.info("Destination: %s", LABELED_DIR)

    if dry_run:
        log.info("[dry-run] Would download to %s", LABELED_DIR)
        return 0

    try:
        downloaded = gdown.download_folder(
            url,
            output=str(LABELED_DIR),
            quiet=False,
            use_cookies=False,
        )
    except Exception as exc:
        log.error("Download failed: %s", exc)
        log.info("If the folder is not publicly shared, set GOOGLE_APPLICATION_CREDENTIALS")
        log.info("or share the folder with 'Anyone with the link can view'.")
        return 0

    downloaded = downloaded or []
    jsonl_files = [f for f in downloaded if str(f).endswith(".jsonl")]
    log.info("Downloaded %d file(s) (%d .jsonl)", len(downloaded), len(jsonl_files))

    # Report row counts per split
    for path in LABELED_DIR.glob("*.jsonl"):
        try:
            count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
            log.info("  %s: %d rows", path.name, count)
        except Exception:
            pass

    return len(jsonl_files)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download Kira labeled data from Google Drive")
    parser.add_argument("--folder-id", default=GDRIVE_FOLDER_ID)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sync(args.folder_id, args.dry_run)


if __name__ == "__main__":
    main()
