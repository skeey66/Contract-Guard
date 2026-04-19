from fastapi import APIRouter
from backend.app.services import chroma_service
from backend.app.contract_types import SUPPORTED_CONTRACT_TYPES

router = APIRouter()


@router.get("/kb/status")
async def kb_status():
    status = chroma_service.collection_status()
    by_source = chroma_service.count_by_source()

    # 카드 라벨에 맞춰 source를 카테고리로 합산
    # - laws: legalize-kr 'law' + 내장 법률명 source (민법, 주택임대차보호법 등)
    # - judgments: 한국 법원 판례(precedent_kr) + AI Hub 판결문 + 내장 판례/실무
    # - clauses: AI Hub 약관 + 내장 약관규제법/판례, 실무
    JUDGMENT_SOURCES = {"precedent_kr", "aihub_판결문", "판례/실무"}
    CLAUSE_SOURCES = {"aihub_약관", "약관규제법/판례", "실무"}

    laws = 0
    judgments = 0
    clauses = 0
    for src, cnt in by_source.items():
        if src in JUDGMENT_SOURCES:
            judgments += cnt
        elif src in CLAUSE_SOURCES:
            clauses += cnt
        else:
            # 'law' 및 내장 법률명(민법/주택임대차보호법/근로기준법 등) 모두 법률로 집계
            laws += cnt

    categories = {
        "total": status["count"],
        "laws": laws,
        "judgments": judgments,
        "clauses": clauses,
    }
    return {
        "status": "ready" if status["count"] > 0 else "empty",
        "collection": status["name"],
        "document_count": status["count"],
        "categories": categories,
        "supported_contract_types": SUPPORTED_CONTRACT_TYPES,
    }
