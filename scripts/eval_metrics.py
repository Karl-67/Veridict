from __future__ import annotations

import math
import random
from collections import Counter
from statistics import mean


def json_validity_rate(valid_flags: list[bool]) -> float:
    return sum(valid_flags) / len(valid_flags) if valid_flags else 0.0


def contradiction_prf(predicted: set[str], gold: set[str]) -> dict[str, float]:
    tp = len(predicted & gold)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(gold) if gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def citation_accuracy(valid_citations: list[bool]) -> float:
    return json_validity_rate(valid_citations)


def hallucinated_citation_rate(valid_citations: list[bool]) -> float:
    return 1.0 - citation_accuracy(valid_citations) if valid_citations else 0.0


def severity_calibration(probabilities: list[float], outcomes: list[bool], bins: int = 10) -> dict[str, float]:
    if not probabilities:
        return {"brier": 0.0, "ece": 0.0}
    brier = mean((p - float(y)) ** 2 for p, y in zip(probabilities, outcomes))
    ece = 0.0
    for index in range(bins):
        lo, hi = index / bins, (index + 1) / bins
        bucket = [(p, y) for p, y in zip(probabilities, outcomes) if lo <= p < hi or (index == bins - 1 and p == 1.0)]
        if bucket:
            conf = mean(p for p, _ in bucket)
            acc = mean(float(y) for _, y in bucket)
            ece += (len(bucket) / len(probabilities)) * abs(acc - conf)
    return {"brier": brier, "ece": ece}


def admin_agreement_rate(admin_labels: list[str], gold_labels: list[str]) -> float:
    if not admin_labels:
        return 0.0
    return sum(a == g for a, g in zip(admin_labels, gold_labels)) / len(admin_labels)


def latency_cost_summary(rows: list[dict]) -> dict[str, float]:
    return {
        "latency_mean": mean(row.get("latency_seconds", 0.0) for row in rows) if rows else 0.0,
        "cost_total": sum(row.get("cost_usd", 0.0) for row in rows),
    }


def bootstrap_confidence_interval(values: list[float], n: int = 1000, alpha: float = 0.05) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    samples = sorted(mean(random.choice(values) for _ in values) for _ in range(n))
    return (samples[int((alpha / 2) * n)], samples[int((1 - alpha / 2) * n) - 1])


def mcnemar_test(a_correct: list[bool], b_correct: list[bool]) -> dict[str, float]:
    counts = Counter((a, b) for a, b in zip(a_correct, b_correct))
    b = counts[(True, False)]
    c = counts[(False, True)]
    statistic = ((abs(b - c) - 1) ** 2 / (b + c)) if b + c else 0.0
    p_approx = math.exp(-0.5 * statistic)
    return {"statistic": statistic, "p_value_approx": p_approx}
