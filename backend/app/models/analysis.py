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
    # 위험 조항(high/medium)에 대해 표준약관 기반으로 LLM이 생성한 권고 수정안.
    # 안전·저위험 조항이거나 생성 실패 시 None.
    suggested_rewrite: str | None = None


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
