from fastapi import APIRouter
from backend.app.services import chroma_service
from backend.app.contract_types import SUPPORTED_CONTRACT_TYPES

router = APIRouter()


@router.get("/kb/status")
async def kb_status():
    status = chroma_service.collection_status()
    by_source = chroma_service.count_by_source()

    # 카드 라벨에 맞춰 source를 카테고리로 합산
    # - laws: legalize-kr 'law' + 내장 법률명 + 약관규제법/판례
    # - safe_clauses: AI Hub 유리 약관(safe_clause) + 내장 실무
    # - judgments: 한국 법원 판례(precedent_kr) + AI Hub 판결문 + 내장 판례/실무
    # - unfair_clauses: AI Hub 불리 약관(unfair_clause)
    JUDGMENT_SOURCES = {"precedent_kr", "aihub_판결문", "판례/실무"}
    SAFE_CLAUSE_SOURCES = {"safe_clause", "실무"}
    UNFAIR_CLAUSE_SOURCES = {"unfair_clause"}
    LAW_LIKE_OTHER = {"약관규제법/판례"}

    laws = 0
    safe_clauses = 0
    judgments = 0
    unfair_clauses = 0
    for src, cnt in by_source.items():
        if src in JUDGMENT_SOURCES:
            judgments += cnt
        elif src in SAFE_CLAUSE_SOURCES:
            safe_clauses += cnt
        elif src in UNFAIR_CLAUSE_SOURCES:
            unfair_clauses += cnt
        else:
            # 'law' / 내장 법률명(민법, 주택임대차보호법, 근로기준법 등) / 약관규제법은 법률로 집계
            laws += cnt

    categories = {
        "total": status["count"],
        "laws": laws,
        "safe_clauses": safe_clauses,
        "judgments": judgments,
        "unfair_clauses": unfair_clauses,
        # 하위 호환: 프론트가 'clauses' 키만 보던 경우를 위해 합계 제공
        "clauses": safe_clauses + unfair_clauses,
    }
    return {
        "status": "ready" if status["count"] > 0 else "empty",
        "collection": status["name"],
        "document_count": status["count"],
        "categories": categories,
        "supported_contract_types": SUPPORTED_CONTRACT_TYPES,
    }
