import json
import logging
import uuid
from difflib import SequenceMatcher
from pathlib import Path

from backend.app.config import settings
from backend.app.models.clause import Clause
from backend.app.models.risk import RiskLevel, RiskDetail
from backend.app.models.analysis import ClauseAnalysis, AnalysisResult
from backend.app.rag.chain import analyze_all_clauses
from backend.app.contract_types import CONTRACT_TYPES
from backend.app.services.rewrite_service import rewrite_risky_clauses

logger = logging.getLogger(__name__)


async def run_analysis(
    document_id: str,
    filename: str,
    clauses: list[Clause],
    contract_type: str = "lease",
    parties: dict[str, str] | None = None,
) -> AnalysisResult:
    result = await analyze_all_clauses(
        clauses,
        contract_type=contract_type,
        parties=parties,
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
    summary = _generate_summary(clause_analyses, risky)

    analysis_result = AnalysisResult(
        id=str(uuid.uuid4()),
        document_id=document_id,
        filename=filename,
        total_clauses=len(clauses),
        risky_clauses=len(risky),
        clause_analyses=clause_analyses,
        summary=summary,
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
                )
                for r in raw_risks
                if isinstance(r, dict)
            ]
            explanation = parsed.get("explanation", "")
            analysis_status = parsed.get("_status", "ok")
        else:
            # index_map에도 없음 = chain이 완전히 누락한 조항 (이상 케이스)
            risk_level = RiskLevel.MEDIUM
            confidence = 0.3
            risks = []
            explanation = "[분석 실패] 분석 파이프라인에서 이 조항이 누락되었습니다. 수동 검토가 필요합니다."
            analysis_status = "missing"

        # 해당 조항 전용 참고문헌 사용
        clause_refs = per_clause_refs.get(clause.index, [])
        similar_refs = [
            f"{ref.get('text', '')[:80]}... (유사도: {ref.get('similarity', 0):.2f})"
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


def _generate_summary(
    all_analyses: list[ClauseAnalysis],
    risky_analyses: list[ClauseAnalysis],
) -> str:
    total = len(all_analyses)
    risky_count = len(risky_analyses)

    if risky_count == 0:
        return f"총 {total}개 조항을 분석한 결과, 특별히 불리한 조항이 발견되지 않았습니다."

    high = sum(1 for a in risky_analyses if a.risk_level == RiskLevel.HIGH)
    medium = sum(1 for a in risky_analyses if a.risk_level == RiskLevel.MEDIUM)
    low = sum(1 for a in risky_analyses if a.risk_level == RiskLevel.LOW)

    parts = []
    if high:
        parts.append(f"고위험 {high}개")
    if medium:
        parts.append(f"중위험 {medium}개")
    if low:
        parts.append(f"저위험 {low}개")

    risk_summary = ", ".join(parts)
    return (
        f"총 {total}개 조항 중 {risky_count}개 조항에서 "
        f"위험 요소가 발견되었습니다 ({risk_summary}). "
        f"세부 내용을 확인하고 계약 전 수정을 요청하세요."
    )
