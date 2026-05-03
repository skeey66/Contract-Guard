from enum import Enum
from pydantic import BaseModel


class RiskLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    SAFE = "safe"


class RiskDetail(BaseModel):
    risk_type: str
    description: str
    suggestion: str
    # 본 조항 원문에서 위험 부분을 정확히 발췌한 문구 (frontend 형광펜용).
    # LLM이 채워야 하며, 본문의 정확한 substring이어야 한다 (의역·축약 금지).
    # 옵셔널 — 구버전 데이터 호환 + LLM이 채우지 못한 경우 None.
    quote: str | None = None
