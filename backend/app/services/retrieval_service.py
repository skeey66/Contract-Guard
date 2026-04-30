import logging
import re

from backend.app.services import chroma_service
from backend.app.services import bm25_service
from backend.app.services import reranker_service
from backend.app.config import settings

logger = logging.getLogger(__name__)

# RRF 상수 (k가 클수록 하위 순위 문서의 영향력 증가)
RRF_K = 60

# 법률 본문 부스트 — KB 분포가 판례·판결문 83% / 법률 12% / 약관 5%로 극단적 불균형이라
# 1차 RRF만으로는 법률 조문이 top-K에 잘 안 들어온다. 3.0으로 강화하여 정형 법조문이
# 검색 결과에 항상 노출되도록 보장한다 (stratified 보장과 이중 안전장치).
LAW_BOOST = 3.0

# 표준약관(safe_clause)에 대한 부스트 — 표준약관 사례에 부합하면 안전 시그널이므로
# law보다는 약하지만 일반 retrieval 점수보다는 우선시한다.
SAFE_CLAUSE_BOOST = 1.5

# unfair_clause(분리 후 명확한 불공정 약관 라벨)는 표면 유사도로 false-positive 위험이
# 있어 페널티 유지. 법률·판례·표준약관이 함께 retrieve되면 보조 자료로 위치시킨다.
CLAUSE_PENALTY = 0.6

# Stratified retrieval — 카테고리별 강제 보장 개수
# 합계가 settings.retrieval_top_k(=5)와 일치해야 한다.
# 우선순위: 법률 → 표준약관 → 판례 → 불공정약관 (사용자 의도: 법률·표준약관 위주, 판례는 회색지대 해석)
STRATIFIED_QUOTA = {
    "law": 2,            # 법률 본문 (강행규정 — 반드시 2개)
    "safe_clause": 1,    # 표준·안전 약관 (부합 시 안전 시그널)
    "judgment": 1,       # 판례·판결문 (회색지대 해석)
    "unfair_clause": 1,  # 불공정 약관 사례 (위험 시그널, 보조)
}

# 1차 retrieval 풀 크기 — 카테고리별 후보를 충분히 확보하기 위해 top_k의 N배로 가져온다.
# 너무 크면 BM25/벡터 latency 증가, 너무 작으면 stratified가 채울 항목 부족.
INITIAL_POOL_K = 20


# ─────────────────────────────────────────────
# 카테고리 매핑 — metadata.source를 추상 카테고리로 변환
#   law            : 법률 본문·강행규정 (BUILTIN_KB 개별 법률명도 모두 통합)
#   safe_clause    : 표준·안전 약관 (AI Hub dvAntageous=1, 실무 표준 사례)
#   judgment       : 판례·판결문
#   unfair_clause  : 불공정 약관 사례 (AI Hub dvAntageous=2)
#   other          : 미매핑
# ─────────────────────────────────────────────
_LAW_SOURCES = {
    "law",
    "민법",
    "주택임대차보호법",
    "상가건물임대차보호법",
    "근로기준법",
    "근로자퇴직급여보장법",
    "이자제한법",
    "대부업법",
    "보증인보호특별법",
    "하도급거래공정화법",
    "약관규제법/판례",  # 약관규제법 본문은 법률 카테고리로 취급
}
_JUDGMENT_SOURCES = {"precedent_kr", "aihub_판결문", "판례/실무"}
_SAFE_CLAUSE_SOURCES = {"safe_clause", "실무"}  # AI Hub 유리 약관 + BUILTIN 실무 표준
_UNFAIR_CLAUSE_SOURCES = {"unfair_clause"}  # AI Hub 불리 약관 (분리 후 명확 라벨)


def _categorize(entry: dict) -> str:
    """metadata.source → 추상 카테고리. 미매핑 source는 other."""
    src = (entry.get("metadata") or {}).get("source", "")
    if src in _LAW_SOURCES:
        return "law"
    if src in _SAFE_CLAUSE_SOURCES:
        return "safe_clause"
    if src in _JUDGMENT_SOURCES:
        return "judgment"
    if src in _UNFAIR_CLAUSE_SOURCES:
        return "unfair_clause"
    return "other"


# 헤더 라벨 제거용 정규식 (본문 hash 폴백 dedup용)
_HEADER_LABEL_RE = re.compile(r"^\[[^\]]+\]\s*[^\n]+\n", re.MULTILINE)
_INLINE_HEADER_RE = re.compile(
    r"^[가-힣A-Za-z·\s]+\s*제\s*\d+\s*조(?:의\s*\d+)?\s*\([^)]*\)\s*:?\s*",
    re.MULTILINE,
)
_MARKDOWN_RE = re.compile(r"\*+|#+|`+|[①-⑳㈀-㈎]")
_WS_RE = re.compile(r"\s+")
_ARTICLE_PARSE_RE = re.compile(r"제\s*(\d+)\s*조(?:의\s*(\d+))?")


def _law_article_key(entry: dict) -> str | None:
    """법조문 메타데이터 기반 dedup 키 (법령명 + 조문번호 + 항).

    같은 조문이 여러 source(legalize-kr "law" / BUILTIN_KB "민법" 등)로 인덱싱되어
    있어도 (법령, 조문) 조합으로 1개만 통과하게 한다.

    매핑 가능하면 "법령명-N-M" 형식 키, 매핑 불가면 None (본문 hash로 폴백).
    """
    md = entry.get("metadata") or {}
    src = md.get("source", "")

    # legalize-kr 형식: source="law" + law_name + article_no(int) + sub_no(int)
    if src == "law":
        law_name = (md.get("law_name") or "").strip()
        article_no = md.get("article_no")
        sub_no = md.get("sub_no") or 0
        if law_name and article_no is not None:
            return f"{law_name}-{int(article_no)}-{int(sub_no)}"

    # BUILTIN_KB 형식: source가 법률명 + article="제N조"
    if src in _LAW_SOURCES and src != "law":
        article = (md.get("article") or "").strip()
        m = _ARTICLE_PARSE_RE.search(article)
        if m:
            article_no = int(m.group(1))
            sub_no = int(m.group(2)) if m.group(2) else 0
            return f"{src}-{article_no}-{sub_no}"

    return None


def _content_dedup_key(entry: dict) -> str:
    """본문 정규화 hash 기반 dedup 키 (메타 기반 키가 없을 때 폴백).

    헤더·마크다운·공백을 모두 정규화하여 본문 알맹이만 비교. 단 미세한 표현 차이
    ("동의 없이" vs "동의없이")는 공백 제거로 흡수한다.
    """
    text = entry.get("text", "")
    text = _HEADER_LABEL_RE.sub("", text, count=1)
    text = _INLINE_HEADER_RE.sub("", text, count=1)
    text = _MARKDOWN_RE.sub(" ", text)
    # 공백 완전 제거 (미세 공백 차이 흡수)
    normalized = re.sub(r"\s+", "", text).lower()
    return normalized[:120]


def _dedup_key(entry: dict) -> str:
    """우선순위: 법조문 메타 기반 키 > 본문 정규화 hash."""
    return _law_article_key(entry) or _content_dedup_key(entry)


def _build_rrf_candidates(
    vector_results: list[tuple[str, dict]],
    bm25_results: list[tuple[str, dict]],
) -> tuple[dict[str, float], dict[str, dict]]:
    """벡터 + BM25 결과를 RRF 점수로 머지. 점수 dict + entry dict 반환."""
    scores: dict[str, float] = {}
    entries: dict[str, dict] = {}

    for rank, (doc_id, entry) in enumerate(vector_results):
        scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (RRF_K + rank + 1)
        entries[doc_id] = entry

    for rank, (doc_id, entry) in enumerate(bm25_results):
        scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (RRF_K + rank + 1)
        if doc_id not in entries:
            entries[doc_id] = entry

    return scores, entries


def _stratified_select(
    scores: dict[str, float],
    entries: dict[str, dict],
    top_k: int,
) -> list[dict]:
    """카테고리 부스트 + stratified 선택 + 본문 중복 제거. 점수 출처 무관.

    절차:
      1. 카테고리별 점수 조정 (law 부스트, safe_clause 부스트, unfair_clause 페널티)
      2. 카테고리별 풀 분리·정렬
      3. STRATIFIED_QUOTA에 따라 우선 선택 (본문 dedup 적용)
      4. 카테고리 quota 미달 시 잔여 풀에서 점수 높은 순으로 보충
      5. 출력 순서: law → safe_clause → judgment → unfair_clause → other
         (LLM이 법률·표준약관을 먼저 읽고 마지막에 위험 사례 참조)
    """
    # 1. 카테고리별 점수 조정 (원본 dict 변경 방지 — 호출부 재사용 대비)
    scores = dict(scores)
    for doc_id, entry in entries.items():
        cat = _categorize(entry)
        if cat == "law":
            scores[doc_id] *= LAW_BOOST
        elif cat == "safe_clause":
            scores[doc_id] *= SAFE_CLAUSE_BOOST
        elif cat == "unfair_clause":
            scores[doc_id] *= CLAUSE_PENALTY

    # 2. 카테고리별 풀 분리·정렬
    pools: dict[str, list[tuple[float, str]]] = {
        "law": [],
        "safe_clause": [],
        "judgment": [],
        "unfair_clause": [],
        "other": [],
    }
    for doc_id in scores:
        cat = _categorize(entries[doc_id])
        pools[cat].append((scores[doc_id], doc_id))
    for cat in pools:
        pools[cat].sort(reverse=True)

    # 3. STRATIFIED_QUOTA 우선 선택 + 본문 dedup
    selected_ids: list[str] = []
    seen_dedup_keys: set[str] = set()
    quota_remaining = dict(STRATIFIED_QUOTA)

    for cat in ("law", "safe_clause", "judgment", "unfair_clause"):
        for score, doc_id in pools.get(cat, []):
            if quota_remaining[cat] <= 0:
                break
            dkey = _dedup_key(entries[doc_id])
            if dkey in seen_dedup_keys:
                continue
            seen_dedup_keys.add(dkey)
            selected_ids.append(doc_id)
            quota_remaining[cat] -= 1

    # 4. quota 미달 시 (해당 카테고리 후보 부족) 나머지 점수 높은 항목으로 보충
    remaining = top_k - len(selected_ids)
    if remaining > 0:
        all_remaining = [
            (scores[doc_id], doc_id)
            for doc_id in scores
            if doc_id not in selected_ids
        ]
        all_remaining.sort(reverse=True)
        for score, doc_id in all_remaining:
            if remaining <= 0:
                break
            dkey = _dedup_key(entries[doc_id])
            if dkey in seen_dedup_keys:
                continue
            seen_dedup_keys.add(dkey)
            selected_ids.append(doc_id)
            remaining -= 1

    # 5. 출력 순서: law → safe_clause → judgment → unfair_clause → other
    cat_order = {"law": 0, "safe_clause": 1, "judgment": 2, "unfair_clause": 3, "other": 4}
    selected_with_meta = [
        (cat_order.get(_categorize(entries[doc_id]), 5), -scores[doc_id], doc_id)
        for doc_id in selected_ids
    ]
    selected_with_meta.sort()

    results = []
    for _, _, doc_id in selected_with_meta:
        entry = entries[doc_id]
        entry["rrf_score"] = round(scores[doc_id], 6)
        results.append(entry)

    return results


def _apply_reranker(
    query: str,
    scores: dict[str, float],
    entries: dict[str, dict],
) -> dict[str, float]:
    """Cross-encoder로 entries 전체를 재정렬한 점수 dict 반환.

    1차 RRF 점수는 무시하고 reranker 점수(0~1)로 대체한다. 카테고리 부스트는
    이후 _stratified_select에서 적용되므로 여기서는 순수 관련성만 산출한다.
    """
    if not entries:
        return scores
    doc_ids = list(entries.keys())
    passages = [entries[doc_id]["text"] for doc_id in doc_ids]
    rerank_scores = reranker_service.rerank(query, passages)
    return {doc_id: rerank_scores[i] for i, doc_id in enumerate(doc_ids)}


def retrieve_similar(
    text: str,
    top_k: int | None = None,
    contract_type: str | None = None,
) -> list[dict]:
    """BM25 + 벡터 하이브리드 검색 후 stratified RRF로 결합.

    카테고리별 보장 quota(law 2, safe_clause 1, judgment 1, unfair_clause 1)에 따라
    법률 본문과 표준약관이 항상 top-K에 노출되도록 한다.
    """
    k = top_k or settings.retrieval_top_k

    # 1차 retrieval 풀은 stratified 선택을 위해 충분히 크게 가져온다.
    pool_k = max(INITIAL_POOL_K, k * 4)

    # 벡터 검색 (ChromaDB)
    vector_raw = chroma_service.query(text, k=pool_k, contract_type=contract_type)
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

    # BM25 검색 — 원점수는 [0, 무제한]이라 벡터 유사도(0~1)와 동일 필드에 저장하면
    # 표시용 비교가 망가진다. score / (score + C) 매핑으로 일반 BM25 범위(5~60)에서
    # 0.38~0.88로 매핑되어 saturation 방지.
    bm25_raw = bm25_service.search(text, k=pool_k, contract_type=contract_type)
    bm25_results: list[tuple[str, dict]] = []
    BM25_SCALE_C = 8.0
    BM25_CAP = 0.92
    for doc_dict, score in bm25_raw:
        doc_id = doc_dict.get("id", doc_dict["text"][:80])
        sim = min(BM25_CAP, score / (score + BM25_SCALE_C)) if score > 0 else 0.0
        entry = {
            "id": doc_id,
            "text": doc_dict["text"],
            "similarity": round(sim, 4),
            "metadata": doc_dict.get("metadata", {}),
        }
        bm25_results.append((doc_id, entry))

    if not vector_results and not bm25_results:
        return []

    # 한쪽만 있을 때도 stratified 선택은 동일하게 동작 (한쪽 풀로만 결합)
    if not bm25_results:
        logger.debug("BM25 결과 없음, 벡터 검색 결과만 사용")
    if not vector_results:
        logger.debug("벡터 검색 결과 없음, BM25 결과만 사용")

    scores, entries = _build_rrf_candidates(vector_results, bm25_results)

    if settings.reranker_enabled:
        scores = _apply_reranker(text, scores, entries)

    combined = _stratified_select(scores, entries, top_k=k)
    logger.debug(
        f"하이브리드 검색 완료: 벡터 {len(vector_results)}건, "
        f"BM25 {len(bm25_results)}건, "
        f"reranker={'on' if settings.reranker_enabled else 'off'} "
        f"→ stratified {len(combined)}건"
    )
    return combined
