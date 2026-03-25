import pdfplumber
from fastapi import APIRouter, File, HTTPException, UploadFile
from io import BytesIO

from agents.reviewer import review_contract
from models.schemas import PipelineStage, PipelineStatus, UploadResponse

router = APIRouter(prefix="/api")


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/upload", response_model=UploadResponse)
async def upload_contract(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    contents = await file.read()

    # Extract text from PDF
    text = ""
    try:
        with pdfplumber.open(BytesIO(contents)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to parse PDF file")

    if not text.strip():
        raise HTTPException(status_code=400, detail="No text could be extracted from the PDF")

    # Truncate to ~30k chars to stay within token limits
    text = text[:30000]

    stages = [
        PipelineStage(name="Harvey", status="done"),
        PipelineStage(name="Kira", status="done"),
        PipelineStage(name="Reviewer 1", status="done"),
        PipelineStage(name="Reviewer 2", status="done"),
        PipelineStage(name="Reviewer 3", status="done"),
        PipelineStage(name="Validators", status="done"),
        PipelineStage(name="Verdict", status="done"),
    ]

    try:
        result = await review_contract(text)
    except Exception as e:
        return UploadResponse(
            success=False,
            pipeline=PipelineStatus(stages=stages, current_stage=6),
            error=str(e),
        )

    return UploadResponse(
        success=True,
        pipeline=PipelineStatus(stages=stages, current_stage=7),
        result=result,
    )
