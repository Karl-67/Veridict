"""
Routes for contract clause listing, editing, finding accept/dismiss,
and document annotations (anchored comments / suggestions).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

import io

from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.backend.db.models import (
    DocumentAnnotationRecord,
    FindingRecord,
    HumanReviewRecord,
    ParsedClauseRecord,
    RunRecord,
)
from app.backend.db.session import DbSession
from app.backend.models.schemas import DocumentAnnotationCreate, DocumentAnnotationOut
from app.backend.services.auth_service import require_auth

router = APIRouter(prefix="/api", tags=["editor"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ClauseOut(BaseModel):
    clause_uid: str
    page_number: int
    normalized_text: str
    bbox: list[float]


class ClauseEditBody(BaseModel):
    text: str


class ContractEditsOut(BaseModel):
    edits: dict  # clause_uid → {text, edited_at}


class AcceptFindingBody(BaseModel):
    custom_text: Optional[str] = None  # override replacement text


# ---------------------------------------------------------------------------
# Clause listing
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/clauses", response_model=list[ClauseOut])
async def list_clauses(run_id: str, db: DbSession) -> list[ClauseOut]:
    result = await db.execute(
        select(ParsedClauseRecord)
        .where(ParsedClauseRecord.run_id == run_id)
        .order_by(ParsedClauseRecord.page_number.asc())
    )
    clauses = result.scalars().all()
    return [
        ClauseOut(
            clause_uid=c.clause_uid,
            page_number=c.page_number,
            normalized_text=c.normalized_text,
            bbox=[c.bbox_x0 or 0.0, c.bbox_y0 or 0.0, c.bbox_x1 or 0.0, c.bbox_y1 or 0.0],
        )
        for c in clauses
    ]


# ---------------------------------------------------------------------------
# Contract-level clause edits (stored on the run)
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/contract-edits")
async def get_contract_edits(run_id: str, db: DbSession) -> dict:
    run = (await db.execute(select(RunRecord).where(RunRecord.id == run_id))).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run.contract_edits or {}


@router.get("/runs/{run_id}/export-edited")
async def export_edited_contract(run_id: str, db: DbSession) -> StreamingResponse:
    """Export the contract as a DOCX with AI findings inline and all clause edits applied."""
    run = (await db.execute(select(RunRecord).where(RunRecord.id == run_id))).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    clauses = (await db.execute(
        select(ParsedClauseRecord)
        .where(ParsedClauseRecord.run_id == run_id)
        .order_by(ParsedClauseRecord.page_number.asc(), ParsedClauseRecord.bbox_y0.asc())
    )).scalars().all()

    findings_rows = (await db.execute(
        select(FindingRecord)
        .where(FindingRecord.run_id == run_id, FindingRecord.dismissed_at.is_(None))
        .order_by(FindingRecord.severity.asc())
    )).scalars().all()

    annotations_rows = (await db.execute(
        select(DocumentAnnotationRecord)
        .where(
            DocumentAnnotationRecord.run_id == run_id,
            DocumentAnnotationRecord.status.not_in(["dismissed", "deleted"]),
        )
        .order_by(DocumentAnnotationRecord.created_at.asc())
    )).scalars().all()

    # Index findings and annotations by clause_uid for quick lookup
    findings_by_clause: dict[str, list] = {}
    for f in findings_rows:
        findings_by_clause.setdefault(f.clause_uid or "", []).append(f)

    annotations_by_clause: dict[str, list] = {}
    for a in annotations_rows:
        annotations_by_clause.setdefault(a.clause_uid or "", []).append(a)

    edits: dict = run.contract_edits or {}

    try:
        from docx import Document
        from docx.shared import Pt, RGBColor
        from docx.enum.text import WD_COLOR_INDEX

        doc = Document()
        doc.core_properties.title = run.original_filename or "Contract"

        # Title
        title_para = doc.add_heading(run.original_filename or "Contract", level=1)

        _SEV_COLOR = {
            "critical": RGBColor(0xC4, 0x43, 0x2B),
            "high":     RGBColor(0xC4, 0x43, 0x2B),
            "medium":   RGBColor(0xC8, 0x97, 0x3E),
            "low":      RGBColor(0x3D, 0x8B, 0x5E),
        }

        current_page = None
        for clause in clauses:
            if clause.page_number != current_page:
                current_page = clause.page_number
                doc.add_paragraph(f"─── Page {current_page} ───", style="Heading 2")

            clause_edit = edits.get(clause.clause_uid)
            clause_findings = findings_by_clause.get(clause.clause_uid or "", [])
            clause_annotations = annotations_by_clause.get(clause.clause_uid or "", [])

            # Clause body paragraph
            para = doc.add_paragraph()
            run_obj = para.add_run(clause.normalized_text)
            run_obj.font.size = Pt(10)

            # If there's an accepted edit, add it below in green
            if clause_edit:
                edit_para = doc.add_paragraph()
                edit_run = edit_para.add_run("✎ Accepted edit: ")
                edit_run.bold = True
                edit_run.font.color.rgb = RGBColor(0x3D, 0x8B, 0x5E)
                edit_run.font.size = Pt(9)
                body_run = edit_para.add_run(clause_edit["text"])
                body_run.font.color.rgb = RGBColor(0x3D, 0x8B, 0x5E)
                body_run.font.size = Pt(9)

            # AI findings for this clause
            for f in clause_findings:
                color = _SEV_COLOR.get(f.severity or "medium", RGBColor(0x44, 0x44, 0x44))
                finding_para = doc.add_paragraph()
                label = finding_para.add_run(f"⚠ AI [{(f.severity or 'medium').upper()}]: ")
                label.bold = True
                label.font.color.rgb = color
                label.font.size = Pt(9)
                issue_run = finding_para.add_run(f.issue or "")
                issue_run.font.color.rgb = color
                issue_run.font.size = Pt(9)
                if f.recommended_change:
                    rec_para = doc.add_paragraph()
                    rec_label = rec_para.add_run("  → Suggested rewrite: ")
                    rec_label.italic = True
                    rec_label.font.size = Pt(8.5)
                    rec_label.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
                    rec_text = rec_para.add_run(f.recommended_change)
                    rec_text.font.size = Pt(8.5)
                    rec_text.font.color.rgb = RGBColor(0x33, 0x33, 0x99)

            # Human annotations for this clause
            for ann in clause_annotations:
                ann_para = doc.add_paragraph()
                prefix = "💬 Comment" if ann.annotation_type == "comment" else "✏ Suggestion"
                ann_label = ann_para.add_run(f"{prefix}: ")
                ann_label.bold = True
                ann_label.font.size = Pt(9)
                ann_label.font.color.rgb = RGBColor(0x44, 0x44, 0x99)
                ann_body = ann_para.add_run(ann.body or "")
                ann_body.font.size = Pt(9)
                if ann.suggested_replacement:
                    sug_para = doc.add_paragraph()
                    sug_label = sug_para.add_run("  → Replacement: ")
                    sug_label.italic = True
                    sug_label.font.size = Pt(8.5)
                    sug_label.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
                    sug_text = sug_para.add_run(ann.suggested_replacement)
                    sug_text.font.size = Pt(8.5)
                    sug_text.font.color.rgb = RGBColor(0x33, 0x33, 0x99)

            doc.add_paragraph()  # blank line between clauses

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)

        base = (run.original_filename or "contract").rsplit(".", 1)[0]
        filename = f"{base}-edited.docx"
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except ImportError:
        # Fallback to plain text if python-docx is not installed
        lines = [run.original_filename or "Contract", ""]
        current_page = None
        for clause in clauses:
            if clause.page_number != current_page:
                current_page = clause.page_number
                lines.append(f"--- Page {current_page} ---")
            clause_edit = edits.get(clause.clause_uid)
            text = clause_edit["text"] if clause_edit else clause.normalized_text
            lines.append(text)
            for f in findings_by_clause.get(clause.clause_uid or "", []):
                lines.append(f"  [AI {f.severity}] {f.issue}")
            lines.append("")
        base = (run.original_filename or "contract").rsplit(".", 1)[0]
        return PlainTextResponse(
            "\n".join(lines),
            headers={"Content-Disposition": f'attachment; filename="{base}-edited.txt"'},
        )


@router.put("/runs/{run_id}/contract-edits/{clause_uid}", status_code=status.HTTP_200_OK)
async def save_clause_edit(
    run_id: str,
    clause_uid: str,
    body: ClauseEditBody,
    db: DbSession,
    token: dict = Depends(require_auth),
) -> dict:
    run = (await db.execute(select(RunRecord).where(RunRecord.id == run_id))).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    edits: dict = dict(run.contract_edits or {})
    edits[clause_uid] = {"text": body.text, "edited_at": datetime.utcnow().isoformat()}
    run.contract_edits = edits
    flag_modified(run, "contract_edits")
    await db.commit()
    return {"clause_uid": clause_uid, "text": body.text}


# ---------------------------------------------------------------------------
# Finding accept / dismiss
# ---------------------------------------------------------------------------


@router.post("/runs/{run_id}/findings/{finding_id}/accept", status_code=status.HTTP_200_OK)
async def accept_finding(
    run_id: str,
    finding_id: str,
    db: DbSession,
    body: AcceptFindingBody | None = Body(default=None),
    token: dict = Depends(require_auth),
) -> dict:
    finding = (await db.execute(
        select(FindingRecord).where(FindingRecord.id == finding_id, FindingRecord.run_id == run_id)
    )).scalar_one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    # Determine replacement text: explicit override -> finding.recommended_change -> None
    body = body or AcceptFindingBody()
    replacement_text = body.custom_text or finding.recommended_change

    applied_text: str | None = None
    if replacement_text and finding.clause_uid:
        run = (await db.execute(select(RunRecord).where(RunRecord.id == run_id))).scalar_one_or_none()
        if run:
            edits: dict = dict(run.contract_edits or {})
            edits[finding.clause_uid] = {
                "text": replacement_text,
                "edited_at": datetime.utcnow().isoformat(),
            }
            run.contract_edits = edits
            flag_modified(run, "contract_edits")
            applied_text = replacement_text

    # Mark finding as accepted so it disappears from the review queue
    finding.accepted_at = datetime.utcnow()
    annotation_result = await db.execute(
        select(DocumentAnnotationRecord).where(
            DocumentAnnotationRecord.run_id == run_id,
            DocumentAnnotationRecord.finding_id == finding_id,
            DocumentAnnotationRecord.status == "open",
        )
    )
    for annotation in annotation_result.scalars().all():
        annotation.status = "accepted"

    # Audit trail
    record = HumanReviewRecord(
        id=str(uuid.uuid4()),
        run_id=run_id,
        finding_id=finding_id,
        reviewer_id=token["sub"],
        reviewer_role="human_reviewer",
        action="edit",
        original_finding_snapshot={"issue": finding.issue, "severity": finding.severity},
        edited_finding_snapshot={
            "accepted_recommendation": finding.recommendation,
            "applied_text": applied_text,
        },
        edit_justification="accepted",
        is_run_level=False,
    )
    db.add(record)
    await db.commit()
    return {"finding_id": finding_id, "accepted": True, "applied_text": applied_text}


@router.post("/runs/{run_id}/findings/{finding_id}/dismiss", status_code=status.HTTP_200_OK)
async def dismiss_finding(
    run_id: str,
    finding_id: str,
    db: DbSession,
    token: dict = Depends(require_auth),
) -> dict:
    finding = (await db.execute(
        select(FindingRecord).where(FindingRecord.id == finding_id, FindingRecord.run_id == run_id)
    )).scalar_one_or_none()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    finding.dismissed_at = datetime.utcnow()
    annotation_result = await db.execute(
        select(DocumentAnnotationRecord).where(
            DocumentAnnotationRecord.run_id == run_id,
            DocumentAnnotationRecord.finding_id == finding_id,
            DocumentAnnotationRecord.status == "open",
        )
    )
    for annotation in annotation_result.scalars().all():
        annotation.status = "dismissed"

    # Audit trail
    record = HumanReviewRecord(
        id=str(uuid.uuid4()),
        run_id=run_id,
        finding_id=finding_id,
        reviewer_id=token["sub"],
        reviewer_role="human_reviewer",
        action="reject",
        original_finding_snapshot={"issue": finding.issue, "severity": finding.severity},
        is_run_level=False,
    )
    db.add(record)
    await db.commit()
    return {"finding_id": finding_id, "dismissed": True}


# ---------------------------------------------------------------------------
# Document annotations — anchored comments and suggestions
# ---------------------------------------------------------------------------


def _annotation_to_out(a: DocumentAnnotationRecord) -> DocumentAnnotationOut:
    author_name = None
    if a.author:
        author_name = getattr(a.author, "display_name", None)
    return DocumentAnnotationOut(
        id=a.id,
        run_id=a.run_id,
        clause_uid=a.clause_uid,
        page_number=a.page_number,
        selected_text=a.selected_text,
        span_start=a.span_start,
        span_end=a.span_end,
        annotation_type=a.annotation_type,
        body=a.body,
        suggested_replacement=a.suggested_replacement,
        status=a.status,
        source=a.source,
        finding_id=a.finding_id,
        author_id=a.author_id,
        author_name=author_name,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


@router.get("/runs/{run_id}/annotations", response_model=list[DocumentAnnotationOut])
async def list_annotations(
    run_id: str,
    db: DbSession,
    clause_uid: str | None = None,
) -> list[DocumentAnnotationOut]:
    q = (
        select(DocumentAnnotationRecord)
        .options(selectinload(DocumentAnnotationRecord.author))
        .where(
            DocumentAnnotationRecord.run_id == run_id,
            DocumentAnnotationRecord.status.not_in(["accepted", "dismissed", "deleted"]),
        )
        .order_by(DocumentAnnotationRecord.created_at.asc())
    )
    if clause_uid:
        q = q.where(DocumentAnnotationRecord.clause_uid == clause_uid)
    rows = (await db.execute(q)).scalars().all()
    return [_annotation_to_out(a) for a in rows]


@router.post("/runs/{run_id}/annotations", response_model=DocumentAnnotationOut, status_code=status.HTTP_201_CREATED)
async def create_annotation(
    run_id: str,
    body: DocumentAnnotationCreate,
    db: DbSession,
    token: dict = Depends(require_auth),
) -> DocumentAnnotationOut:
    if body.annotation_type not in ("comment", "suggestion"):
        raise HTTPException(status_code=400, detail="annotation_type must be comment or suggestion")
    if body.annotation_type == "suggestion" and not (body.suggested_replacement or "").strip():
        raise HTTPException(status_code=400, detail="Suggestions require suggested_replacement")
    record = DocumentAnnotationRecord(
        id=str(uuid.uuid4()),
        run_id=run_id,
        clause_uid=body.clause_uid,
        annotation_type=body.annotation_type,
        body=body.body.strip(),
        suggested_replacement=body.suggested_replacement,
        selected_text=body.selected_text,
        span_start=body.span_start,
        span_end=body.span_end,
        page_number=body.page_number,
        source="human",
        author_id=token["sub"],
        status="open",
    )
    db.add(record)
    await db.flush()
    await db.refresh(record, ["author"])
    return _annotation_to_out(record)


@router.delete("/runs/{run_id}/annotations/{annotation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_annotation(
    run_id: str,
    annotation_id: str,
    db: DbSession,
    token: dict = Depends(require_auth),
) -> None:
    record = (await db.execute(
        select(DocumentAnnotationRecord).where(
            DocumentAnnotationRecord.id == annotation_id,
            DocumentAnnotationRecord.run_id == run_id,
        )
    )).scalar_one_or_none()
    if not record or record.status == "deleted":
        raise HTTPException(status_code=404, detail="Annotation not found")
    if record.source == "human" and record.author_id != token["sub"]:
        raise HTTPException(status_code=403, detail="Cannot delete another user's annotation")
    record.status = "deleted"
    await db.commit()
