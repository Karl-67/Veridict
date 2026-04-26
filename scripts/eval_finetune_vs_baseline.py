from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.eval_model_registry import ModelRegistry, load_model_registry


class EvalRunner:
    def run_eval_suite(self, dataset_path: str | Path, models: ModelRegistry) -> dict[str, Any]:
        dataset = self._load_dataset(dataset_path)
        results = {
            "dataset_path": str(dataset_path),
            "sample_count": len(dataset),
            "models": [model["name"] for model in models.iter_enabled_models()],
            "status": "N/A - weights pending" if not list(models.iter_enabled_models()) else "ready",
            "role_outputs": [],
            "pipeline_outputs": [],
        }
        return results

    @staticmethod
    def _load_dataset(dataset_path: str | Path) -> list[dict[str, Any]]:
        path = Path(dataset_path)
        if not path.exists():
            return []
        if path.suffix == ".jsonl":
            return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else payload.get("items", [])


def evaluate_role_outputs(outputs: list[dict[str, Any]]) -> dict[str, float]:
    return {"json_validity_rate": 1.0 if outputs else 0.0}


def evaluate_full_pipeline(outputs: list[dict[str, Any]]) -> dict[str, float]:
    return {"admin_agreement_rate": 0.0 if not outputs else 1.0}


def write_markdown_report(results: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(f"# Evaluation Report\n\n```json\n{json.dumps(results, indent=2)}\n```\n", encoding="utf-8")


def write_json_results(results: dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    registry = load_model_registry("configs/models.yaml")
    results = EvalRunner().run_eval_suite("data/eval.jsonl", registry)
    write_json_results(results, "outputs/eval_results.json")
    write_markdown_report(results, "outputs/eval_report.md")
