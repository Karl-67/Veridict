# Training-Time Evaluation

How Harvey, Kira, and Validator know they are improving during fine-tuning.

---

## The Core Signal: Next-Token Prediction Loss

All three models are trained with **supervised fine-tuning (SFT)**. The only signal
the model receives during training is the cross-entropy loss over the assistant
tokens — the structured JSON it is expected to produce.

For every training example, the input is a (system, user) message pair and the
target is the assistant JSON string. The model predicts one token at a time. For
each token it predicts, the loss measures how far that prediction was from the
correct token. The optimizer then adjusts the model weights to reduce that
distance.

A concrete example. Harvey receives this clause:

```
Contract: ACME Software License
Section: Limitation of Liability
--- CLAUSE ---
In no event shall Licensor be liable for any indirect, incidental,
special or consequential damages...
--- END CLAUSE ---
```

The expected output is:

```json
{"findings": [{"issue_type": "liability_exposure", "severity": "high",
  "risk_present": true,
  "rationale": "The clause caps all consequential damages with no financial ceiling.",
  "evidence_span": "In no event shall Licensor be liable for any indirect"}]}
```

The model is trained to predict every character of that JSON string in order.
When it predicts `"liability_exposure"` correctly, the loss for those tokens is
low. When it predicts `"liability_risk"` instead, the loss is high and the
weights are corrected.

---

## What the Trainer Measures

The `SFTTrainer` (from TRL) computes two loss values throughout training:

| Metric | When computed | What it measures |
|---|---|---|
| `train/loss` | Every N steps during training | How well the model fits the training data |
| `eval/loss` | Once per epoch on the validation split | How well the model generalises to unseen data |

Both are cross-entropy values. Lower is better. The key number to watch is
`eval/loss`. Training loss will always decrease because the model has seen those
examples. Eval loss tells you whether the model is actually learning the pattern
or memorising individual examples.

**What good looks like:**

- Training loss and eval loss both decrease together for the first epoch or two.
  This means the model is learning real patterns.
- If training loss keeps falling but eval loss plateaus or rises, the model is
  starting to overfit. The `save_total_limit=2` and `load_best_model_at_end=True`
  settings in the config ensure the best checkpoint (lowest eval loss) is saved
  automatically.

---

## The Structured JSON Problem

Token loss alone is necessary but not sufficient for these models. The output
must be valid, parseable JSON with the correct field names and values. A model
can have a reasonable token loss and still produce broken JSON or use the wrong
issue type label.

This creates a gap between what the loss measures and what actually matters in
production:

| What loss measures | What actually matters |
|---|---|
| Did the model predict the right tokens? | Is the output valid JSON? |
| Was `liability_exposure` predicted correctly? | Does the issue type match the clause? |
| Were the rationale tokens correct? | Is the rationale grounded in the clause text? |
| Was `"high"` predicted correctly? | Is the severity calibrated to the actual risk? |

To close this gap, training is supplemented with **custom eval callbacks**
(see below) that compute semantically meaningful metrics on the validation set
at the end of each epoch.

---

## Custom Eval Callbacks

These run after each epoch on the validation split. They do not affect the
optimizer — they are diagnostic only. They are implemented in
`scripts/distill/eval_callback.py`.

### 1. JSON Parse Rate

The most basic check. Of all responses the model generates on the validation
set, what fraction are valid JSON that can be parsed without error?

A model that produces broken JSON cannot be used in production regardless of
its token loss. This metric should reach and stay above 95% within the first
epoch for a model fine-tuned on well-formed examples.

```
json_parse_rate = parseable_responses / total_responses
```

### 2. Field Completeness Rate

Of the responses that are valid JSON, what fraction contain all required fields?

For Harvey and Kira the required fields per finding are:
`issue_type`, `severity`, `risk_present`, `rationale`, `evidence_span`.

For Validator the required fields are: `decision`, `reason`, `evidence_alignment`.

A model can produce valid JSON with missing fields. This metric catches that.

```
field_complete_rate = responses_with_all_fields / parseable_responses
```

### 3. F1, F2, and Jaccard (Harvey and Kira)

These three scores measure the quality of the **finding set** the model returns
for a clause — not just whether one token was right, but whether the full set
of predicted issue types matches the full set of gold issue types.

**Finding-set F1**

Standard harmonic mean of precision and recall over predicted vs. gold issue types.
Treats each unique `issue_type` as an element of a set.

```
precision = |pred_issues ∩ gold_issues| / |pred_issues|
recall    = |pred_issues ∩ gold_issues| / |gold_issues|
F1        = 2 × precision × recall / (precision + recall)
```

Most clauses have one finding, so F1 reduces to 1.0 (exact match) or 0.0
(wrong type) for single-finding cases. Where a clause genuinely has two
flagged issues, F1 rewards getting both right.

**Finding-set F2**

Same formula with beta=2, which weights recall twice as heavily as precision.
Harvey is recall-first by design (missing a real risk is worse than a false
positive), so F2 is a better primary metric for Harvey. Kira is more
precision-oriented, so F1 is the primary metric there.

```
F2 = 5 × precision × recall / (4 × precision + recall)
```

**Finding-set Jaccard**

The ratio of the intersection to the union of predicted and gold issue types.
Stricter than F1 because false positives and false negatives are penalised
symmetrically.

```
Jaccard = |pred ∩ gold| / |pred ∪ gold|
```

A model that predicts `liability_exposure` when the gold is
`financial_obligation` gets Jaccard = 0 and F1 = 0 for that example.
A model that predicts both and gold has only one gets Jaccard = 0.5.

**Evidence span F1 and Jaccard**

The same token-overlap metrics applied to the `evidence_span` field instead of
the issue type. This measures whether the quoted clause text the model returns
actually matches what a human would quote.

```
evidence_span_f1      = token-level F1 between predicted and gold evidence_span
evidence_span_jaccard = token-level Jaccard between predicted and gold evidence_span
```

Both treat each token as an element of a multiset, so repeated words are
handled correctly (same as the SQuAD reading comprehension evaluation method).

**Target values at convergence:**

| Metric | Harvey target | Kira target |
|---|---|---|
| finding_f1 | ≥ 0.70 | ≥ 0.68 |
| finding_f2 | ≥ 0.72 | ≥ 0.65 |
| finding_jaccard | ≥ 0.60 | ≥ 0.58 |
| evidence_span_f1 | ≥ 0.50 | ≥ 0.50 |
| evidence_span_jaccard | ≥ 0.40 | ≥ 0.40 |

The evidence span targets are intentionally lower because the gold evidence spans
in the training data are derived from the `clause_text` field (not human-highlighted
spans) and are therefore imprecise ground truth. These numbers improve substantially
after the GPT annotation pipeline populates real `evidence_text` fields.

---

### 3. Issue-Type Accuracy (Harvey and Kira)

Of all findings produced on the validation set, what fraction have an
`issue_type` that matches the gold label exactly?

This is the most important semantic metric for Harvey and Kira. If the model
consistently returns the right issue family (liability, compliance, etc.) for
the right clauses, it has learned the core task.

```
issue_type_accuracy = correct_issue_type_findings / total_findings
```

This is computed per issue family as well, so you can see if the model is
stronger on frequent categories (compliance_obligation, liability_exposure)
than rare ones (jurisdictional_risk, third_party_risk).

### 4. Empty-Findings Rate

What fraction of validation examples produce `{"findings": []}` (the no-risk
output)?

This metric has two interpretations depending on the direction it moves:

- Too high: the model is becoming overly conservative and refusing to flag
  real risks. Recall is degrading.
- Too low: the model is overclaiming and flagging everything. Precision is
  degrading.

The target empty-findings rate on the validation set should be close to the
true no-risk fraction in that split (approximately 25–35% for Harvey, 30–40%
for Kira based on the training data composition).

```
empty_findings_rate = empty_responses / total_responses
```

### 5. Decision Accuracy (Validator only)

Validator is effectively a 3-class classifier. The decision accuracy is the
fraction of validation examples where the predicted `decision` field
(retain/reject/uncertain) matches the gold label.

This is the primary semantic metric for Validator. It should be tracked
separately for each decision class because the model must not collapse into
always predicting the majority class.

```
decision_accuracy        = correct_decisions / total_decisions
retain_precision         = correct_retain / all_predicted_retain
reject_recall_on_HN      = correctly_rejected_HN / total_HN_in_val
```

The `reject_recall_on_HN` number is particularly important. Hard negative rows
in the validation set are explicitly labelled for rejection. If the model fails
to reject them, it is not providing meaningful filtering.

---

## How to Read Training Progress

The following pattern is expected and healthy for all three models:

```
Epoch 1:
  train/loss: 1.8 → 1.2
  eval/loss:  1.9 → 1.4
  json_parse_rate: 0.72
  issue_type_accuracy: 0.51

Epoch 2:
  train/loss: 1.2 → 0.7
  eval/loss:  1.4 → 1.0
  json_parse_rate: 0.91
  issue_type_accuracy: 0.68

Epoch 3:
  train/loss: 0.7 → 0.4
  eval/loss:  1.0 → 0.95    ← eval loss near-flat: converging
  json_parse_rate: 0.97
  issue_type_accuracy: 0.74
```

Warning signs to act on:

| Pattern | Diagnosis | Action |
|---|---|---|
| eval/loss rises while train/loss falls | Overfitting | Reduce epochs, increase LoRA dropout, reduce learning rate |
| json_parse_rate stays below 0.80 | Model not learning JSON structure | Check that training data has consistent formatting; reduce MAX_SEQ_LENGTH to avoid truncation |
| issue_type_accuracy plateaus below 0.55 | Model collapsing to majority class | Check class_weight field is being used; increase rare-class oversampling |
| empty_findings_rate above 0.60 | Model becoming too conservative | Check hard-negative fraction is not dominating the training set |
| decision_accuracy uniform across classes | Validator ignoring class signal | Check retain/reject/uncertain balance in validator_ft/train.jsonl |

---

## What "Converged" Means for Each Model

### Harvey
- eval/loss stable for at least one epoch
- json_parse_rate ≥ 0.96
- issue_type_accuracy ≥ 0.70 on Harvey issue families
- finding_f2 ≥ 0.72 (recall-weighted — Harvey is recall-first)
- finding_jaccard ≥ 0.60
- evidence_span_f1 ≥ 0.50
- empty_findings_rate in range 0.20 – 0.40

### Kira
- Same loss and parse rate targets as Harvey
- issue_type_accuracy ≥ 0.68 on Kira issue families (compliance_obligation,
  confidentiality_risk, representation_risk, jurisdictional_risk)
- finding_f1 ≥ 0.68 (standard F1 — Kira is more precision-oriented)
- finding_jaccard ≥ 0.58
- evidence_span_f1 ≥ 0.50
- empty_findings_rate in range 0.25 – 0.45 (Kira is more conservative by design)

### Validator
- eval/loss stable
- decision_accuracy ≥ 0.72 overall
- retain_precision ≥ 0.80 (it should not retain unsupported findings)
- reject_recall_on_HN ≥ 0.65 (it must catch the hard negatives)

---

## Implementation: eval_callback.py

The custom metrics above are implemented as a `transformers.TrainerCallback` that
runs at the end of each evaluation epoch. It generates responses from the model
on a fixed sample of validation rows (capped at 200 for speed), parses the
outputs, and logs all metrics to the same logging destination as the trainer
(console, and optionally Weights & Biases or TensorBoard).

Location: `scripts/distill/eval_callback.py`

To attach it to training, pass it to `SFTTrainer` via the `callbacks` argument:

```python
from scripts.distill.eval_callback import StructuredEvalCallback

trainer = SFTTrainer(
    ...
    callbacks=[StructuredEvalCallback(val_rows=val_rows, role="harvey", max_samples=200)],
)
```

The callback accepts a `role` argument (harvey, kira, validator) so it knows
which fields and thresholds to check.

---

## Summary

During training, the model receives one signal: **cross-entropy loss on the
expected JSON tokens**. This tells the model at the token level whether it is
predicting the right characters. The trainer saves the checkpoint with the
lowest validation loss.

On top of that, custom callbacks measure what the token loss cannot: whether
the output is valid JSON, whether the issue type is semantically correct, and
whether the Validator is correctly filtering hard negatives. These metrics do
not affect training — they tell you when to stop and which checkpoint to keep.

The combination of token loss for optimisation and semantic callbacks for
diagnosis gives a complete picture of training health without requiring a
separate evaluation run.
