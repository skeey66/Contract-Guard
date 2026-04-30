"""AI Hub Validation 데이터를 이용한 분석 정확도 검증 스크립트.

사용법:
    python -m backend.scripts.validate
    python -m backend.scripts.validate --limit 20    # 일부만 테스트
"""

import argparse
import asyncio
import json
import os
import sys
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.models.clause import Clause
from backend.app.rag.chain import analyze_all_clauses


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def load_validation_set() -> list[dict]:
    """Validation 불리 + Training 유리 임대차 약관 데이터를 로드."""
    # CLAUDE.md: AI Hub 원천 데이터 위치는 backend/data/raw/aihub/ (프로젝트 루트의 data/raw/가 아님)
    aihub_base = PROJECT_ROOT / "backend" / "data" / "raw" / "aihub" / "01.데이터"
    items = []

    search_paths = [
        # Validation 불리
        (aihub_base / "2.Validation" / "라벨링데이터_230510_add", "validation"),
        # Training 유리 (검증용으로 일부 차용)
        (aihub_base / "1.Training" / "라벨링데이터_230510_add", "training"),
    ]

    for base_path, split in search_paths:
        if not base_path.exists():
            continue
        for root, dirs, files in os.walk(base_path):
            nfc_root = _nfc(root)
            if "약관" not in nfc_root:
                continue
            for f in files:
                nfc_f = _nfc(f)
                if "임대차" not in nfc_f or not nfc_f.endswith(".json"):
                    continue
                filepath = os.path.join(root, f)
                try:
                    with open(filepath, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                articles = data.get("clauseArticle", [])
                clause_text = "\n".join(articles) if isinstance(articles, list) else str(articles)
                if not clause_text.strip():
                    continue

                dv = str(data.get("dvAntageous", ""))
                # 1=유리(safe), 2=불리(risky)
                ground_truth = "risky" if dv == "2" else "safe"

                items.append({
                    "clause_text": clause_text,
                    "ground_truth": ground_truth,
                    "dv": dv,
                    "filename": nfc_f,
                    "split": split,
                    "basis": data.get("illdcssBasiss", []),
                })

    return items


def prediction_matches(risk_level: str, ground_truth: str) -> bool:
    """LLM 판정과 정답이 일치하는지 확인."""
    if ground_truth == "safe":
        return risk_level in ("safe", "low")
    else:  # risky
        return risk_level in ("high", "medium")


# 동시 LLM 호출 슬롯 — Ollama NUM_PARALLEL=1 환경에서 1로 유지하면 EXAONE이 full GPU 사용
# (병렬로 올리면 KV cache 압박으로 모델이 CPU swap → 더 느려짐)
VALIDATION_CONCURRENCY = 1


async def _process_item(
    idx: int,
    item: dict,
    total: int,
    semaphore: asyncio.Semaphore,
    counter: list[int],
) -> dict:
    """개별 항목 분석 — Semaphore로 동시 LLM 호출 제한."""
    async with semaphore:
        clause = Clause(
            index=0,
            title=f"약관 조항 ({item['filename'][:30]})",
            content=item["clause_text"][:500],
        )

        try:
            result = await analyze_all_clauses([clause])
            parsed_list = result["parsed_list"]
            if parsed_list:
                risk_level = parsed_list[0].get("risk_level", "safe").lower().strip()
                explanation = parsed_list[0].get("explanation", "")
            else:
                risk_level = "safe"
                explanation = "파싱 실패"
        except Exception as e:
            risk_level = "error"
            explanation = str(e)

        gt = item["ground_truth"]
        match = prediction_matches(risk_level, gt)

        # 완료 순서로 진행도 출력 (병렬이라 idx 순 아님)
        counter[0] += 1
        icon = "✅" if match else "❌"
        print(
            f"[{counter[0]}/{total}] {icon} 정답={gt:5s} 판정={risk_level:6s} | {item['filename'][:40]}",
            flush=True,
        )

        return {
            "idx": idx,
            "filename": item["filename"],
            "ground_truth": gt,
            "prediction": risk_level,
            "match": match,
            "explanation": explanation,
            "clause_text": item["clause_text"],
            "basis": item.get("basis", []),
        }


async def run_validation(items: list[dict]) -> dict:
    """검증 실행 — Semaphore 병렬 처리로 LLM 호출 동시 발사."""
    total = len(items)

    print(f"\n검증 시작: 총 {total}건 (동시성 {VALIDATION_CONCURRENCY})")
    print("=" * 60)

    semaphore = asyncio.Semaphore(VALIDATION_CONCURRENCY)
    counter = [0]
    raw_results = await asyncio.gather(
        *[_process_item(i, item, total, semaphore, counter) for i, item in enumerate(items)]
    )

    # 원래 순서로 정렬 (병렬이라 도착 순서가 idx와 다름)
    raw_results.sort(key=lambda r: r["idx"])

    correct = 0
    false_safe: list[dict] = []
    false_risky: list[dict] = []
    results: list[dict] = []

    for r in raw_results:
        if r["match"]:
            correct += 1
        else:
            if r["ground_truth"] == "risky" and r["prediction"] in ("safe", "low"):
                false_safe.append({
                    "filename": r["filename"],
                    "risk_level": r["prediction"],
                    "text": r["clause_text"][:200],
                    "basis": r["basis"],
                })
            elif r["ground_truth"] == "safe" and r["prediction"] in ("high", "medium"):
                false_risky.append({
                    "filename": r["filename"],
                    "risk_level": r["prediction"],
                    "text": r["clause_text"][:200],
                })
        results.append({
            "filename": r["filename"],
            "ground_truth": r["ground_truth"],
            "prediction": r["prediction"],
            "match": r["match"],
            "explanation": r["explanation"][:100],
        })

    accuracy = correct / total if total > 0 else 0

    # 결과 요약
    print("\n" + "=" * 60)
    print(f"정확도: {correct}/{total} ({accuracy:.1%})")

    safe_items = [r for r in results if r["ground_truth"] == "safe"]
    risky_items = [r for r in results if r["ground_truth"] == "risky"]

    safe_correct = sum(1 for r in safe_items if r["match"])
    risky_correct = sum(1 for r in risky_items if r["match"])

    if safe_items:
        print(f"  유리(safe) 정확도: {safe_correct}/{len(safe_items)} ({safe_correct/len(safe_items):.1%})")
    if risky_items:
        print(f"  불리(risky) 정확도: {risky_correct}/{len(risky_items)} ({risky_correct/len(risky_items):.1%})")

    print(f"\n오판 분석:")
    print(f"  놓친 위험 (불리→safe/low): {len(false_safe)}건")
    print(f"  거짓 경보 (유리→high/medium): {len(false_risky)}건")

    if false_safe:
        print(f"\n--- 놓친 위험 TOP 5 ---")
        for item in false_safe[:5]:
            basis = item["basis"][0][:80] if item["basis"] else "근거 없음"
            print(f"  [{item['risk_level']}] {item['filename'][:35]}")
            print(f"    조항: {item['text'][:80]}...")
            print(f"    근거: {basis}")

    if false_risky:
        print(f"\n--- 거짓 경보 TOP 5 ---")
        for item in false_risky[:5]:
            print(f"  [{item['risk_level']}] {item['filename'][:35]}")
            print(f"    조항: {item['text'][:80]}...")

    # 결과 파일 저장
    output_path = PROJECT_ROOT / "data" / "validation_result.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "accuracy": accuracy,
            "total": total,
            "correct": correct,
            "safe_accuracy": safe_correct / len(safe_items) if safe_items else 0,
            "risky_accuracy": risky_correct / len(risky_items) if risky_items else 0,
            "false_safe_count": len(false_safe),
            "false_risky_count": len(false_risky),
            "details": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n상세 결과 저장: {output_path}")

    return {
        "accuracy": accuracy,
        "false_safe": false_safe,
        "false_risky": false_risky,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Hub 데이터 기반 분석 정확도 검증")
    parser.add_argument("--limit", type=int, default=0, help="검증 건수 제한 (0=전체)")
    args = parser.parse_args()

    items = load_validation_set()
    print(f"검증 데이터 로드: {len(items)}건")
    print(f"  유리(safe): {sum(1 for i in items if i['ground_truth']=='safe')}건")
    print(f"  불리(risky): {sum(1 for i in items if i['ground_truth']=='risky')}건")

    if args.limit > 0:
        # 유리/불리 균형 맞춰서 샘플링
        safe_items = [i for i in items if i["ground_truth"] == "safe"]
        risky_items = [i for i in items if i["ground_truth"] == "risky"]
        half = args.limit // 2
        items = safe_items[:half] + risky_items[:args.limit - half]
        print(f"  -> {len(items)}건으로 제한")

    asyncio.run(run_validation(items))
