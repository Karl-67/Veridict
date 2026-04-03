export interface ClauseFlag {
  clause: string;
  issue: string;
  severity: "low" | "medium" | "high";
}

export interface ReviewResult {
  clause_flags: ClauseFlag[];
  risk_level: "low" | "medium" | "high";
  summary: string;
  recommendations: string[];
}

export interface PipelineStage {
  name: string;
  status: "pending" | "running" | "done";
}

export interface PipelineStatus {
  stages: PipelineStage[];
  current_stage: number;
}

export interface UploadResponse {
  success: boolean;
  pipeline: PipelineStatus;
  result: ReviewResult | null;
  error: string | null;
}
