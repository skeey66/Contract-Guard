"""Cross-encoder 기반 reranker 서비스.

bge-reranker-v2-m3 모델로 (query, passage) 쌍의 관련성 점수를 산출한다.
retrieval_service의 1차 hybrid retrieval(BM25 + dense) 풀 위에서 정밀 재정렬
용도. 임베딩 모델(bge-m3)과 동일 계열이라 도메인 정합성이 높다.
"""

from __future__ import annotations

import logging

from sentence_transformers import CrossEncoder
from backend.app.config import settings

logger = logging.getLogger(__name__)

_reranker: CrossEncoder | None = None


def get_reranker() -> CrossEncoder:
    """Reranker 싱글턴 인스턴스 반환."""
    global _reranker
    if _reranker is None:
        # reranker는 EXAONE에 GPU VRAM 양보를 위해 별도 device 설정 (기본 cpu).
        # auto면 sentence-transformers가 GPU 자동 선택.
        kwargs = {}
        if settings.reranker_device != "auto":
            kwargs["device"] = settings.reranker_device
        _reranker = CrossEncoder(
            settings.reranker_model,
            max_length=settings.reranker_max_length,
            **kwargs,
        )
        logger.info(
            f"Reranker 로딩 완료: {settings.reranker_model} "
            f"(device={_reranker.model.device})"
        )
    return _reranker


def rerank(
    query: str,
    passages: list[str],
    batch_size: int = 32,
) -> list[float]:
    """(query, passage) 쌍별 관련성 점수를 반환 (높을수록 관련성↑).

    bge-reranker-v2-m3는 sigmoid 정규화된 0~1 범위 점수를 출력한다.
    """
    if not passages:
        return []
    pairs = [(query, p) for p in passages]
    scores = get_reranker().predict(
        pairs,
        batch_size=batch_size,
        show_progress_bar=False,
    )
    return [float(s) for s in scores]


def reset_reranker() -> None:
    """싱글턴 초기화 — 설정 변경 시 호출."""
    global _reranker
    _reranker = None
