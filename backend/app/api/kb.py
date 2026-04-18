from fastapi import APIRouter
from backend.app.services import chroma_service
from backend.app.contract_types import SUPPORTED_CONTRACT_TYPES

router = APIRouter()


@router.get("/kb/status")
async def kb_status():
    status = chroma_service.collection_status()
    by_source = chroma_service.count_by_source()
    # 홈 화면 통계 카드 라벨 매핑
    categories = {
        "total": status["count"],
        "laws": by_source.get("law", 0),
        "judgments": by_source.get("aihub_판결문", 0),
        "clauses": by_source.get("aihub_약관", 0),
    }
    return {
        "status": "ready" if status["count"] > 0 else "empty",
        "collection": status["name"],
        "document_count": status["count"],
        "categories": categories,
        "supported_contract_types": SUPPORTED_CONTRACT_TYPES,
    }
