# Evaluation Plan

## Models

- Fine-tuned Gemma 26B.
- Gemma 26B base.
- Two legal baseline models.

## Datasets

- CUAD subset.
- ContractNLI subset.
- Internal golden contracts.

## Protocol

- Run identical prompts, retrieval settings, decoding config, and role structure across all models.
- Evaluate per role and full pipeline.
- Use paired comparisons, bootstrap confidence intervals, and McNemar tests.

## Metrics

- JSON validity.
- Contradiction precision/recall/F1.
- Citation accuracy and hallucinated citation rate.
- Severity calibration.
- Admin agreement rate.
- Latency and cost.

## Claim Policy

No superiority claim should be made until `p < 0.05` and the confidence interval excludes zero.
