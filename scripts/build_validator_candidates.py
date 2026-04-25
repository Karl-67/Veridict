#!/usr/bin/env python3
"""
build_validator_candidates.py — Phase 8 of the branch training pipeline.

Generates Validator training rows from real Harvey/Kira model outputs on
held-out contracts. These candidates teach Validator the actual error distribution
of the reviewers, not just generic NLI patterns.

Two modes:

  --mode proxy   (default, no GPU required)
    Builds synthetic candidates from gold reviewer rows in the test split.
    Positive candidates (retain):   rows with risk_present=True, well-formed evidence
    Negative candidates (reject):   hard negatives from build_hard_negatives.py
    Uncertain candidates:           rows where severity_confidence='weak' or evidence empty

  --mode inference  (requires trained Harvey/Kira checkpoints)
    Loads Harvey/Kira checkpoints and runs inference on held-out contracts.
    Actual model outputs are paired with ground truth for supervision.

Outputs:
  data/distillation/validator/candidates_{train,val,test}.jsonl

These are merged with the ContractNLI base by export_branch.py --role validator.

Run (proxy mode — always available):
  python -m scripts.build_validator_candidates

Run (inference mode — after training Harvey and Kira):
  python -m scripts.build_validator_candidates --mode inference \
    --harvey-model data/distillation/model_harvey \
    --kira-model   data/distillation/model_kira
"""

import argparse
import hashlib
import json
import random
from pathlib import Path

ROOT        = Path(__file__).resolve().parent.parent
DATA_DIR    = ROOT / "data"
DISTILL_DIR = DATA_DIR / "distillation"
CURATED_DIR = DATA_DIR / "curated"
HN_FILE     = CURATED_DIR / "hard_negatives" / "hard_negatives.jsonl"

SPLITS = ("train", "val", "test")

# Ratio of retain:reject:uncertain in candidate pool
RETAIN_FRAC    = 0.50
REJECT_FRAC    = 0.35
UNCERTAIN_FRAC = 0.15

# Total candidate rows per split (merged with ContractNLI base in export_branch.py)
CANDIDATE_TARGET = {"train": 8_000, "val": 1_000, "test": 1_000}

random.seed(42)


# ── I/O ───────────────────────────────────────────────────────────────────────

def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def write_jsonl(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def cand_id(base: str, tag: str) -> str:
    h = hashlib.md5(f"{base}_{tag}".encode()).hexdigest()[:8]
    return f"cand_{h}_{tag[:4]}"


# ── Proxy mode ────────────────────────────────────────────────────────────────

def build_retain_candidate(row: dict) -> dict:
    """Well-supported positive finding → decision=retain."""
    clause   = str(row.get("clause_text") or row.get("full_local_context", "")).strip()
    issue    = str(row.get("mapped_issue_type") or row.get("issue_type", "")).strip()
    severity = str(row.get("severity", "medium")).strip()
    rationale= str(row.get("description", "")).strip()
    evidence = str(row.get("evidence_text", "")).strip() or clause[:200]

    return {
        "id":                cand_id(str(row.get("id", "")), "ret"),
        "source":            row.get("source", ""),
        "contract_id":       row.get("contract_id", ""),
        "clause_text":       clause,
        "issue_type":        issue,
        "severity":          severity,
        "rationale":         rationale,
        "evidence_span":     evidence,
        "decision":          "retain",
        "reason":            "Finding is supported by the clause text and evidence span is accurate.",
        "evidence_alignment":"strong",
        "candidate_source":  "gold_positive",
        "branch":            row.get("branch", ""),
        "split":             row.get("split", "train"),
    }


def build_reject_candidate(row: dict) -> dict:
    """Hard negative / corrupted finding → decision=reject."""
    clause    = str(row.get("clause_text") or row.get("full_local_context", "")).strip()
    issue     = str(row.get("issue_type", "")).strip()
    severity  = str(row.get("severity", "low")).strip()
    neg_type  = str(row.get("negative_type", "hard_negative"))
    rationale = str(row.get("description", "Proposed finding not supported by clause.")).strip()
    evidence  = str(row.get("evidence_text", "")).strip() or clause[:100]

    # Determine rejection reason by negative type
    reason_map = {
        "corrupted_evidence":  "The evidence span does not appear in the clause text.",
        "wrong_issue_label":   "The issue type does not match what the clause addresses.",
        "severity_inflation":  "The stated severity is not justified by the clause language.",
        "paraphrased_finding": "The rationale is not grounded in the clause text.",
        "scary_vocab_safe":    "This clause contains legal vocabulary but creates no material risk.",
        "adjacent_non_risk":   "This clause is adjacent to a risky provision but is itself benign.",
    }
    reason = reason_map.get(neg_type, "Finding is not supported by the clause text.")

    return {
        "id":                cand_id(str(row.get("id", "")), "rej"),
        "source":            row.get("source", ""),
        "contract_id":       row.get("contract_id", ""),
        "clause_text":       clause,
        "issue_type":        issue,
        "severity":          severity,
        "rationale":         rationale,
        "evidence_span":     evidence,
        "decision":          "reject",
        "reason":            reason,
        "evidence_alignment":"none",
        "candidate_source":  f"hard_negative_{neg_type}",
        "branch":            row.get("branch", ""),
        "split":             row.get("split", "train"),
    }


def build_uncertain_candidate(row: dict) -> dict:
    """Weak-confidence positive → decision=uncertain."""
    clause    = str(row.get("clause_text") or row.get("full_local_context", "")).strip()
    issue     = str(row.get("mapped_issue_type") or row.get("issue_type", "")).strip()
    severity  = str(row.get("severity", "medium")).strip()
    rationale = str(row.get("description", "")).strip()
    evidence  = str(row.get("evidence_text", "")).strip() or clause[:150]

    return {
        "id":                cand_id(str(row.get("id", "")), "unc"),
        "source":            row.get("source", ""),
        "contract_id":       row.get("contract_id", ""),
        "clause_text":       clause,
        "issue_type":        issue,
        "severity":          severity,
        "rationale":         rationale,
        "evidence_span":     evidence,
        "decision":          "uncertain",
        "reason":            (
            "Clause is related to the flagged issue but with exploitable gaps "
            "or imprecise grounding."
        ),
        "evidence_alignment":"weak",
        "candidate_source":  "weak_confidence",
        "branch":            row.get("branch", ""),
        "split":             row.get("split", "train"),
    }


def build_proxy_candidates() -> dict[str, list[dict]]:
    """
    Build candidates without running model inference.
    Uses gold reviewer rows and hard negatives as supervision signal.
    """
    result: dict[str, list[dict]] = {s: [] for s in SPLITS}

    # Load full hard-negative pool (all tagged split="train"; reuse proportionally for all splits)
    hard_negatives = load_jsonl(HN_FILE)
    random.shuffle(hard_negatives)

    # Pre-load all branch rows by split
    branch_rows: dict[str, dict[str, list[dict]]] = {}
    for branch in ("harvey", "kira"):
        branch_rows[branch] = {}
        for split in SPLITS:
            branch_rows[branch][split] = load_jsonl(DISTILL_DIR / branch / f"{split}.jsonl")

    for split in SPLITS:
        target  = CANDIDATE_TARGET[split]
        ret_cap = int(target * RETAIN_FRAC)
        rej_cap = int(target * REJECT_FRAC)
        unc_cap = int(target * UNCERTAIN_FRAC)

        # Retain candidates — medium/high/critical positive rows (not hard negatives)
        retain_pool: list[dict] = []
        for branch in ("harvey", "kira"):
            for row in branch_rows[branch][split]:
                if (row.get("risk_present", True)
                        and str(row.get("severity", "")).lower() in ("high", "critical", "medium")
                        and not row.get("negative_type")):
                    retain_pool.append(row)
        random.shuffle(retain_pool)
        retains = [build_retain_candidate(r) for r in retain_pool[:ret_cap]]

        # Reject candidates — sample from the full HN pool proportionally
        hn_sample = random.sample(hard_negatives, min(rej_cap, len(hard_negatives)))
        rejects   = [build_reject_candidate(r) for r in hn_sample]

        # Uncertain candidates — low-severity positives or rows with adjacent-non-risk type
        uncertain_pool: list[dict] = []
        for branch in ("harvey", "kira"):
            for row in branch_rows[branch][split]:
                if (row.get("risk_present", True)
                        and str(row.get("severity", "")).lower() in ("low", "medium")
                        and not row.get("negative_type")
                        and not row.get("evidence_text")):   # no grounded evidence = uncertain
                    uncertain_pool.append(row)
        random.shuffle(uncertain_pool)
        uncertains = [build_uncertain_candidate(r) for r in uncertain_pool[:unc_cap]]

        combined = retains + rejects + uncertains
        random.shuffle(combined)
        result[split] = combined

    return result


# ── Inference mode ────────────────────────────────────────────────────────────

def run_inference_on_held_out(harvey_model: str, kira_model: str) -> dict[str, list[dict]]:
    """
    Load Harvey/Kira checkpoints and run inference on held-out test contracts.
    Pairs each model output with ground truth for retain/reject/uncertain labeling.
    """
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
    except ImportError:
        raise ImportError("transformers required for inference mode. pip install transformers torch")

    result: dict[str, list[dict]] = {s: [] for s in SPLITS}

    for role, model_path in [("harvey", harvey_model), ("kira", kira_model)]:
        if not Path(model_path).exists():
            print(f"  [WARN] Model not found: {model_path} — skipping {role} inference")
            continue

        print(f"  Loading {role} model from {model_path} ...")
        tokenizer = AutoTokenizer.from_pretrained(model_path)
        model     = AutoModelForCausalLM.from_pretrained(
            model_path,
            torch_dtype=torch.bfloat16,
            device_map="auto",
        )
        pipe = pipeline("text-generation", model=model, tokenizer=tokenizer,
                        max_new_tokens=256, do_sample=False)

        # Run on test split held-out rows
        test_rows = load_jsonl(DISTILL_DIR / role / "test.jsonl")
        random.shuffle(test_rows)
        test_rows = test_rows[:500]   # cap inference budget

        from .prompts import SYSTEM_HARVEY, USER_HARVEY, SYSTEM_KIRA, USER_KIRA
        sys_p  = SYSTEM_HARVEY if role == "harvey" else SYSTEM_KIRA
        user_t = USER_HARVEY   if role == "harvey" else USER_KIRA

        for row in test_rows:
            clause  = str(row.get("clause_text") or row.get("full_local_context", "")).strip()
            title   = str(row.get("contract_title", "Unknown")).strip()
            section = str(row.get("section_heading", "General Terms")).strip()
            left    = str(row.get("left_context", "")).strip()
            right   = str(row.get("right_context", "")).strip()

            def _lb(t: str) -> str: return f"Context before:\n{t}\n\n" if t else ""
            def _rb(t: str) -> str: return f"Context after:\n{t}\n\n"  if t else ""

            user_msg = user_t.format(
                contract_title=title, section_heading=section,
                clause_text=clause, left_block=_lb(left), right_block=_rb(right),
            )
            messages = [
                {"role": "system",  "content": sys_p},
                {"role": "user",    "content": user_msg},
            ]

            try:
                out = pipe(messages, return_full_text=False)[0]["generated_text"]
                parsed = json.loads(out.strip())
                findings = parsed.get("findings", [])
            except Exception:
                continue

            gold_present = row.get("risk_present", True)
            gold_issue   = str(row.get("mapped_issue_type") or row.get("issue_type", ""))

            for finding in findings:
                pred_issue = str(finding.get("issue_type", ""))
                evidence   = str(finding.get("evidence_span", ""))

                # Label: retain if issue matches gold and evidence is in clause
                if pred_issue == gold_issue and gold_present and evidence in clause:
                    decision   = "retain"
                    alignment  = "strong"
                    reason     = "Model finding matches gold label and evidence is grounded."
                elif not gold_present or pred_issue != gold_issue:
                    decision   = "reject"
                    alignment  = "none"
                    reason     = "Model predicted wrong issue type or risk where none exists."
                else:
                    decision   = "uncertain"
                    alignment  = "weak"
                    reason     = "Partial match — issue type correct but evidence grounding is weak."

                cand = {
                    "id":                cand_id(str(row.get("id", "")), f"inf_{role[:3]}"),
                    "source":            row.get("source", role),
                    "contract_id":       row.get("contract_id", ""),
                    "clause_text":       clause,
                    "issue_type":        pred_issue,
                    "severity":          str(finding.get("severity", "medium")),
                    "rationale":         str(finding.get("rationale", "")),
                    "evidence_span":     evidence,
                    "decision":          decision,
                    "reason":            reason,
                    "evidence_alignment":alignment,
                    "candidate_source":  f"inference_{role}",
                    "branch":            role,
                    "split":             "train",
                }
                result["train"].append(cand)

        del model, tokenizer, pipe
        print(f"  {role} inference: {len(result['train'])} candidates generated")

    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["proxy", "inference"], default="proxy",
                        help="proxy=synthetic candidates (no GPU); inference=run trained models")
    parser.add_argument("--harvey-model", default=str(DISTILL_DIR / "model_harvey"),
                        help="Path to Harvey checkpoint (inference mode only)")
    parser.add_argument("--kira-model",   default=str(DISTILL_DIR / "model_kira"),
                        help="Path to Kira checkpoint (inference mode only)")
    args = parser.parse_args()

    print("=" * 60)
    print(f"Build Validator Candidates  [mode={args.mode}]")
    print("=" * 60)

    if args.mode == "proxy":
        candidates = build_proxy_candidates()
    else:
        candidates = run_inference_on_held_out(args.harvey_model, args.kira_model)

    val_dir = DISTILL_DIR / "validator"
    total   = 0
    for split, rows in candidates.items():
        out = val_dir / f"candidates_{split}.jsonl"
        write_jsonl(rows, out)
        dec = {}
        for r in rows:
            d = r.get("decision", "?")
            dec[d] = dec.get(d, 0) + 1
        print(f"  {split:5}: {len(rows):>7,} candidates  {dec}")
        total += len(rows)

    print(f"\n  Total: {total:,} candidate rows")
    print(f"  Output: {val_dir}")
    print("\nDone. Run export_branch.py --role validator next.")


if __name__ == "__main__":
    main()
