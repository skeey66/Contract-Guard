import json
import pickle
import re
import logging
from pathlib import Path

from rank_bm25 import BM25Okapi

from backend.app.config import settings, DATA_DIR

logger = logging.getLogger(__name__)

_BM25_DIR = Path(DATA_DIR) / "bm25"
_bm25_indices: dict[str, BM25Okapi] = {}
_bm25_docs: dict[str, list[dict]] = {}


# 긴 접미사부터 매칭하기 위해 길이 내림차순
_KO_PARTICLES = sorted(
    [
        "으로서", "으로써", "에게서", "에서는", "에서도", "까지는",
        "로서", "로써", "에게", "한테", "까지", "부터", "이나", "에서",
        "으로", "이다", "한다", "된다", "했다", "하다", "되다", "이며",
        "으며", "처럼", "보다", "마저", "라도", "에도",
        "은", "는", "이", "가", "을", "를", "의", "에", "도", "만",
        "과", "와", "나", "로", "며",
    ],
    key=len,
    reverse=True,
)


def _strip_particle(tok: str) -> str:
    # 조사/어미를 제거하여 어간 후보를 얻음. 어간이 너무 짧아지면 원본 유지.
    for p in _KO_PARTICLES:
        if len(tok) > len(p) + 1 and tok.endswith(p):
            return tok[: -len(p)]
    return tok


def _tokenize(text: str) -> list[str]:
    """한국어 텍스트를 토큰화.

    원본 토큰과 조사 제거 후 어간을 모두 포함하여 BM25 recall을 향상시킨다.
    (예: "근로자는" → ["근로자는", "근로자"])
    """
    raw_tokens = re.findall(r"[가-힣a-zA-Z0-9]+", text)
    out = []
    seen = set()
    for t in raw_tokens:
        if len(t) <= 1:
            continue
        if t not in seen:
            out.append(t)
            seen.add(t)
        stripped = _strip_particle(t)
        if stripped != t and len(stripped) > 1 and stripped not in seen:
            out.append(stripped)
            seen.add(stripped)
    return out


def _index_path(contract_type: str) -> Path:
    return _BM25_DIR / f"{contract_type}_bm25.pkl"


def _docs_path(contract_type: str) -> Path:
    return _BM25_DIR / f"{contract_type}_docs.json"


def build_index(items: list[dict], contract_type: str):
    """BM25 인덱스 구축 및 디스크 저장.

    items: [{"id": ..., "text": ..., "metadata": ...}, ...]
    """
    _BM25_DIR.mkdir(parents=True, exist_ok=True)

    # contract_type별 필터 또는 common 포함
    filtered = [
        item for item in items
        if item.get("metadata", {}).get("contract_type") in (contract_type, "common")
    ]
    if not filtered:
        logger.warning(f"BM25 인덱스 구축 대상 0건: {contract_type}")
        return

    corpus = [_tokenize(item["text"]) for item in filtered]
    bm25 = BM25Okapi(corpus)

    with open(_index_path(contract_type), "wb") as f:
        pickle.dump(bm25, f)
    with open(_docs_path(contract_type), "w", encoding="utf-8") as f:
        json.dump(filtered, f, ensure_ascii=False)

    _bm25_indices[contract_type] = bm25
    _bm25_docs[contract_type] = filtered
    logger.info(f"BM25 인덱스 구축 완료: {contract_type} ({len(filtered)}건)")


def build_all_indices(items: list[dict]):
    """전체 데이터에서 계약 유형별 BM25 인덱스 일괄 구축."""
    contract_types = set()
    for item in items:
        ct = item.get("metadata", {}).get("contract_type")
        if ct and ct != "common":
            contract_types.add(ct)

    for ct in contract_types:
        build_index(items, ct)


def _load_index(contract_type: str) -> bool:
    """디스크에서 BM25 인덱스 로드. 성공 시 True."""
    idx_path = _index_path(contract_type)
    doc_path = _docs_path(contract_type)
    if not idx_path.exists() or not doc_path.exists():
        return False

    try:
        with open(idx_path, "rb") as f:
            _bm25_indices[contract_type] = pickle.load(f)
        with open(doc_path, "r", encoding="utf-8") as f:
            _bm25_docs[contract_type] = json.load(f)
        return True
    except Exception as e:
        logger.error(f"BM25 인덱스 로드 실패 ({contract_type}): {e}")
        return False


def search(
    query_text: str,
    k: int = 5,
    contract_type: str | None = None,
) -> list[tuple[dict, float]]:
    """BM25 검색. (문서, 점수) 리스트 반환."""
    ct = contract_type or "lease"

    if ct not in _bm25_indices:
        if not _load_index(ct):
            return []

    bm25 = _bm25_indices[ct]
    docs = _bm25_docs[ct]

    query_tokens = _tokenize(query_text)
    if not query_tokens:
        return []

    scores = bm25.get_scores(query_tokens)

    # 상위 k개 인덱스 추출
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]

    results = []
    for idx in ranked:
        if scores[idx] > 0:
            results.append((docs[idx], float(scores[idx])))

    return results
