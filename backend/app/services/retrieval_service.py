from backend.app.services import chroma_service
from backend.app.config import settings


def retrieve_similar(
    text: str,
    top_k: int | None = None,
    contract_type: str | None = None,
) -> list[dict]:
    """텍스트와 유사한 법률 조항을 ChromaDB에서 검색."""
    k = top_k or settings.retrieval_top_k
    results = chroma_service.query(text, k=k, contract_type=contract_type)

    similar = []
    for doc, score in results:
        if score >= settings.retrieval_min_score:
            similar.append({
                "id": doc.metadata.get("id", ""),
                "text": doc.page_content,
                "similarity": round(score, 4),
                "metadata": doc.metadata,
            })

    return similar
