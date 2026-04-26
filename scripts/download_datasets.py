"""Download and cache legal contract datasets from HuggingFace."""

import json
import os
import sys
from pathlib import Path

import pandas as pd
from datasets import load_dataset
from huggingface_hub import hf_hub_download

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def download_cuad():
    """Download the CUAD (Contract Understanding Atticus Dataset).

    Source: theatticusproject/cuad
    510 contracts, 13k+ clause annotations, 41 clause categories.
    Downloads the SQuAD-format JSON directly to avoid Windows symlink issues with PDFs.
    """
    out_dir = DATA_DIR / "atticus"
    out_file = out_dir / "cuad.parquet"
    clauses_file = out_dir / "cuad_clauses.parquet"

    if out_file.exists() and clauses_file.exists():
        print(f"[CUAD] Already cached at {out_dir}")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "CUAD_v1.json"

    # Download just the JSON file via huggingface_hub
    if not json_path.exists():
        print("[CUAD] Downloading SQuAD-format JSON from HuggingFace...")
        downloaded = hf_hub_download(
            repo_id="theatticusproject/cuad",
            filename="CUAD_v1/CUAD_v1.json",
            repo_type="dataset",
            local_dir=str(out_dir),
        )
        downloaded_path = Path(downloaded)
        if downloaded_path != json_path and downloaded_path.exists():
            import shutil
            shutil.copy2(downloaded_path, json_path)
        print(f"[CUAD] Downloaded to {json_path}")
    else:
        print(f"[CUAD] JSON already cached at {json_path}")

    # Parse SQuAD-format JSON into a flat dataframe
    print("[CUAD] Parsing SQuAD JSON...")
    with open(json_path, "r", encoding="utf-8") as f:
        squad_data = json.load(f)

    rows = []
    for article in squad_data.get("data", []):
        title = article.get("title", "")
        for paragraph in article.get("paragraphs", []):
            context = paragraph.get("context", "")
            for qa in paragraph.get("qas", []):
                question = qa.get("question", "")
                is_impossible = qa.get("is_impossible", False)
                answers = qa.get("answers", [])
                answer_texts = [a["text"] for a in answers if a.get("text")]
                answer_starts = [a["answer_start"] for a in answers if "answer_start" in a]
                rows.append({
                    "title": title,
                    "context": context,
                    "question": question,
                    "is_impossible": is_impossible,
                    "answers": {"text": answer_texts, "answer_start": answer_starts},
                })

    df = pd.DataFrame(rows)
    if not out_file.exists():
        df.to_parquet(out_file, index=False)
        print(f"[CUAD] Saved {len(df)} rows to {out_file}")

    # Build clause-level dataframe (full context preserved)
    if not clauses_file.exists():
        expand_cuad_clauses(df, out_dir)


def expand_cuad_clauses(df: pd.DataFrame, out_dir: Path):
    """Expand CUAD's QA-style format into a clause-level dataframe.

    Each answer span becomes one row. The full contract context is stored
    verbatim — no truncation — so build_kira_dataset.py can extract ±8-sentence
    context windows and use it as the DeepSeek full-contract fallback.
    """
    out_file = out_dir / "cuad_clauses.parquet"

    rows = []
    for _, row in df.iterrows():
        context  = row.get("context", "")
        title    = row.get("title", "")
        question = row.get("question", "")
        answers  = row.get("answers", {})

        answer_texts = answers.get("text", []) if isinstance(answers, dict) else []
        for text in answer_texts:
            if text.strip():
                rows.append({
                    "contract_title": title,
                    "clause_type":    question,   # full CUAD question string
                    "clause_text":    text.strip(),
                    "context":        context,    # full contract — no truncation
                })

    clauses_df = pd.DataFrame(rows)
    if clauses_df.empty:
        print("[CUAD] Warning: no clauses extracted, saving empty dataframe")
        clauses_df = pd.DataFrame(columns=["contract_title", "clause_type", "clause_text", "context"])

    clauses_df.to_parquet(out_file, index=False)
    print(f"[CUAD] Extracted {len(clauses_df)} clause spans to {out_file}")


def download_maud():
    """Download the MAUD (Merger Agreement Understanding Dataset).

    Source: theatticusproject/maud
    152 merger agreements, ~47,000 expert-annotated QA rows across 92 questions.
    Covers deal points such as MAE definitions, termination fees, fiduciary-out
    provisions, and representation survival — high-value for contract-review SFT.
    """
    out_dir = DATA_DIR / "maud"
    out_file = out_dir / "maud.parquet"
    if out_file.exists():
        print(f"[MAUD] Already cached at {out_file}")
        return

    print("[MAUD] Downloading from HuggingFace (theatticusproject/maud)...")
    ds = load_dataset("theatticusproject/maud")

    dfs = []
    for split_name in ds:
        split_df = ds[split_name].to_pandas()
        split_df["split"] = split_name
        dfs.append(split_df)

    df = pd.concat(dfs, ignore_index=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_file, index=False)
    print(f"[MAUD] Saved {len(df)} rows to {out_file}")


def main():
    print(f"Data directory: {DATA_DIR}\n")

    download_cuad()
    print()
    download_maud()

    print("\nDone! All datasets saved to", DATA_DIR)


if __name__ == "__main__":
    main()
