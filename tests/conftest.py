from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

os.environ.setdefault("POSTGRES_DSN", "postgresql://verdict:verdict@localhost:5432/verdict")
os.environ.setdefault("EMBEDDING_PROVIDER", "hash")


@pytest.fixture
def sample_contract_pdf() -> Path:
    return Path("test_contract.pdf")


@pytest.fixture
def auth_admin_user() -> dict:
    return {"sub": "user-admin", "org_id": "tenant-a", "org_role": "org_admin"}


@pytest.fixture
def auth_member_user() -> dict:
    return {"sub": "user-member", "org_id": "tenant-a", "org_role": "member"}


@pytest.fixture
def seeded_rag_corpus() -> list[dict]:
    return [{"tenant_id": "tenant-a", "chunk_id": "chunk-1", "text": "A sample policy clause."}]
