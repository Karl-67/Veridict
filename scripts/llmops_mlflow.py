from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, Iterator


DEFAULT_EXPERIMENT = "veridict-training"


def enabled() -> bool:
    return bool(os.getenv("MLFLOW_TRACKING_URI", "").strip())


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def dataset_version(paths: list[str | Path]) -> str:
    digest = hashlib.sha256()
    for raw_path in sorted(Path(p) for p in paths):
        if not raw_path.exists():
            continue
        digest.update(str(raw_path).encode("utf-8"))
        digest.update(sha256_file(raw_path).encode("utf-8"))
    return digest.hexdigest()


def _mlflow():
    import mlflow

    tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "").strip()
    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(os.getenv("MLFLOW_EXPERIMENT", DEFAULT_EXPERIMENT))
    return mlflow


@contextmanager
def start_run(run_name: str, tags: dict[str, Any] | None = None, nested: bool = False) -> Iterator[Any | None]:
    if not enabled():
        with nullcontext(None) as run:
            yield run
        return
    previous_env_run_id = os.environ.pop("MLFLOW_RUN_ID", None)
    try:
        mlflow = _mlflow()
        with mlflow.start_run(run_name=run_name, nested=nested) as run:
            if tags:
                mlflow.set_tags({k: str(v) for k, v in tags.items() if v is not None})
            yield run
    except Exception as exc:
        print(f"[mlflow] disabled for this run: {exc}", flush=True)
        with nullcontext(None) as run:
            yield run
    finally:
        if previous_env_run_id:
            os.environ["MLFLOW_RUN_ID"] = previous_env_run_id


def log_params(params: dict[str, Any]) -> None:
    if not enabled():
        return
    try:
        mlflow = _mlflow()
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, (dict, list, tuple, set)):
                value = json.dumps(value, sort_keys=True)
            mlflow.log_param(key, value)
    except Exception as exc:
        print(f"[mlflow] param logging skipped: {exc}", flush=True)


def log_metrics(metrics: dict[str, Any], prefix: str = "") -> None:
    if not enabled():
        return
    try:
        mlflow = _mlflow()
        for key, value in metrics.items():
            if isinstance(value, bool):
                value = float(value)
            if isinstance(value, (int, float)):
                mlflow.log_metric(f"{prefix}{key}", float(value))
    except Exception as exc:
        print(f"[mlflow] metric logging skipped: {exc}", flush=True)


def log_artifact(path: str | Path, artifact_path: str | None = None) -> None:
    if not enabled():
        return
    try:
        _mlflow().log_artifact(str(path), artifact_path=artifact_path)
    except Exception as exc:
        print(f"[mlflow] artifact logging skipped: {exc}", flush=True)


def log_dict(payload: dict[str, Any], artifact_file: str) -> None:
    if not enabled():
        return
    try:
        _mlflow().log_dict(payload, artifact_file)
    except Exception as exc:
        print(f"[mlflow] dict artifact logging skipped: {exc}", flush=True)
