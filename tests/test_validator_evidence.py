from app.backend.models.schemas import ContractEvidence, Finding, RagCitation


def test_harvey_and_kira_evidence_shapes_validate():
    citation = RagCitation(
        chunk_id="chunk-1",
        document_id="doc-1",
        version="v1",
        page=1,
        source_path="policy.pdf",
        chunk_hash="hash",
        score=0.9,
    )
    evidence = ContractEvidence(clause_id="clause-1", page=1, span=None, text="Clause text", confidence=0.95)
    finding = Finding(
        finding_id="finding-1",
        clause_uid="clause-1",
        issue_type="liability_exposure",
        severity="high",
        exploitability="high",
        business_impact="high",
        description="Issue",
        recommendation="negotiate",
        recommendation_detail="Revise clause",
        contract_evidence=[evidence],
        rag_citations=[citation],
        branch="harvey",
        agent_role="harvey_issue_discovery",
        round_number=1,
    )
    assert finding.contract_evidence[0].clause_id == "clause-1"
    assert finding.rag_citations[0].chunk_id == "chunk-1"
