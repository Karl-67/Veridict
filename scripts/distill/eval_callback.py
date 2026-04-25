"""
eval_callback.py — Custom training-time evaluation callback.

Attaches to SFTTrainer and runs semantic checks at the end of each evaluation
epoch. Does not affect optimizer or gradients — diagnostic only.

Metrics computed (see TRAINING_EVALUATION.md for full definitions):

  All roles:
    json_parse_rate         — fraction of outputs that are valid JSON
    field_complete_rate     — fraction with all required fields present

  Harvey / Kira:
    issue_type_accuracy     — fraction of findings with correct issue_type
    empty_findings_rate     — fraction of responses with {"findings": []}
    per_issue_accuracy      — per-issue-type breakdown

  Validator:
    decision_accuracy       — fraction with correct retain/reject/uncertain
    retain_precision        — precision on predicted "retain"
    reject_recall_on_hn     — recall on hard-negative rows (should be rejected)

Usage:
  from scripts.distill.eval_callback import StructuredEvalCallback

  trainer = SFTTrainer(
      ...,
      callbacks=[StructuredEvalCallback(val_rows=val_rows, role="harvey", max_samples=200)],
  )
"""

import json
import random
from collections import Counter, defaultdict
from typing import Any

REQUIRED_FIELDS = {
    "harvey":    {"issue_type", "severity", "risk_present", "rationale", "evidence_span"},
    "kira":      {"issue_type", "severity", "risk_present", "rationale", "evidence_span"},
    "validator": {"decision", "reason", "evidence_alignment"},
}

VALID_DECISIONS   = {"retain", "reject", "uncertain"}
VALID_SEVERITIES  = {"critical", "high", "medium", "low"}
VALID_ALIGNMENTS  = {"strong", "weak", "none"}

ISSUE_TYPES = {
    "harvey": {
        "liability_exposure", "termination_risk", "ip_risk", "financial_obligation",
        "restriction_clause", "dispute_resolution", "warranty_and_insurance",
        "governance_risk", "third_party_risk",
    },
    "kira": {
        "compliance_obligation", "confidentiality_risk",
        "representation_risk", "jurisdictional_risk",
    },
}

# Warning thresholds (logged but do not stop training)
THRESHOLDS = {
    "json_parse_rate":      0.90,
    "field_complete_rate":  0.85,
    "issue_type_accuracy":  0.55,
    "empty_findings_rate_min": 0.10,
    "empty_findings_rate_max": 0.65,
    "decision_accuracy":    0.60,
    "reject_recall_on_hn":  0.50,
}


class StructuredEvalCallback:
    """
    TrainerCallback that evaluates structured JSON output quality each epoch.

    Parameters
    ----------
    val_rows : list[dict]
        Validation rows in the fine-tuning format
        (each has a "messages" key with system/user/assistant turns).
    role : str
        "harvey", "kira", or "validator"
    max_samples : int
        Cap on how many validation rows to evaluate per epoch (for speed).
    """

    def __init__(self, val_rows: list[dict], role: str, max_samples: int = 200):
        self.role        = role.lower()
        self.max_samples = max_samples
        self._prepare_samples(val_rows)

    # ── Sample preparation ─────────────────────────────────────────────────────

    def _prepare_samples(self, val_rows: list[dict]) -> None:
        """Extract (user_message, gold_assistant) pairs from val_rows."""
        rows = list(val_rows)
        random.shuffle(rows)
        rows = rows[: self.max_samples]

        self.samples: list[tuple[list[dict], str]] = []
        for row in rows:
            msgs = row.get("messages", [])
            if len(msgs) < 3:
                continue
            context = msgs[:-1]          # system + user
            gold    = msgs[-1]["content"] # assistant JSON string
            self.samples.append((context, gold))

    # ── Trainer hook ───────────────────────────────────────────────────────────

    def on_evaluate(self, args: Any, state: Any, control: Any,
                    model: Any = None, tokenizer: Any = None, **kwargs: Any) -> None:
        """Called by the Trainer at the end of each evaluation pass."""
        if model is None or tokenizer is None or not self.samples:
            return

        predictions = self._generate(model, tokenizer)
        metrics     = self._compute_metrics(predictions)
        self._log(metrics, state.epoch or 0)

    # ── Generation ────────────────────────────────────────────────────────────

    def _generate(self, model: Any, tokenizer: Any) -> list[tuple[str, str]]:
        """Generate model responses for each sample. Returns [(pred, gold), ...]."""
        import torch

        results = []
        model.eval()

        for context, gold in self.samples:
            try:
                text = tokenizer.apply_chat_template(
                    context,
                    tokenize=False,
                    add_generation_prompt=True,
                )
                inputs = tokenizer(text, return_tensors="pt",
                                   truncation=True, max_length=1024)
                inputs = {k: v.to(model.device) for k, v in inputs.items()}

                with torch.no_grad():
                    out = model.generate(
                        **inputs,
                        max_new_tokens=256,
                        do_sample=False,
                        pad_token_id=tokenizer.eos_token_id,
                    )

                generated = out[0][inputs["input_ids"].shape[1]:]
                pred = tokenizer.decode(generated, skip_special_tokens=True).strip()
                results.append((pred, gold))

            except Exception:
                results.append(("", gold))

        return results

    # ── Metric computation ────────────────────────────────────────────────────

    def _compute_metrics(self, predictions: list[tuple[str, str]]) -> dict:
        metrics: dict[str, Any] = {}
        n = len(predictions)
        if n == 0:
            return metrics

        parsed_preds   = []
        parsed_golds   = []
        parse_failures = 0

        for pred, gold in predictions:
            pp = _try_parse(pred)
            pg = _try_parse(gold)
            parsed_preds.append(pp)
            parsed_golds.append(pg)
            if pp is None:
                parse_failures += 1

        metrics["json_parse_rate"] = (n - parse_failures) / n

        if self.role in ("harvey", "kira"):
            metrics.update(self._reviewer_metrics(parsed_preds, parsed_golds, n))
        elif self.role == "validator":
            metrics.update(self._validator_metrics(parsed_preds, parsed_golds, predictions))

        return metrics

    def _reviewer_metrics(self, preds: list, golds: list, n: int) -> dict:
        req = REQUIRED_FIELDS[self.role]

        field_complete   = 0
        issue_correct    = 0
        issue_total      = 0
        empty_count      = 0
        per_issue_correct: dict[str, int] = defaultdict(int)
        per_issue_total:   dict[str, int] = defaultdict(int)

        # Aggregate scores for F1, F2, Jaccard, evidence span
        f1_scores:      list[float] = []
        f2_scores:      list[float] = []
        jacc_scores:    list[float] = []  # finding-set Jaccard
        span_f1_scores: list[float] = []  # evidence span token-F1
        span_jacc:      list[float] = []  # evidence span token-Jaccard

        for pp, pg in zip(preds, golds):
            if pp is None:
                continue

            pred_findings = pp.get("findings", []) if isinstance(pp, dict) else []
            gold_findings = pg.get("findings", []) if isinstance(pg, dict) else []

            # Empty-findings rate
            if not pred_findings:
                empty_count += 1

            # Field completeness — check first finding if present
            if pred_findings:
                f = pred_findings[0]
                if isinstance(f, dict) and req.issubset(f.keys()):
                    field_complete += 1
            elif not gold_findings:
                field_complete += 1   # correctly produced empty

            # Issue-type accuracy (exact match on first finding)
            if pred_findings and gold_findings:
                pred_issue = str(pred_findings[0].get("issue_type", "")).strip()
                gold_issue = str(gold_findings[0].get("issue_type", "")).strip()
                per_issue_total[gold_issue] += 1
                issue_total += 1
                if pred_issue == gold_issue:
                    issue_correct += 1
                    per_issue_correct[gold_issue] += 1

            # Finding-set F1, F2, Jaccard
            _, _, f1, jc = _finding_set_scores(pred_findings, gold_findings, beta=1.0)
            _, _, f2, _  = _finding_set_scores(pred_findings, gold_findings, beta=2.0)
            f1_scores.append(f1)
            f2_scores.append(f2)
            jacc_scores.append(jc)

            # Evidence span quality (token-level) — compare first finding
            if pred_findings and gold_findings:
                pred_span = str(pred_findings[0].get("evidence_span", ""))
                gold_span = str(gold_findings[0].get("evidence_span", ""))
                if gold_span:
                    span_f1_scores.append(_token_f1(pred_span, gold_span))
                    span_jacc.append(_token_jaccard(pred_span, gold_span))

        parseable = sum(1 for p in preds if p is not None)

        def mean(lst: list[float]) -> float:
            return sum(lst) / len(lst) if lst else 0.0

        return {
            "field_complete_rate":   field_complete / max(parseable, 1),
            "issue_type_accuracy":   issue_correct  / max(issue_total, 1),
            "empty_findings_rate":   empty_count    / n,
            # Finding-set scores (set of issue_types predicted vs gold)
            "finding_f1":            mean(f1_scores),
            "finding_f2":            mean(f2_scores),   # recall-weighted
            "finding_jaccard":       mean(jacc_scores),
            # Evidence span scores (token overlap between predicted and gold span)
            "evidence_span_f1":      mean(span_f1_scores),
            "evidence_span_jaccard": mean(span_jacc),
            "per_issue_accuracy":    {
                k: per_issue_correct[k] / v
                for k, v in per_issue_total.items() if v > 0
            },
        }

    def _validator_metrics(self, preds: list, golds: list,
                            raw: list[tuple[str, str]]) -> dict:
        req = REQUIRED_FIELDS["validator"]

        field_complete = 0
        decision_correct = 0
        decision_total   = 0
        pred_retain      = 0
        correct_retain   = 0
        gold_hn          = 0   # gold rows that should be rejected (hard negatives)
        hn_rejected      = 0

        for pp, pg in zip(preds, golds):
            if pp is None or pg is None:
                continue

            pred_dec = str(pp.get("decision", "")).strip().lower()
            gold_dec = str(pg.get("decision", "")).strip().lower()

            if pred_dec not in VALID_DECISIONS:
                continue

            decision_total += 1

            # Field completeness
            if req.issubset(pp.keys()):
                field_complete += 1

            # Decision accuracy
            if pred_dec == gold_dec:
                decision_correct += 1

            # Retain precision
            if pred_dec == "retain":
                pred_retain += 1
                if gold_dec == "retain":
                    correct_retain += 1

            # Reject recall on hard negatives
            # Gold "reject" rows in the val set are primarily hard negatives
            if gold_dec == "reject":
                gold_hn += 1
                if pred_dec == "reject":
                    hn_rejected += 1

        parseable = sum(1 for p in preds if p is not None)
        return {
            "field_complete_rate":   field_complete   / max(parseable, 1),
            "decision_accuracy":     decision_correct / max(decision_total, 1),
            "retain_precision":      correct_retain   / max(pred_retain, 1),
            "reject_recall_on_hn":   hn_rejected      / max(gold_hn, 1),
            "decision_distribution": dict(Counter(
                str(p.get("decision", "?")) for p in preds if p is not None
            )),
        }

    # ── Logging ───────────────────────────────────────────────────────────────

    def _log(self, metrics: dict, epoch: float) -> None:
        tag = f"[{self.role.upper()} eval @ epoch {epoch:.1f}]"
        print(f"\n{tag}")

        for key, val in metrics.items():
            if key == "per_issue_accuracy":
                print(f"  per_issue_accuracy:")
                for issue, acc in sorted(val.items(), key=lambda x: -x[1]):
                    warn = " *" if acc < THRESHOLDS["issue_type_accuracy"] else ""
                    print(f"    {issue:30}: {acc:.3f}{warn}")
            elif key == "decision_distribution":
                print(f"  decision_distribution: {val}")
            elif isinstance(val, float):
                threshold_key = key
                threshold = THRESHOLDS.get(threshold_key)
                warn = ""
                if threshold is not None:
                    if key == "empty_findings_rate_min":
                        warn = " * LOW" if val < THRESHOLDS["empty_findings_rate_min"] else ""
                    elif key == "empty_findings_rate":
                        warn  = " * TOO HIGH" if val > THRESHOLDS["empty_findings_rate_max"] else ""
                        warn += " * TOO LOW"  if val < THRESHOLDS["empty_findings_rate_min"] else ""
                    else:
                        warn = " * BELOW THRESHOLD" if val < threshold else ""
                print(f"  {key:30}: {val:.3f}{warn}")

        print()

        # Try to log to the HuggingFace trainer state if available
        try:
            from transformers.integrations import WandbCallback  # noqa: F401
            import wandb
            if wandb.run is not None:
                flat = {f"{self.role}/{k}": v
                        for k, v in metrics.items()
                        if isinstance(v, float)}
                wandb.log(flat, step=None)
        except Exception:
            pass


# ── Scoring helpers ───────────────────────────────────────────────────────────

def _f_beta(precision: float, recall: float, beta: float) -> float:
    """Generic F-beta score. beta=1 → F1, beta=2 → F2 (recall-weighted)."""
    if precision + recall == 0:
        return 0.0
    b2 = beta ** 2
    return (1 + b2) * precision * recall / (b2 * precision + recall)


def _token_jaccard(a: str, b: str) -> float:
    """Token-level Jaccard similarity between two strings."""
    ta = set(a.lower().split())
    tb = set(b.lower().split())
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _token_f1(a: str, b: str) -> float:
    """Token-level F1 (same as SQuAD span evaluation)."""
    ta = a.lower().split()
    tb = b.lower().split()
    common = Counter(ta) & Counter(tb)
    n_common = sum(common.values())
    if n_common == 0:
        return 0.0
    p = n_common / len(ta)
    r = n_common / len(tb)
    return _f_beta(p, r, beta=1.0)


def _finding_set_scores(pred_findings: list[dict], gold_findings: list[dict],
                        beta: float = 1.0) -> tuple[float, float, float, float]:
    """
    Compute precision, recall, F-beta, and Jaccard for a set of findings.

    A predicted finding matches a gold finding when issue_type is identical.
    Returns (precision, recall, f_beta, jaccard).
    """
    pred_issues = [str(f.get("issue_type", "")) for f in pred_findings]
    gold_issues = [str(f.get("issue_type", "")) for f in gold_findings]

    pred_set = set(pred_issues)
    gold_set = set(gold_issues)

    tp = len(pred_set & gold_set)
    fp = len(pred_set - gold_set)
    fn = len(gold_set - pred_set)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f_beta    = _f_beta(precision, recall, beta)
    jaccard   = tp / (tp + fp + fn) if (tp + fp + fn) > 0 else 1.0

    return precision, recall, f_beta, jaccard


# ── Helpers ────────────────────────────────────────────────────────────────────

def _try_parse(text: str) -> dict | None:
    """Attempt to parse a JSON string. Returns None on failure."""
    if not text:
        return None
    try:
        obj = json.loads(text.strip())
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        # Try to extract JSON object from a response that has leading/trailing text
        import re
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        return None
