import logging

from backend.app.services import chroma_service
from backend.app.services import bm25_service
from backend.app.config import settings

logger = logging.getLogger(__name__)

# RRF 상수 (k가 클수록 하위 순위 문서의 영향력 증가)
RRF_K = 60

# 법률 본문(source="law")은 grounding의 가장 강한 근거이므로 RRF 점수 부스트.
# 약관·판결문이 압도적으로 많아(약 4400건 vs 법률 509건) 단순 RRF로는 top-5에
# 거의 못 들어와서, 법률 조문이 검색 결과에 항상 한두 건은 노출되도록 보정한다.
LAW_BOOST = 1.5


def _rrf_combine(
    vector_results: list[tuple[str, dict]],
    bm25_results: list[tuple[str, dict]],
    top_k: int,
) -> list[dict]:
    """RRF(Reciprocal Rank Fusion)로 두 검색 결과를 결합.

    각 결과는 (doc_id, entry_dict) 형태.
    """
    scores: dict[str, float] = {}
    entries: dict[str, dict] = {}

    # 벡터 검색 순위 반영
    for rank, (doc_id, entry) in enumerate(vector_results):
        scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (RRF_K + rank + 1)
        entries[doc_id] = entry

    # BM25 검색 순위 반영
    for rank, (doc_id, entry) in enumerate(bm25_results):
        scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (RRF_K + rank + 1)
        if doc_id not in entries:
            entries[doc_id] = entry

    # 법률 본문 부스트 (source="law")
    for doc_id, entry in entries.items():
        if entry.get("metadata", {}).get("source") == "law":
            scores[doc_id] *= LAW_BOOST

    # RRF 점수 기준 정렬
    ranked_ids = sorted(scores, key=lambda x: scores[x], reverse=True)[:top_k]

    results = []
    for doc_id in ranked_ids:
        entry = entries[doc_id]
        entry["rrf_score"] = round(scores[doc_id], 6)
        results.append(entry)

    return results


def retrieve_similar(
    text: str,
    top_k: int | None = None,
    contract_type: str | None = None,
) -> list[dict]:
    """BM25 + 벡터 하이브리드 검색 후 RRF로 결합."""
    k = top_k or settings.retrieval_top_k

    # 벡터 검색 (ChromaDB)
    vector_raw = chroma_service.query(text, k=k, contract_type=contract_type)
    vector_results: list[tuple[str, dict]] = []
    for doc, score in vector_raw:
        doc_id = doc.metadata.get("id", doc.page_content[:80])
        entry = {
            "id": doc_id,
            "text": doc.page_content,
            "similarity": round(score, 4),
            "metadata": doc.metadata,
        }
        vector_results.append((doc_id, entry))

    # BM25 검색
    bm25_raw = bm25_service.search(text, k=k, contract_type=contract_type)
    bm25_results: list[tuple[str, dict]] = []
    for doc_dict, score in bm25_raw:
        doc_id = doc_dict.get("id", doc_dict["text"][:80])
        entry = {
            "id": doc_id,
            "text": doc_dict["text"],
            "similarity": round(score, 4),
            "metadata": doc_dict.get("metadata", {}),
        }
        bm25_results.append((doc_id, entry))

    # 양쪽 모두 결과가 없으면 빈 리스트
    if not vector_results and not bm25_results:
        return []

    # 한쪽만 있으면 해당 결과만 반환
    if not bm25_results:
        logger.debug("BM25 결과 없음, 벡터 검색 결과만 사용")
        return [entry for _, entry in vector_results]
    if not vector_results:
        logger.debug("벡터 검색 결과 없음, BM25 결과만 사용")
        return [entry for _, entry in bm25_results]

    # RRF 결합
    combined = _rrf_combine(vector_results, bm25_results, top_k=k)
    logger.debug(
        f"하이브리드 검색 완료: 벡터 {len(vector_results)}건, "
        f"BM25 {len(bm25_results)}건 → RRF {len(combined)}건"
    )
    return combined
