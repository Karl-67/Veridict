from app.backend.services.run_service import STAGE_SEQUENCE


def test_lifecycle_reaches_human_review_before_finalized():
    assert STAGE_SEQUENCE[-2:] == ["awaiting_human_review", "finalized"]
    assert STAGE_SEQUENCE[4:7] == ["harvey_context_load", "kira_review_block", "admin_merge"]
