from scripts.eval_metrics import contradiction_prf, json_validity_rate, mcnemar_test
from scripts.eval_model_registry import PENDING, load_model_registry, mark_missing_as_pending


def test_json_validity_rate():
    assert json_validity_rate([True, False, True]) == 2 / 3


def test_contradiction_prf():
    scores = contradiction_prf({"a", "b"}, {"b", "c"})
    assert scores["precision"] == 0.5
    assert scores["recall"] == 0.5


def test_mcnemar_smoke():
    assert "p_value_approx" in mcnemar_test([True, False], [False, False])


def test_disabled_finetuned_pending():
    registry = load_model_registry("configs/models.yaml")
    rows = mark_missing_as_pending(registry)
    assert any(row["model_id"] == "gemma_26b_finetuned" and row["status"] == PENDING for row in rows)
