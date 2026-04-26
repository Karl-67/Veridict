from app.backend.services.parser import compute_clause_confidence


def test_confidence_threshold_ordering():
    strong = compute_clause_confidence(0.92, "docling", "This is a well extracted contract clause with enough text.")
    weak = compute_clause_confidence(0.1, "ocr", "%%")
    assert strong > 0.6
    assert weak < 0.3
