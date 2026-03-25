from pydantic import BaseModel
from typing import Literal


class ClauseFlag(BaseModel):
    clause: str
    issue: str
    severity: Literal["low", "medium", "high"]


class ReviewResult(BaseModel):
    clause_flags: list[ClauseFlag]
    risk_level: Literal["low", "medium", "high"]
    summary: str
    recommendations: list[str]


class PipelineStage(BaseModel):
    name: str
    status: Literal["pending", "running", "done"]


class PipelineStatus(BaseModel):
    stages: list[PipelineStage]
    current_stage: int


class UploadResponse(BaseModel):
    success: bool
    pipeline: PipelineStatus
    result: ReviewResult | None = None
    error: str | None = None
