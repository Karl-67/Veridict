"""
Document parsing service.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from io import BytesIO

from app.backend.core.config import Settings


LOW_CONFIDENCE_THRESHOLD = 0.45


@dataclass
class CanonicalDocument:
    document_hash: str
    parser_version: str
    used_ocr_fallback: bool
    low_confidence: bool
    clauses: list[dict]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _build_clause_uid(document_hash: str, page: int, index: int, text: str) -> str:
    digest = hashlib.sha1(f"{document_hash}:{page}:{index}:{text}".encode("utf-8")).hexdigest()
    return f"clause_{digest[:16]}"


def parse_pdf_to_canonical_document(pdf_bytes: bytes, settings: Settings) -> CanonicalDocument:
    import pdfplumber
    import pytesseract

    document_hash = hashlib.sha256(pdf_bytes).hexdigest()
    clauses: list[dict] = []
    used_ocr_fallback = False

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            normalized = _normalize_text(text)
            if not normalized:
                if settings.enable_ocr_fallback:
                    used_ocr_fallback = True
                    try:
                        page_image = page.to_image(resolution=200).original
                        text = pytesseract.image_to_string(page_image) or ""
                        normalized = _normalize_text(text)
                    except Exception:
                        text = ""
                        normalized = ""
                if not normalized:
                    continue
            parts = [part.strip() for part in re.split(r"\n\s*\n|(?<=\.)\s{2,}", text) if _normalize_text(part)]
            if not parts:
                parts = [normalized]
            for clause_index, part in enumerate(parts, start=1):
                clause_text = _normalize_text(part)
                confidence = 0.6 if used_ocr_fallback and not page.extract_text() else 0.92
                clauses.append(
                    {
                        "document_hash": document_hash,
                        "parser_version": settings.parser_version,
                        "clause_uid": _build_clause_uid(document_hash, page_index, clause_index, clause_text),
                        "page": page_index,
                        "bbox": [0.0, 0.0, 0.0, 0.0],
                        "normalized_text": clause_text,
                        "extraction_confidence": confidence,
                        "section_heading": None,
                        "ocr_used": used_ocr_fallback and not page.extract_text(),
                    }
                )

    return CanonicalDocument(
        document_hash=document_hash,
        parser_version=settings.parser_version,
        used_ocr_fallback=used_ocr_fallback,
        low_confidence=not clauses or any(clause["extraction_confidence"] < LOW_CONFIDENCE_THRESHOLD for clause in clauses),
        clauses=clauses,
    )


def build_clause_index(parsed_document: CanonicalDocument) -> list[dict]:
    return [
        {
            "document_hash": clause["document_hash"],
            "parser_version": clause["parser_version"],
            "clause_uid": clause["clause_uid"],
            "page": clause["page"],
            "bbox": clause["bbox"],
            "normalized_text": clause["normalized_text"],
            "extraction_confidence": clause["extraction_confidence"],
            "section_heading": clause.get("section_heading"),
            "ocr_used": clause.get("ocr_used", False),
        }
        for clause in parsed_document.clauses
    ]
