from app.backend.services.rag_ingestion import RagIngestionService, VALID_DOC_TYPES


def test_doc_type_contract():
    assert VALID_DOC_TYPES == {"policy", "reference_contract", "playbook"}


def test_hash_helpers_are_stable():
    assert RagIngestionService.compute_file_hash(b"abc") == RagIngestionService.compute_file_hash(b"abc")
    assert RagIngestionService.compute_chunk_hash("abc") == RagIngestionService.compute_chunk_hash("abc")
