from fastapi import APIRouter
from backend.app.services import chroma_service
from backend.app.contract_types import SUPPORTED_CONTRACT_TYPES

router = APIRouter()


@router.get("/kb/status")
async def kb_status():
    status = chroma_service.collection_status()
    return {
        "status": "ready" if status["count"] > 0 else "empty",
        "collection": status["name"],
        "document_count": status["count"],
        "supported_contract_types": SUPPORTED_CONTRACT_TYPES,
    }
