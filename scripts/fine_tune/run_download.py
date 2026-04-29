#!/usr/bin/env python3
"""Download training data from Google Drive to RunPod workspace."""
import gdown, pathlib

pathlib.Path("/workspace/verdict_training/data/raw").mkdir(parents=True, exist_ok=True)
gdown.download_folder(
    "https://drive.google.com/drive/folders/1FWhdw0eM2a3iyc_c3hpCCiWnFmBHvfgL",
    output="/workspace/verdict_training/data/raw",
    quiet=False,
    use_cookies=False,
)
pathlib.Path("/workspace/verdict_training/logs/gdrive_done.flag").write_text("DONE")
print("Download complete.")
