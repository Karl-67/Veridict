from app.backend.services.run_service import STAGE_SEQUENCE


def test_new_run_stages_match_stage_topology():
    assert STAGE_SEQUENCE == [
        "create_run",
        "ingest_pdf",
        "parse_ocr_normalize",
        "clause_index",
        "harvey_context_load",
        "kira_review_block",
        "admin_merge",
        "awaiting_human_review",
        "finalized",
    ]


def test_no_final_review_block_for_new_runs():
    assert "final_review_block" not in STAGE_SEQUENCE
    assert "harvey_review_block" not in STAGE_SEQUENCE
    assert "kira_context_load" not in STAGE_SEQUENCE
