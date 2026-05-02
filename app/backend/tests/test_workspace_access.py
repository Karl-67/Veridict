"""Tests for assert_run_access access-control logic."""
from __future__ import annotations

import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi import HTTPException


def _make_run(tenant_id: str) -> MagicMock:
    run = MagicMock()
    run.tenant_id = tenant_id
    return run


def _make_contract(workspace_id: str | None, org_id: str | None) -> MagicMock:
    c = MagicMock()
    c.workspace_id = workspace_id
    c.org_id = org_id
    return c


def _make_version(contract_id: int) -> MagicMock:
    v = MagicMock()
    v.contract_id = contract_id
    return v


def _execute_result(value) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _make_db(
    run=None,
    version=None,
    contract=None,
    member=None,
) -> AsyncMock:
    """Build a mock AsyncSession.

    get() is called for RunRecord and ContractRecord (in that order).
    execute() is called for ContractVersionRecord then WorkspaceMemberRecord.
    """
    db = MagicMock()

    # db.get: first call → run, second call → contract
    db.get = AsyncMock(side_effect=[run, contract])

    # db.execute: first call → version result, second call → member result
    db.execute = AsyncMock(side_effect=[
        _execute_result(version),
        _execute_result(member),
    ])
    return db


# ---------------------------------------------------------------------------
# Import smoke test
# ---------------------------------------------------------------------------


def test_import_app_main():
    """Catch missing-module crashes before they reach the deployed image."""
    import app.backend.main  # noqa: F401


# ---------------------------------------------------------------------------
# Missing and cross-tenant runs
# ---------------------------------------------------------------------------


async def test_missing_run_raises_404():
    from app.backend.services.workspace_access import assert_run_access

    db = _make_db(run=None)
    token = {"sub": "user-1", "org_id": "org-1", "org_role": "member"}
    with pytest.raises(HTTPException) as exc_info:
        await assert_run_access(db, "run-x", token)
    assert exc_info.value.status_code == 404


async def test_cross_tenant_run_raises_404():
    from app.backend.services.workspace_access import assert_run_access

    run = _make_run(tenant_id="other-org")
    db = _make_db(run=run)
    token = {"sub": "user-1", "org_id": "org-1", "org_role": "member"}
    with pytest.raises(HTTPException) as exc_info:
        await assert_run_access(db, "run-x", token)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Standalone (legacy) runs — no contract_version link
# ---------------------------------------------------------------------------


async def test_standalone_same_tenant_allowed():
    from app.backend.services.workspace_access import assert_run_access

    run = _make_run(tenant_id="org-1")
    # execute returns None (no version), get for contract never reached
    db = MagicMock()
    db.get = AsyncMock(return_value=run)
    db.execute = AsyncMock(return_value=_execute_result(None))

    token = {"sub": "user-1", "org_id": "org-1", "org_role": "member"}
    result = await assert_run_access(db, "run-1", token)
    assert result is run


async def test_standalone_solo_user_matched_by_sub():
    """User with no org: tenant_id == sub."""
    from app.backend.services.workspace_access import assert_run_access

    run = _make_run(tenant_id="user-solo")
    db = MagicMock()
    db.get = AsyncMock(return_value=run)
    db.execute = AsyncMock(return_value=_execute_result(None))

    token = {"sub": "user-solo", "org_id": None, "org_role": "member"}
    result = await assert_run_access(db, "run-1", token)
    assert result is run


# ---------------------------------------------------------------------------
# Workspace-scoped runs via contract_version join
# ---------------------------------------------------------------------------


async def test_org_admin_can_access_linked_run():
    from app.backend.services.workspace_access import assert_run_access

    run = _make_run(tenant_id="org-1")
    version = _make_version(contract_id=42)
    contract = _make_contract(workspace_id="ws-1", org_id="org-1")

    db = _make_db(run=run, version=version, contract=contract, member=None)
    token = {"sub": "admin-user", "org_id": "org-1", "org_role": "org_admin"}
    result = await assert_run_access(db, "run-1", token)
    assert result is run


async def test_workspace_member_can_access_linked_run():
    from app.backend.services.workspace_access import assert_run_access

    run = _make_run(tenant_id="org-1")
    version = _make_version(contract_id=42)
    contract = _make_contract(workspace_id="ws-1", org_id="org-1")
    member = MagicMock()

    db = _make_db(run=run, version=version, contract=contract, member=member)
    token = {"sub": "user-1", "org_id": "org-1", "org_role": "member"}
    result = await assert_run_access(db, "run-1", token)
    assert result is run


async def test_non_member_org_user_gets_403():
    from app.backend.services.workspace_access import assert_run_access

    run = _make_run(tenant_id="org-1")
    version = _make_version(contract_id=42)
    contract = _make_contract(workspace_id="ws-1", org_id="org-1")

    db = _make_db(run=run, version=version, contract=contract, member=None)
    token = {"sub": "user-outsider", "org_id": "org-1", "org_role": "member"}
    with pytest.raises(HTTPException) as exc_info:
        await assert_run_access(db, "run-1", token)
    assert exc_info.value.status_code == 403


async def test_org_admin_wrong_org_gets_403():
    """org_admin from a different org is not bypassed."""
    from app.backend.services.workspace_access import assert_run_access

    run = _make_run(tenant_id="org-1")
    version = _make_version(contract_id=42)
    contract = _make_contract(workspace_id="ws-1", org_id="org-1")

    db = _make_db(run=run, version=version, contract=contract, member=None)
    token = {"sub": "admin-other", "org_id": "org-2", "org_role": "org_admin"}
    with pytest.raises(HTTPException) as exc_info:
        await assert_run_access(db, "run-1", token)
    assert exc_info.value.status_code == 404  # cross-tenant gate fires first
