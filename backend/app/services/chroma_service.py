import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from backend.app.config import settings
from backend.app.services.embedding_service import get_embeddings

_vectorstore: Chroma | None = None
_raw_client: chromadb.PersistentClient | None = None


def _get_raw_client() -> chromadb.PersistentClient:
    global _raw_client
    if _raw_client is None:
        _raw_client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    return _raw_client


def get_vectorstore() -> Chroma:
    global _vectorstore
    if _vectorstore is None:
        _vectorstore = Chroma(
            collection_name=settings.chroma_collection,
            persist_directory=settings.chroma_persist_dir,
            embedding_function=get_embeddings(),
        )
    return _vectorstore


def add_documents(
    ids: list[str],
    documents: list[str],
    metadatas: list[dict] | None = None,
):
    vs = get_vectorstore()
    docs = [
        Document(page_content=text, metadata=meta or {})
        for text, meta in zip(documents, metadatas or [{}] * len(documents))
    ]
    vs.add_documents(docs, ids=ids)


def query(
    query_text: str,
    k: int = 5,
    contract_type: str | None = None,
) -> list[tuple[Document, float]]:
    # 빈 컬렉션 체크는 count()로 — 전체 id 로딩(vs.get())은 매 쿼리마다 수천건을 로드하므로 피한다
    if _get_raw_client().get_or_create_collection(settings.chroma_collection).count() == 0:
        return []
    vs = get_vectorstore()
    filter_dict = None
    if contract_type:
        filter_dict = {
            "$or": [
                {"contract_type": contract_type},
                {"contract_type": "common"},
            ]
        }
    return vs.similarity_search_with_relevance_scores(
        query_text, k=k, filter=filter_dict,
    )


def collection_status() -> dict:
    """임베딩 모델 로딩 없이 ChromaDB 상태만 조회."""
    try:
        client = _get_raw_client()
        collection = client.get_or_create_collection(settings.chroma_collection)
        return {
            "name": collection.name,
            "count": collection.count(),
        }
    except Exception:
        return {
            "name": settings.chroma_collection,
            "count": 0,
        }


def count_by_source() -> dict[str, int]:
    """metadata.source 별 문서 수를 반환. 홈 화면 통계 표시용."""
    try:
        client = _get_raw_client()
        collection = client.get_or_create_collection(settings.chroma_collection)
        # build_kb.py 에서 사용하는 source 값 (law / aihub_약관 / aihub_판결문 / 내장)
        sources = ["law", "aihub_약관", "aihub_판결문"]
        counts: dict[str, int] = {}
        for src in sources:
            res = collection.get(where={"source": src}, include=[])
            counts[src] = len(res.get("ids", []))
        return counts
    except Exception:
        return {}
