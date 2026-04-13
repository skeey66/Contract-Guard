from pydantic import BaseModel
from backend.app.models.risk import RiskLevel, RiskDetail


class ClauseAnalysis(BaseModel):
    clause_index: int
    clause_title: str
    clause_content: str
    risk_level: RiskLevel
    confidence: float
    risks: list[RiskDetail]
    similar_references: list[str] = []
    explanation: str = ""
    # 분석 상태: "ok" | "parse_failed" | "llm_error" | "timeout"
    # 무음 폴백을 가시화하기 위한 필드 — medium은 진짜 중위험과 구분이 안 되므로 상태로 노출
    analysis_status: str = "ok"


class AnalysisResult(BaseModel):
    id: str
    document_id: str
    filename: str
    total_clauses: int
    risky_clauses: int
    clause_analyses: list[ClauseAnalysis]
    summary: str = ""


class AnalysisResponse(BaseModel):
    status: str
    result: AnalysisResult | None = None
    error: str | None = None
