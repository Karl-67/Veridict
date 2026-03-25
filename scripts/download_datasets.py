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
    if out_file.exists():
        print(f"[CUAD] Already cached at {out_file}")
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
        # Move to expected location if needed
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
    df.to_parquet(out_file, index=False)
    print(f"[CUAD] Saved {len(df)} rows to {out_file}")

    # Also create an expanded clause-level dataframe
    expand_cuad_clauses(df, out_dir)


def expand_cuad_clauses(df: pd.DataFrame, out_dir: Path):
    """Expand CUAD's QA-style format into a clause-level dataframe.

    CUAD stores clauses as answer spans in a SQuAD-like format.
    We extract each clause with its category for EDA purposes.
    """
    out_file = out_dir / "cuad_clauses.parquet"

    # CUAD clause category names (41 categories)
    clause_categories = [
        "Document Name", "Parties", "Agreement Date", "Effective Date",
        "Expiration Date", "Renewal Term", "Notice Period To Terminate Renewal",
        "Governing Law", "Most Favored Nation", "Non-Compete",
        "Exclusivity", "No-Solicit Of Customers", "Competitive Restriction Exception",
        "No-Solicit Of Employees", "Non-Disparagement", "Termination For Convenience",
        "Rofr/Rofo/Rofn", "Change Of Control", "Anti-Assignment",
        "Revenue/Profit Sharing", "Price Restrictions", "Minimum Commitment",
        "Volume Restriction", "Ip Ownership Assignment", "Joint Ip Ownership",
        "License Grant", "Non-Transferable License", "Affiliate License-Licensor",
        "Affiliate License-Licensee", "Unlimited/All-You-Can-Eat-License",
        "Irrevocable Or Perpetual License", "Source Code Escrow",
        "Post-Termination Services", "Audit Rights", "Uncapped Liability",
        "Cap On Liability", "Liquidated Damages", "Warranty Duration",
        "Insurance", "Covenant Not To Sue", "Third Party Beneficiary",
    ]

    rows = []
    for _, row in df.iterrows():
        context = row.get("context", "")
        title = row.get("title", "")

        answers = row.get("answers", {})
        question = row.get("question", "")

        # Match question to clause category
        clause_type = question if question else "Unknown"

        answer_texts = answers.get("text", []) if isinstance(answers, dict) else []
        for text in answer_texts:
            if text.strip():
                rows.append({
                    "contract_title": title,
                    "clause_type": clause_type,
                    "clause_text": text.strip(),
                    "context": context[:500],  # truncate for storage
                })

    clauses_df = pd.DataFrame(rows)
    if clauses_df.empty:
        print("[CUAD] Warning: no clauses extracted, saving empty dataframe")
        clauses_df = pd.DataFrame(columns=["contract_title", "clause_type", "clause_text", "context"])

    clauses_df.to_parquet(out_file, index=False)
    print(f"[CUAD] Extracted {len(clauses_df)} clause spans to {out_file}")


def download_ledgar():
    """Download the LEDGAR dataset (from LexGLUE).

    Source: coastalcph/lex_glue, config='ledgar'
    Contract provision classification with 100 provision types.
    """
    out_dir = DATA_DIR / "legal_clauses"
    out_file = out_dir / "ledgar.parquet"
    if out_file.exists():
        print(f"[LEDGAR] Already cached at {out_file}")
        return

    print("[LEDGAR] Downloading from HuggingFace...")
    ds = load_dataset("coastalcph/lex_glue", "ledgar")

    # Combine all splits
    dfs = []
    for split_name in ds:
        split_df = ds[split_name].to_pandas()
        split_df["split"] = split_name
        dfs.append(split_df)

    df = pd.concat(dfs, ignore_index=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_file, index=False)
    print(f"[LEDGAR] Saved {len(df)} rows to {out_file}")


def main():
    print(f"Data directory: {DATA_DIR}\n")

    download_cuad()
    print()
    download_ledgar()

    print("\nDone! All datasets saved to", DATA_DIR)


if __name__ == "__main__":
    main()
