import logging
import re
import uuid
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from backend.app.config import settings
from backend.app.models.clause import Clause
from backend.app.models.risk import RiskLevel, RiskDetail
from backend.app.models.analysis import ClauseAnalysis, AnalysisResult, ReferenceItem
from backend.app.rag.chain import analyze_all_clauses
from backend.app.contract_types import CONTRACT_TYPES
from backend.app.services.rewrite_service import rewrite_risky_clauses
from backend.app.services.summary_service import generate_overall_summary

logger = logging.getLogger(__name__)


async def run_analysis(
    document_id: str,
    filename: str,
    clauses: list[Clause],
    contract_type: str = "lease",
    parties: dict[str, str] | None = None,
    sub_type: str | None = None,
) -> AnalysisResult:
    result = await analyze_all_clauses(
        clauses,
        contract_type=contract_type,
        parties=parties,
        sub_type=sub_type,
    )
    parsed_list = result["parsed_list"]
    per_clause_refs = result["per_clause_refs"]

    # 위험도 high/medium 조항에 대해 표준약관 기반 수정안 생성
    rewrites: dict[int, str] = {}
    try:
        rewrites = await rewrite_risky_clauses(clauses, parsed_list, per_clause_refs)
    except Exception as e:
        logger.error(f"수정안 생성 단계 실패 (분석 결과는 정상 반환): {e}")

    clause_analyses = _build_clause_analyses(
        parsed_list, clauses, per_clause_refs, contract_type, rewrites
    )

    risky = [ca for ca in clause_analyses if ca.risk_level != RiskLevel.SAFE]

    # LLM 기반 종합 평가 — 내부에서 타임아웃·예외를 잡아 카운트 기반 폴백으로 대체함
    summary = await generate_overall_summary(clause_analyses, contract_type=contract_type)

    analysis_result = AnalysisResult(
        id=str(uuid.uuid4()),
        document_id=document_id,
        filename=filename,
        total_clauses=len(clauses),
        risky_clauses=len(risky),
        clause_analyses=clause_analyses,
        summary=summary,
        contract_type=contract_type,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )

    # 분석 결과를 디스크에 영속화 — export/재조회 엔드포인트가 사용
    try:
        results_dir = Path(settings.results_dir)
        results_dir.mkdir(parents=True, exist_ok=True)
        out_path = results_dir / f"{analysis_result.id}.json"
        out_path.write_text(
            analysis_result.model_dump_json(indent=2, exclude_none=False),
            encoding="utf-8",
        )
        logger.info(f"분석 결과 저장: {out_path}")
    except Exception as e:
        logger.error(f"분석 결과 저장 실패 (응답은 정상 반환): {e}")

    return analysis_result


# source 분류 — 홈 화면 KB 카드와 동일한 분류 체계 (4분할)
_JUDGMENT_SOURCES = {"precedent_kr", "aihub_판결문", "판례/실무"}
_SAFE_CLAUSE_SOURCES = {"safe_clause", "실무"}
_UNFAIR_CLAUSE_SOURCES = {"unfair_clause"}
# "약관규제법/판례"는 약관규제법 본문이므로 law로 집계


def _categorize_source(source: str) -> str:
    """metadata.source를 dashboard 카테고리로 매핑.

    내부 retrieval 카테고리(safe_clause/unfair_clause)는 프론트엔드 탭 구조와의
    하위 호환을 위해 모두 'clause'로 합산한다. 프론트는 source/text prefix로 구분 가능.
    """
    if source in _JUDGMENT_SOURCES:
        return "judgment"
    if source in _SAFE_CLAUSE_SOURCES or source in _UNFAIR_CLAUSE_SOURCES:
        return "clause"
    return "law"


_WS_NORM_RE = re.compile(r"\s+")

# 위험 시그널 단어 — quote 폴백 자동 추출용 (도메인 중립).
# LLM이 위험 판정했지만 quote 작성을 빠뜨린 경우, 본문에서 이 단어들 근처 문장을 추출해
# 형광펜·증거 기반 검증의 폴백으로 사용한다.
_RISK_SIGNAL_WORDS = (
    # 부정·박탈
    "없이", "없다", "없으며", "포기", "박탈", "거부",
    # 일방성·재량
    "전적으로", "단독", "일방", "일방적", "독단", "임의로", "마음대로",
    # 즉시·강제
    "즉시", "무조건", "절대", "전면",
    # 책임 면제·배제
    "면제", "배제", "면책",
    # 법정 한도 초과
    "초과", "한도",
    # 비용 전가 (을이 부담·분담·충당)
    "을이 부담", "을의 부담", "임차인이 부담", "임차인의 부담",
    "전액 부담", "전부 부담", "전액", "분담한다", "분담하기로", "충당", "전가",
    # 일방 결정·해석 권한
    "갑이 결정", "갑이 단독", "갑의 단독", "임대인이 결정", "임대인의 단독",
    "사업자가 결정", "사용자가 결정",
    # 기한 박탈·제한
    "공제", "유보", "무기한", "무제한", "박탈",
    # 관할·소송 제약
    "본사", "소재지", "지정", "전속관할",
    # 일반화된 광범위 면책 표현
    "어떠한 경우에도", "여하한 사유",
)


def _extract_risky_excerpt(content: str, max_len: int = 100) -> str | None:
    """본문에서 위험 시그널 단어가 등장하는 문장을 추출.

    LLM이 위험으로 판정했지만 quote를 작성하지 못한 경우의 폴백.
    위험 시그널 단어가 본문에 등장할 때만 추출 (false-positive 차단).
    매칭 실패 시 None을 반환하여 환각 차단을 그대로 진행.
    """
    if not content:
        return None
    sentences = re.split(r"[.。\n]", content)
    for sent in sentences:
        sent_strip = sent.strip()
        if not sent_strip or len(sent_strip) < 10:
            continue
        if any(w in sent_strip for w in _RISK_SIGNAL_WORDS):
            if len(sent_strip) <= max_len:
                return sent_strip
            return sent_strip[:max_len].rstrip(" ,·")
    return None


def _validate_quote(raw, clause_text: str) -> str | None:
    """LLM이 출력한 quote가 본 조항 원문의 substring인지 검증한다.

    LLM이 의역하거나 환각으로 본문에 없는 문구를 quote에 적으면 frontend의 형광펜이
    매칭되지 않아 사용자에게 혼란을 준다. 정확한 substring일 때만 채택하고, 아니면
    None으로 폴백하여 형광펜 표시를 생략한다 (잘못 칠하기보다 안 칠하기가 안전).

    매칭 단계 (점진 완화):
      1) 정확 substring
      2) 공백 정규화 substring (줄바꿈·다중공백 차이만 있는 경우)
      3) Prefix 폴백: LLM이 quote를 길게 출력하다가 토큰 한도로 끝부분이 잘리거나
         의역으로 끝부분만 변형한 경우, 처음 N자가 본문에 있으면 그것만 채택.
         (LLM 응답이 num_predict 한도에서 절단되는 케이스를 복구)
    """
    if not isinstance(raw, str):
        return None
    q = raw.strip()
    if not q or not clause_text:
        return None
    if len(q) < 4:
        return None

    # 1단계: 정확 substring
    if q in clause_text:
        return q

    # 2단계: 공백 정규화 후 substring
    q_norm = _WS_NORM_RE.sub(" ", q)
    text_norm = _WS_NORM_RE.sub(" ", clause_text)
    if q_norm in text_norm:
        return q_norm

    # 3단계: Prefix 폴백 (긴 quote의 앞부분만 매칭되는 경우)
    for cut in (120, 100, 80, 60, 40, 25):
        if len(q) <= cut:
            continue
        prefix = q[:cut].rstrip(" ,.\"'·")
        if len(prefix) < 15:
            break
        if prefix in clause_text:
            return prefix
        prefix_norm = _WS_NORM_RE.sub(" ", prefix)
        if prefix_norm in text_norm:
            return prefix_norm

    logger.debug(f"quote 검증 실패 (본문에 없음): {q[:60]!r}")
    return None


def _reclassify_by_evidence(
    risk_level: RiskLevel,
    analysis_status: str,
    refs: list[dict],
) -> tuple[RiskLevel, str]:
    """LLM 위험 판정을 데이터 출처와 매칭 강도에 따라 등급 재분류.

    medium 자격은 'unfair_clause' 매칭만 인정 — judgment·law 매칭은 정상 조항에서도
    흔하게 발생해 noise이고, 매칭 강도가 높다고 "위반 근거"인 것은 아니다.
    임계값은 BM25-only 제외 + 의미 매칭 sim ≥ 0.7.

    분류:
    - HIGH (법률 위반):
      - rule_high / kb_high (검증된 패턴)
      - LLM high + very_strong unfair_clause 매칭 (sim ≥ 0.75)
    - MEDIUM (계약자 불리):
      - LLM high/medium + strong unfair_clause 매칭 (sim ≥ 0.7)
    - LOW (검토 권장):
      - LLM 위험 판정인데 strong unfair 매칭 없음
    - SAFE: rule_safe / kb_safe / evidence_filtered / missing / LLM safe
    """
    if analysis_status in ("rule_high", "rule_safe", "kb_high", "kb_safe",
                            "missing", "evidence_filtered"):
        return risk_level, analysis_status
    if risk_level not in (RiskLevel.HIGH, RiskLevel.MEDIUM):
        return risk_level, analysis_status

    def _has_strong_unfair(threshold: float) -> bool:
        for r in refs:
            if r.get("match_source", "vector") == "bm25":
                continue
            if (r.get("similarity", 0) or 0) < threshold:
                continue
            if (r.get("metadata") or {}).get("source", "") in _UNFAIR_CLAUSE_SOURCES:
                return True
        return False

    if risk_level == RiskLevel.HIGH and _has_strong_unfair(0.75):
        return RiskLevel.HIGH, "unfair_strong_evidence"
    if _has_strong_unfair(0.7):
        return RiskLevel.MEDIUM, "unfair_evidence"
    return RiskLevel.LOW, "llm_only"


def _normalize_risk_type(raw: str, valid_types: list[str]) -> str:
    """LLM이 반환한 risk_type을 유효한 유형으로 매핑."""
    raw_clean = raw.strip()
    # 정확히 일치하면 그대로 반환
    if raw_clean in valid_types:
        return raw_clean
    # 유사도 기반 매칭
    best_match = None
    best_score = 0.0
    for vt in valid_types:
        score = SequenceMatcher(None, raw_clean, vt).ratio()
        if score > best_score:
            best_score = score
            best_match = vt
    if best_match and best_score >= 0.4:
        logger.info(f"risk_type 매핑: '{raw_clean}' → '{best_match}' (유사도: {best_score:.2f})")
        return best_match
    logger.warning(f"risk_type 매핑 실패: '{raw_clean}' (유효 유형: {valid_types})")
    return raw_clean


def _build_clause_analyses(
    parsed_list: list[dict],
    clauses: list[Clause],
    per_clause_refs: dict[int, list[dict]],
    contract_type: str = "lease",
    rewrites: dict[int, str] | None = None,
) -> list[ClauseAnalysis]:
    # 계약 유형별 유효한 risk_type 목록
    ct_config = CONTRACT_TYPES.get(contract_type, {})
    valid_risk_types = ct_config.get("risk_types", [])

    # clause_index → parsed 매핑 (정확한 매칭만 사용)
    index_map = {}
    for item in parsed_list:
        ci = item.get("clause_index")
        if ci is not None:
            index_map[ci] = item

    analyses = []
    for clause in clauses:
        parsed = index_map.get(clause.index)

        if parsed:
            risk_level = _parse_risk_level(parsed.get("risk_level", "safe"))
            confidence = float(parsed.get("confidence", 0.5))
            raw_risks = parsed.get("risks", [])
            risks = [
                RiskDetail(
                    risk_type=_normalize_risk_type(r.get("risk_type", "unknown"), valid_risk_types) if valid_risk_types else r.get("risk_type", "unknown"),
                    description=r.get("description", ""),
                    suggestion=r.get("suggestion", ""),
                    quote=_validate_quote(r.get("quote"), clause.content),
                )
                for r in raw_risks
                if isinstance(r, dict)
            ]
            explanation = parsed.get("explanation", "")
            analysis_status = parsed.get("_status", "ok")

            # 증거 기반 필터링 — quote 검증된 risks만 채택. quote 없으면 환각 가능성.
            # 다만 LLM 비결정성으로 진짜 위험이 quote만 빠뜨려 잘못 차단될 수 있어
            # 본문에서 위험 시그널 자동 추출 폴백으로 false-negative를 줄인다.
            # 룰 기반 결과(_status="kb_high"/"kb_safe"/룰 매칭)는 신뢰성 검증된 출처라 예외.
            llm_origin = analysis_status not in ("kb_high", "kb_safe", "missing")
            if llm_origin and risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM):
                # 1차: quote가 비어있는 risk에 대해 본문에서 위험 시그널 자동 추출 시도
                for r in risks:
                    if not (r.quote and r.quote.strip()):
                        auto_quote = _extract_risky_excerpt(clause.content)
                        if auto_quote:
                            r.quote = auto_quote
                            logger.debug(
                                f"조항 {clause.index} quote 자동 폴백: {auto_quote[:60]!r}"
                            )

                # 2차: 폴백 후에도 quote 없는 risk는 환각으로 간주
                substantiated = [r for r in risks if r.quote and r.quote.strip()]
                if not substantiated and risks:
                    # 위험으로 판정했지만 quote 누락 — 두 가지 가능성:
                    # 1) LLM 환각 (실제 안전인데 위험 본 것)
                    # 2) LLM이 위험 본질은 잡았지만 인용 표기 실패 (실제 위험)
                    # safe로 강등하면 2)가 false negative로 묻힘 → LOW(검토 권장)로 분류해
                    # 사용자가 직접 검토 가능하게 한다.
                    logger.info(
                        f"조항 {clause.index} 증거 부족: 모든 risk가 quote 없음 → "
                        f"{risk_level.value} → low(검토 권장)로 분류"
                    )
                    risk_level = RiskLevel.LOW
                    risks = []
                    explanation = (
                        "LLM이 위험 가능성을 시사했으나 본문에서 직접 인용할 근거를 "
                        "제시하지 못했습니다. 위험 단정은 어렵지만 변호사 검토를 권장합니다."
                    )
                    analysis_status = "evidence_filtered"
                elif len(substantiated) < len(risks):
                    # 일부만 환각인 경우, 증거 있는 risk만 유지
                    removed = len(risks) - len(substantiated)
                    logger.info(
                        f"조항 {clause.index} 부분 환각 차단: {removed}개 risk 제거, "
                        f"{len(substantiated)}개 유지"
                    )
                    risks = substantiated

            # 데이터 출처 기반 등급 재분류 — 등급 근거를 references_detail로 추적 가능하게.
            new_level, new_status = _reclassify_by_evidence(
                risk_level, analysis_status,
                per_clause_refs.get(clause.index, []),
            )
            if new_level != risk_level:
                logger.info(
                    f"조항 {clause.index} 등급 재분류: "
                    f"{risk_level.value} → {new_level.value} ({new_status})"
                )
                risk_level = new_level
                analysis_status = new_status
        else:
            # index_map에도 없음 = chain이 완전히 누락한 조항 (이상 케이스)
            risk_level = RiskLevel.MEDIUM
            confidence = 0.3
            risks = []
            explanation = "[분석 실패] 분석 파이프라인에서 이 조항이 누락되었습니다. 수동 검토가 필요합니다."
            analysis_status = "missing"

        # 해당 조항 전용 참고문헌 — 유사도 내림차순 정렬 후 표시
        clause_refs = sorted(
            per_clause_refs.get(clause.index, []),
            key=lambda r: r.get("similarity", 0) or 0,
            reverse=True,
        )
        similar_refs = [
            f"{ref.get('text', '')[:80]}... (유사도: {ref.get('similarity', 0):.2f})"
            for ref in clause_refs
        ]
        # 대시보드 집계용 구조화 메타데이터 — 카테고리 분류 + 출처/조문 보존
        references_detail = [
            ReferenceItem(
                text=ref.get("text", ""),
                source=(ref.get("metadata") or {}).get("source", "unknown"),
                category=_categorize_source((ref.get("metadata") or {}).get("source", "")),
                similarity=float(ref.get("similarity", 0) or 0),
                article=(ref.get("metadata") or {}).get("article") or None,
                match_source=ref.get("match_source", "vector"),
            )
            for ref in clause_refs
        ]

        suggested_rewrite = (rewrites or {}).get(clause.index)

        analyses.append(ClauseAnalysis(
            clause_index=clause.index,
            clause_title=clause.title,
            clause_content=clause.content,
            risk_level=risk_level,
            confidence=confidence,
            risks=risks,
            similar_references=similar_refs,
            references_detail=references_detail,
            explanation=explanation,
            analysis_status=analysis_status,
            suggested_rewrite=suggested_rewrite,
        ))

    return analyses



def _parse_risk_level(value: str) -> RiskLevel:
    mapping = {
        "high": RiskLevel.HIGH,
        "medium": RiskLevel.MEDIUM,
        "low": RiskLevel.LOW,
        "safe": RiskLevel.SAFE,
    }
    return mapping.get(value.lower().strip(), RiskLevel.MEDIUM)
