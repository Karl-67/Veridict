"""
Document parsing service.

Fallback chain: Docling (primary) → pytesseract OCR → pdfplumber.
parser-confidence-contract thresholds: <0.6 = warning, <0.3 = blocked unless override.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal

from app.backend.core.config import Settings


# parser-confidence-contract
CONFIDENCE_WARNING_THRESHOLD = 0.6
CONFIDENCE_BLOCKED_THRESHOLD = 0.3

# kept for CanonicalDocument backwards-compatibility
LOW_CONFIDENCE_THRESHOLD = 0.45

SourceExtractor = Literal["docling", "ocr", "pdfplumber"]


@dataclass
class ParsedClause:
    id: str
    text: str
    page: int
    bbox: list[float]
    confidence: float
    source_extractor: SourceExtractor


@dataclass
class ParsedDoc:
    pages: list[dict]   # {page: int, text: str}
    clauses: list[ParsedClause]


@dataclass
class CanonicalDocument:
    document_hash: str
    parser_version: str
    used_ocr_fallback: bool
    low_confidence: bool
    clauses: list[dict]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _build_clause_uid(document_hash: str, page: int, index: int, text: str) -> str:
    digest = hashlib.sha1(f"{document_hash}:{page}:{index}:{text}".encode("utf-8")).hexdigest()
    return f"clause_{digest[:16]}"


def _char_distribution_score(text: str) -> float:
    """Fraction of printable/linguistic characters — penalises OCR garbage."""
    if not text:
        return 0.0
    printable = sum(
        1 for c in text if unicodedata.category(c)[0] in ("L", "N", "P", "Z")
    )
    return printable / len(text)


def _split_into_clauses(text: str) -> list[str]:
    prepared = re.sub(r"(?<!^)(?=\b\d+\.\s+[A-Z])", "\n\n", text)
    parts = [p.strip() for p in re.split(r"\n\s*\n|(?<=\.)\s{2,}", prepared) if _normalize_text(p)]
    return parts if parts else [_normalize_text(text)]


# ---------------------------------------------------------------------------
# Confidence blending  (parser-confidence-contract)
# ---------------------------------------------------------------------------

def compute_clause_confidence(
    extractor_confidence: float,
    source_extractor: SourceExtractor,
    text: str,
) -> float:
    """
    Blends extractor confidence + OCR signal + length/char-dist heuristics.
    Result clamped to [0, 1].
    """
    ocr_penalty = 0.15 if source_extractor == "ocr" else 0.0
    length_score = min(1.0, len(text) / 80)
    char_score = _char_distribution_score(text)

    blended = (
        extractor_confidence * 0.6
        + length_score * 0.2
        + char_score * 0.2
        - ocr_penalty
    )
    return max(0.0, min(1.0, blended))


# ---------------------------------------------------------------------------
# Extractor implementations
# ---------------------------------------------------------------------------

def parse_with_docling(path: str | Path) -> ParsedDoc | None:
    """Primary extractor. Returns None on import failure, empty output, or error."""
    try:
        from docling.document_converter import DocumentConverter  # type: ignore
    except ImportError:
        return None

    try:
        converter = DocumentConverter()
        result = converter.convert(str(path))
        doc = result.document
        doc_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()

        # Collect text keyed by page number via docling's item iterator
        page_texts: dict[int, list[str]] = {}
        for item, _ in doc.iterate_items():
            page_no: int = 1
            prov = getattr(item, "prov", None)
            if prov:
                first_prov = prov[0] if isinstance(prov, list) else prov
                page_no = int(getattr(first_prov, "page_no", 1) or 1)
            text: str = getattr(item, "text", "") or ""
            if text:
                page_texts.setdefault(page_no, []).append(text)

        # docling v2 fallback: export whole doc as markdown, treat as page 1
        if not page_texts:
            try:
                full_md: str = doc.export_to_markdown()
            except Exception:
                full_md = ""
            if full_md:
                page_texts = {1: [full_md]}

        if not page_texts:
            return None

        pages: list[dict] = []
        clauses: list[ParsedClause] = []

        for page_no in sorted(page_texts):
            combined = " ".join(page_texts[page_no])
            norm_page = _normalize_text(combined)
            pages.append({"page": page_no, "text": norm_page})

            for i, part in enumerate(_split_into_clauses(combined), start=1):
                norm = _normalize_text(part)
                if not norm:
                    continue
                clauses.append(
                    ParsedClause(
                        id=_build_clause_uid(doc_hash, page_no, i, norm),
                        text=norm,
                        page=page_no,
                        bbox=[0.0, 0.0, 0.0, 0.0],
                        confidence=compute_clause_confidence(0.92, "docling", norm),
                        source_extractor="docling",
                    )
                )

        return ParsedDoc(pages=pages, clauses=clauses) if clauses else None
    except Exception:
        return None


def parse_with_ocr_fallback(path: str | Path) -> ParsedDoc | None:
    """OCR fallback using pytesseract + pdf2image."""
    try:
        import pytesseract  # type: ignore
        from pdf2image import convert_from_path  # type: ignore
    except ImportError:
        return None

    try:
        images = convert_from_path(str(path), dpi=200)
        doc_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        pages: list[dict] = []
        clauses: list[ParsedClause] = []

        for page_no, image in enumerate(images, start=1):
            text: str = pytesseract.image_to_string(image) or ""
            norm_page = _normalize_text(text)
            pages.append({"page": page_no, "text": norm_page})

            for i, part in enumerate(_split_into_clauses(text), start=1):
                norm = _normalize_text(part)
                if not norm:
                    continue
                clauses.append(
                    ParsedClause(
                        id=_build_clause_uid(doc_hash, page_no, i, norm),
                        text=norm,
                        page=page_no,
                        bbox=[0.0, 0.0, 0.0, 0.0],
                        confidence=compute_clause_confidence(0.72, "ocr", norm),
                        source_extractor="ocr",
                    )
                )

        return ParsedDoc(pages=pages, clauses=clauses) if clauses else None
    except Exception:
        return None


def parse_with_pdfplumber_fallback(path: str | Path) -> ParsedDoc | None:
    """Final fallback using pdfplumber."""
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        return None

    try:
        raw = Path(path).read_bytes()
        doc_hash = hashlib.sha256(raw).hexdigest()
        pages: list[dict] = []
        clauses: list[ParsedClause] = []

        with pdfplumber.open(BytesIO(raw)) as pdf:
            for page_no, page in enumerate(pdf.pages, start=1):
                text: str = page.extract_text() or ""
                norm_page = _normalize_text(text)
                pages.append({"page": page_no, "text": norm_page})

                # Best-effort page bbox from word positions
                words = page.extract_words() or []
                page_bbox: list[float] = [0.0, 0.0, 0.0, 0.0]
                if words:
                    xs = [w["x0"] for w in words] + [w["x1"] for w in words]
                    ys = [w["top"] for w in words] + [w["bottom"] for w in words]
                    page_bbox = [min(xs), min(ys), max(xs), max(ys)]

                for i, part in enumerate(_split_into_clauses(text), start=1):
                    norm = _normalize_text(part)
                    if not norm:
                        continue
                    clauses.append(
                        ParsedClause(
                            id=_build_clause_uid(doc_hash, page_no, i, norm),
                            text=norm,
                            page=page_no,
                            bbox=page_bbox,
                            confidence=compute_clause_confidence(0.82, "pdfplumber", norm),
                            source_extractor="pdfplumber",
                        )
                    )

        return ParsedDoc(pages=pages, clauses=clauses) if clauses else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------

def parse_document(path: str | Path) -> ParsedDoc:
    """
    Docling → OCR → pdfplumber fallback chain.
    Raises RuntimeError if all extractors fail or return empty.
    """
    result = parse_with_docling(path)
    if result is not None:
        return result

    result = parse_with_ocr_fallback(path)
    if result is not None:
        return result

    result = parse_with_pdfplumber_fallback(path)
    if result is not None:
        return result

    raise RuntimeError(f"All extractors failed or returned empty output for: {path}")


# ---------------------------------------------------------------------------
# Legacy public API — preserved for clause_index stage
# ---------------------------------------------------------------------------

def parse_pdf_to_canonical_document(pdf_bytes: bytes, settings: Settings) -> CanonicalDocument:
    import pdfplumber

    document_hash = hashlib.sha256(pdf_bytes).hexdigest()
    clauses: list[dict] = []
    used_ocr_fallback = False

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            normalized = _normalize_text(text)
            if not normalized:
                if settings.enable_ocr_fallback:
                    import pytesseract
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
            parts = _split_into_clauses(text)
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
                        "order_index": len(clauses),
                    }
                )

    return CanonicalDocument(
        document_hash=document_hash,
        parser_version=settings.parser_version,
        used_ocr_fallback=used_ocr_fallback,
        low_confidence=not clauses or any(
            clause["extraction_confidence"] < LOW_CONFIDENCE_THRESHOLD for clause in clauses
        ),
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
            "order_index": clause.get("order_index"),
        }
        for clause in parsed_document.clauses
    ]
