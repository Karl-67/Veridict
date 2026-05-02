from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.backend.core.config import get_settings
from app.backend.db.session import get_engine
from app.backend.routes.contracts import router as runs_router
from app.backend.routes.contract_management import router as contracts_router, history_router
from app.backend.routes.auth import router as auth_router
from app.backend.routes.comments import router as comments_router
from app.backend.routes.admin import router as admin_router
from app.backend.routes.workspaces import router as workspaces_router
from app.backend.routes.rag import router as rag_router
from app.backend.routes.fine_tune import router as fine_tune_router
from app.backend.routes.editor import router as editor_router
from app.backend.services.metrics import setup_metrics


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    Path(settings.document_storage_path).mkdir(parents=True, exist_ok=True)
    Path(settings.rag_storage_path).mkdir(parents=True, exist_ok=True)
    async with get_engine().begin() as connection:
        await connection.execute(text("SELECT 1"))
    model_registry = Path(settings.model_registry_path)
    if model_registry.exists():
        import yaml

        yaml.safe_load(model_registry.read_text(encoding="utf-8"))
    yield


settings = get_settings()
app = FastAPI(title="Verdict API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or settings.allowed_frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(runs_router)
app.include_router(contracts_router)
app.include_router(auth_router)
app.include_router(comments_router)
app.include_router(admin_router)
app.include_router(workspaces_router)
app.include_router(rag_router)
app.include_router(history_router)
app.include_router(fine_tune_router)
app.include_router(editor_router)
if settings.metrics_enabled:
    setup_metrics(app)
