"""실제 PDF 계약서를 직접 분석하는 검증 스크립트."""

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services import document_service, clause_service
from backend.app.services.analysis_service import run_analysis


async def main(pdf_path: str):
    print(f"[1/4] PDF 텍스트 추출: {pdf_path}")
    text, pages = document_service.extract_text(pdf_path)
    print(f"  → {len(text)}자, {pages}페이지")

    print("[2/4] 계약 유형·sub-type·당사자 감지")
    contract_type = clause_service.detect_contract_type(text)
    sub_type = (
        clause_service.detect_lease_subtype(text)
        if contract_type == "lease"
        else None
    )
    parties = clause_service.detect_parties(text, contract_type)
    print(f"  → contract_type={contract_type}, sub_type={sub_type}, parties={parties}")

    print("[3/4] 조항 분리")
    clauses = clause_service.split_clauses(text)
    print(f"  → {len(clauses)}개 조항")

    print("[4/4] 분석 실행")
    result = await run_analysis(
        document_id="test-pdf",
        filename=Path(pdf_path).name,
        clauses=clauses,
        contract_type=contract_type,
        parties=parties,
        sub_type=sub_type,
    )

    print()
    print("=" * 70)
    print(f"분석 결과: 총 {result.total_clauses}개 조항 / 위험 {result.risky_clauses}개")
    print("=" * 70)
    by_level: dict[str, int] = {}
    for ca in result.clause_analyses:
        lvl = ca.risk_level.value if hasattr(ca.risk_level, "value") else str(ca.risk_level)
        by_level[lvl] = by_level.get(lvl, 0) + 1
    print(f"분포: {by_level}")
    print()
    print("조항별 결과:")
    for ca in result.clause_analyses:
        lvl = ca.risk_level.value if hasattr(ca.risk_level, "value") else str(ca.risk_level)
        title = ca.clause_title[:30]
        expl = ca.explanation[:100].replace("\n", " ")
        marker = "[!]" if lvl in ("high", "medium") else "[ ]"
        print(f"  {marker} {ca.clause_index:>2} [{lvl:>6s}] {title:32s} | {expl}")


if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\skeey\OneDrive\바탕 화면\제1조.pdf"
    asyncio.run(main(pdf_path))
