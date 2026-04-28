from pydantic import BaseModel
from backend.app.models.risk import RiskLevel, RiskDetail


class ReferenceItem(BaseModel):
    """집계 대시보드용 구조화 참고문헌. similar_references(문자열)과 별개로
    카테고리·출처 메타데이터를 보존하여 프론트에서 탭 분류·중복 제거에 사용한다.
    """
    text: str
    source: str  # ex) "민법", "주택임대차보호법", "precedent_kr", "aihub_약관" 등
    category: str  # "law" | "judgment" | "clause"
    similarity: float
    article: str | None = None


class ClauseAnalysis(BaseModel):
    clause_index: int
    clause_title: str
    clause_content: str
    risk_level: RiskLevel
    confidence: float
    risks: list[RiskDetail]
    similar_references: list[str] = []
    references_detail: list[ReferenceItem] = []  # 대시보드 집계용 구조화 참고자료
    explanation: str = ""
    # 분석 상태: "ok" | "parse_failed" | "llm_error" | "timeout"
    # 무음 폴백을 가시화하기 위한 필드 — medium은 진짜 중위험과 구분이 안 되므로 상태로 노출
    analysis_status: str = "ok"
    # 위험 조항(high/medium)에 대해 표준약관 기반으로 LLM이 생성한 권고 수정안.
    # 안전·저위험 조항이거나 생성 실패 시 None.
    suggested_rewrite: str | None = None
    # 사용자가 직접 입력한 최종 수정안. None이면 미수정. 빈 문자열은 의도적 공란으로 취급하지 않고 None으로 정규화.
    # 우선순위: user_override > suggested_rewrite > clause_content
    user_override: str | None = None
    user_override_at: str | None = None  # ISO8601 UTC, 마지막 수정 시각


class AnalysisResult(BaseModel):
    id: str
    document_id: str
    filename: str
    total_clauses: int
    risky_clauses: int
    clause_analyses: list[ClauseAnalysis]
    summary: str = ""
    # 사이드바 이력 표시에 사용. 기존 저장분과의 하위 호환을 위해 Optional.
    contract_type: str | None = None  # "lease" | "sales" | "employment" | ...
    created_at: str | None = None  # ISO8601 UTC. 누락 시 파일 mtime으로 폴백.


class AnalysisResponse(BaseModel):
    status: str
    result: AnalysisResult | None = None
    error: str | None = None
