import uuid
from backend.app.models.clause import Clause
from backend.app.models.risk import RiskLevel, RiskDetail
from backend.app.models.analysis import ClauseAnalysis, AnalysisResult
from backend.app.rag.chain import analyze_all_clauses


async def run_analysis(
    document_id: str,
    filename: str,
    clauses: list[Clause],
    contract_type: str = "lease",
) -> AnalysisResult:
    result = await analyze_all_clauses(clauses, contract_type=contract_type)
    parsed_list = result["parsed_list"]
    references = result["references"]

    clause_analyses = _build_clause_analyses(parsed_list, clauses, references)

    risky = [ca for ca in clause_analyses if ca.risk_level != RiskLevel.SAFE]
    summary = _generate_summary(clause_analyses, risky)

    return AnalysisResult(
        id=str(uuid.uuid4()),
        document_id=document_id,
        filename=filename,
        total_clauses=len(clauses),
        risky_clauses=len(risky),
        clause_analyses=clause_analyses,
        summary=summary,
    )


def _build_clause_analyses(
    parsed_list: list[dict],
    clauses: list[Clause],
    references: list[dict],
) -> list[ClauseAnalysis]:
    similar_refs = [
        f"{ref.get('text', '')[:80]}... (유사도: {ref.get('similarity', 0):.2f})"
        for ref in references
    ]

    # clause_index → parsed 매핑 (빠른 조회용)
    index_map = {}
    for item in parsed_list:
        ci = item.get("clause_index")
        if ci is not None:
            index_map[ci] = item

    analyses = []
    for pos, clause in enumerate(clauses):
        parsed = None
        if parsed_list:
            # 1순위: 정확한 clause_index 매칭
            parsed = index_map.get(clause.index)
            # 2순위: LLM이 0-based로 반환한 경우 (clause_index - 1 보정)
            if parsed is None:
                parsed = index_map.get(clause.index - 1)
            # 3순위: 위치 기반 fallback
            if parsed is None and pos < len(parsed_list):
                parsed = parsed_list[pos]

        if parsed:
            risk_level = _parse_risk_level(parsed.get("risk_level", "safe"))
            confidence = float(parsed.get("confidence", 0.5))
            raw_risks = parsed.get("risks", [])
            risks = [
                RiskDetail(
                    risk_type=r.get("risk_type", "unknown"),
                    description=r.get("description", ""),
                    suggestion=r.get("suggestion", ""),
                )
                for r in raw_risks
                if isinstance(r, dict)
            ]
            explanation = parsed.get("explanation", "")
        else:
            risk_level = RiskLevel.SAFE
            confidence = 0.3
            risks = []
            explanation = "분석 결과를 파싱하지 못했습니다."

        analyses.append(ClauseAnalysis(
            clause_index=clause.index,
            clause_title=clause.title,
            clause_content=clause.content,
            risk_level=risk_level,
            confidence=confidence,
            risks=risks,
            similar_references=similar_refs,
            explanation=explanation,
        ))

    return analyses



def _parse_risk_level(value: str) -> RiskLevel:
    mapping = {
        "high": RiskLevel.HIGH,
        "medium": RiskLevel.MEDIUM,
        "low": RiskLevel.LOW,
        "safe": RiskLevel.SAFE,
    }
    return mapping.get(value.lower().strip(), RiskLevel.SAFE)


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
