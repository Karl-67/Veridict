#!/usr/bin/env python3
"""
upload_datasets_to_blob.py — Seed Azure Blob Storage with training artifacts.

Run this once after `infra/main.bicep` is deployed, then re-run whenever
golden data or distillation outputs change.

Uploads:
  data/curated/golden/        → datasets/golden/
  data/distillation/          → datasets/distillation/
  data/curated/normalized/    → datasets/curated/normalized/   (if present)
  data/atticus/               → datasets/raw/atticus/          (--include-raw only)
  data/legal_clauses/         → datasets/raw/legal_clauses/    (--include-raw only)
  data/contractnli/           → datasets/raw/contractnli/      (--include-raw only)
  data/maud/                  → datasets/raw/maud/             (--include-raw only)

Authentication (tried in order):
  1. DefaultAzureCredential   — works with `az login`, OIDC, managed identity
  2. AZURE_STORAGE_CONNECTION_STRING env var

Required env (for DefaultAzureCredential path):
  AZURE_STORAGE_ACCOUNT_NAME  from `az deployment group show` / bicep output storageAccountName

Usage:
  python scripts/upload_datasets_to_blob.py
  python scripts/upload_datasets_to_blob.py --include-raw
  python scripts/upload_datasets_to_blob.py --dry-run
  python scripts/upload_datasets_to_blob.py --container artifacts --local-dir scripts/fine_tune/output --prefix eval
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTAINER = "datasets"


def _log(msg: str) -> None:
    print(msg, flush=True)


def _fail(reason: str) -> None:
    _log(f"\nFAIL  {reason}")
    sys.exit(1)


def _get_client(account_name: str | None, connection_string: str | None):
    """Return a BlobServiceClient using the best available credential."""
    try:
        from azure.storage.blob import BlobServiceClient
    except ImportError:
        _fail(
            "azure-storage-blob is not installed.\n"
            "Run: pip install azure-storage-blob azure-identity"
        )

    if connection_string:
        _log("  Auth: connection string")
        return BlobServiceClient.from_connection_string(connection_string)

    if account_name:
        try:
            from azure.identity import DefaultAzureCredential
            _log("  Auth: DefaultAzureCredential")
            url = f"https://{account_name}.blob.core.windows.net"
            return BlobServiceClient(account_url=url, credential=DefaultAzureCredential())
        except ImportError:
            _fail(
                "azure-identity is not installed.\n"
                "Run: pip install azure-identity"
            )

    _fail(
        "No Azure credentials found.\n"
        "Set AZURE_STORAGE_ACCOUNT_NAME (uses DefaultAzureCredential / az login)\n"
        "or AZURE_STORAGE_CONNECTION_STRING."
    )


def _upload_directory(
    client,
    container: str,
    local_dir: Path,
    blob_prefix: str,
    dry_run: bool,
    extensions: set[str] | None = None,
) -> int:
    """Upload all files in local_dir recursively. Returns count of files uploaded."""
    if not local_dir.exists():
        _log(f"  SKIP  {local_dir} does not exist")
        return 0

    files = [f for f in local_dir.rglob("*") if f.is_file()]
    if extensions:
        files = [f for f in files if f.suffix.lower() in extensions]

    if not files:
        _log(f"  SKIP  {local_dir} — no matching files")
        return 0

    container_client = client.get_container_client(container)
    uploaded = 0
    for f in sorted(files):
        rel = f.relative_to(local_dir)
        blob_name = f"{blob_prefix}/{rel}".replace("\\", "/")
        if dry_run:
            _log(f"  [DRY RUN] {f}  →  {container}/{blob_name}")
        else:
            blob_client = container_client.get_blob_client(blob_name)
            with f.open("rb") as fh:
                blob_client.upload_blob(fh, overwrite=True)
            _log(f"  OK  {blob_name}")
        uploaded += 1

    return uploaded


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload Veridict datasets to Azure Blob Storage.")
    parser.add_argument("--include-raw", action="store_true",
                        help="Also upload raw parquet datasets (atticus, legal_clauses, contractnli, maud)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be uploaded without transferring any files")
    parser.add_argument("--container", default=CONTAINER,
                        help=f"Target blob container (default: {CONTAINER})")
    parser.add_argument("--local-dir", type=Path, default=None,
                        help="Upload a single local directory instead of the default set")
    parser.add_argument("--prefix", default=None,
                        help="Blob prefix override (used with --local-dir)")
    args = parser.parse_args()

    account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME", "").strip() or None
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "").strip() or None

    _log("=" * 60)
    _log("Veridict Dataset Upload")
    _log(f"Container : {args.container}")
    _log(f"Dry run   : {args.dry_run}")
    _log("=" * 60)

    client = _get_client(account_name, conn_str)

    total = 0

    if args.local_dir:
        # Ad-hoc single-directory upload
        prefix = args.prefix or args.local_dir.name
        _log(f"\nUploading {args.local_dir}  →  {args.container}/{prefix}/")
        total += _upload_directory(client, args.container, args.local_dir, prefix, args.dry_run)
    else:
        uploads = [
            (ROOT / "data" / "curated" / "golden",      "golden",                   None),
            (ROOT / "data" / "distillation",             "distillation",             None),
            (ROOT / "data" / "curated" / "normalized",   "curated/normalized",       None),
        ]
        if args.include_raw:
            raw_ext = {".parquet", ".jsonl", ".json", ".csv"}
            uploads += [
                (ROOT / "data" / "atticus",       "raw/atticus",       raw_ext),
                (ROOT / "data" / "legal_clauses", "raw/legal_clauses", raw_ext),
                (ROOT / "data" / "contractnli",   "raw/contractnli",   raw_ext),
                (ROOT / "data" / "maud",          "raw/maud",          raw_ext),
            ]

        for local_dir, prefix, ext in uploads:
            _log(f"\nUploading {local_dir.relative_to(ROOT)}  →  {args.container}/{prefix}/")
            total += _upload_directory(
                client, args.container, local_dir, prefix, args.dry_run, extensions=ext
            )

    _log("\n" + "=" * 60)
    action = "Would upload" if args.dry_run else "Uploaded"
    _log(f"PASS  {action} {total} file(s)")
    _log("=" * 60)


if __name__ == "__main__":
    main()
