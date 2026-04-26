import pytest

from app.backend.services.rag_retrieval import HarveyRagRetriever, RagAccessForbidden


def test_kira_caller_is_forbidden():
    with pytest.raises(RagAccessForbidden):
        HarveyRagRetriever(session=None, caller_role="kira")  # type: ignore[arg-type]
