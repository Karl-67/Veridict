from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml


PENDING = "N/A - weights pending"


@dataclass
class ModelRegistry:
    models: dict[str, dict[str, Any]]

    def iter_enabled_models(self):
        return (item for item in self.models.values() if item.get("enabled"))

    def mark_missing_as_pending(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for model_id, model in self.models.items():
            if not model.get("provider_url"):
                rows.append({"model_id": model_id, "status": PENDING, "enabled": bool(model.get("enabled"))})
        return rows


def load_model_registry(path: str | Path) -> ModelRegistry:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return ModelRegistry(models=payload.get("models", {}))


def validate_model_registry(registry: ModelRegistry) -> list[str]:
    errors: list[str] = []
    for model_id, model in registry.models.items():
        for field in ("name", "role_support", "enabled", "is_finetuned", "decoding", "timeout_seconds"):
            if field not in model:
                errors.append(f"{model_id}: missing {field}")
    return errors


def iter_enabled_models(registry: ModelRegistry):
    return registry.iter_enabled_models()


def mark_missing_as_pending(registry: ModelRegistry) -> list[dict[str, Any]]:
    return registry.mark_missing_as_pending()


def health_check_enabled(registry: ModelRegistry) -> list[dict[str, Any]]:
    rows = registry.mark_missing_as_pending()
    for model in registry.iter_enabled_models():
        url = model.get("provider_url")
        if not url:
            continue
        try:
            response = httpx.get(str(url).rstrip("/") + "/health", timeout=model.get("timeout_seconds", 30))
            rows.append({"model_id": model["name"], "status": "ok" if response.is_success else "failed"})
        except Exception as exc:
            rows.append({"model_id": model["name"], "status": "failed", "error": str(exc)})
    return rows


if __name__ == "__main__":
    registry = load_model_registry("configs/models.yaml")
    errors = validate_model_registry(registry)
    if errors:
        raise SystemExit("\n".join(errors))
    for row in health_check_enabled(registry):
        print(row)
