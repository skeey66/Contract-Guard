"""법률 데이터를 파싱하여 ChromaDB에 인덱싱하는 스크립트.

사용법:
    # 모든 계약 유형의 내장 데이터로 KB 구축
    python -m backend.scripts.build_kb

    # AI HUB 데이터 포함 (임대차)
    python -m backend.scripts.build_kb --data-dir data/raw/aihub
"""

import argparse
import json
import uuid
from pathlib import Path

from backend.app.contract_types import CONTRACT_TYPES


def get_all_builtin_data() -> list[dict]:
    """모든 계약 유형의 내장 KB 데이터를 contract_type metadata와 함께 반환."""
    items = []
    for ct_key, ct_config in CONTRACT_TYPES.items():
        for entry in ct_config["builtin_kb"]:
            metadata = {**entry["metadata"], "contract_type": ct_key}
            items.append({
                "id": entry["id"],
                "text": entry["text"],
                "metadata": metadata,
            })
    return items


LEASE_KEYWORDS = ["임대", "임차", "보증금", "차임", "월세", "전세", "임대차", "주택임대"]
SALES_KEYWORDS = ["매매", "매도", "매수", "소유권이전", "잔금", "계약금"]

# 파일명 키워드 → (contract_type, topic)
CLAUSE_FILE_MAPPING = {
    "임대차": ("lease", "임대차_약관"),
    "매매계약": ("sales", "매매_약관"),
}


def _is_lease_related(text: str) -> bool:
    return any(kw in text for kw in LEASE_KEYWORDS)


def _is_sales_related(text: str) -> bool:
    return any(kw in text for kw in SALES_KEYWORDS)


def _normalize_filename(name: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFC", name)


def _load_clause_data(data_path: Path) -> list[dict]:
    """약관 라벨링데이터(JSON)에서 지원 계약 유형 항목을 파싱."""
    items = []
    for json_file in data_path.rglob("*.json"):
        nfc_name = _normalize_filename(json_file.name)

        # 파일명에서 계약 유형 매칭
        matched = None
        for keyword, (ct, topic) in CLAUSE_FILE_MAPPING.items():
            if keyword in nfc_name:
                matched = (ct, topic)
                break
        if not matched:
            continue
        contract_type, topic = matched

        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue

        # 약관 조항 텍스트
        articles = data.get("clauseArticle", [])
        clause_text = "\n".join(articles) if isinstance(articles, list) else str(articles)
        if not clause_text.strip():
            continue

        # 위법성 판단 근거
        bases = data.get("illdcssBasiss", [])
        basis_text = "\n".join(bases) if isinstance(bases, list) else str(bases)

        # 관련 법령
        laws = data.get("relateLaword", [])
        law_text = "\n".join(laws) if isinstance(laws, list) else str(laws)

        # 유불리 판단: "1"=유리, "2"=불리
        dv = data.get("dvAntageous", "")
        advantage = "불리" if str(dv) == "2" else "유리"

        # 조합된 텍스트
        combined = f"[약관-{advantage}] {clause_text}"
        if basis_text.strip():
            combined += f"\n판단근거: {basis_text}"
        if law_text.strip():
            combined += f"\n관련법령: {law_text}"

        items.append({
            "id": str(uuid.uuid4()),
            "text": combined[:2000],
            "metadata": {
                "source": "aihub_약관",
                "filename": nfc_name,
                "topic": topic,
                "advantage": advantage,
                "contract_type": contract_type,
            },
        })

    return items


def _load_judgment_data(data_path: Path) -> list[dict]:
    """판결문 라벨링데이터(JSON)에서 임대차 관련 민사 판결문을 파싱."""
    items = []
    # 민사 판결문만 탐색
    for json_file in data_path.rglob("*.json"):
        nfc_path = _normalize_filename(str(json_file))
        if "민사" not in nfc_path:
            continue

        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue

        # 사건명으로 1차 필터
        info = data.get("info", {})
        case_nm = info.get("caseNm", "")
        relate_laws = info.get("relateLaword", [])
        law_str = " ".join(relate_laws) if isinstance(relate_laws, list) else str(relate_laws)

        # 기초사실 + 판단 텍스트 (dict 안에 list가 중첩된 구조
        facts_raw = data.get("facts", {})
        if isinstance(facts_raw, dict):
            facts_list = []
            for v in facts_raw.values():
                if isinstance(v, list):
                    facts_list.extend(v)
            facts_text = "\n".join(facts_list)
        else:
            facts_text = str(facts_raw)

        dcss_raw = data.get("dcss", {})
        if isinstance(dcss_raw, dict):
            dcss_list = []
            for v in dcss_raw.values():
                if isinstance(v, list):
                    dcss_list.extend(v)
            dcss_text = "\n".join(dcss_list)
        else:
            dcss_text = str(dcss_raw)

        full_text = f"{case_nm} {law_str} {facts_text} {dcss_text}"

        # 계약 유형 판별
        if _is_lease_related(full_text):
            contract_type, topic = "lease", "임대차_판결"
        elif _is_sales_related(full_text):
            contract_type, topic = "sales", "매매_판결"
        else:
            continue

        case_no = info.get("caseNo", "")
        court = info.get("courtNm", "")

        combined = f"[판결문] {court} {case_no} - {case_nm}"
        if facts_text.strip():
            combined += f"\n기초사실: {facts_text[:800]}"
        if dcss_text.strip():
            combined += f"\n판단: {dcss_text[:800]}"
        if law_str.strip():
            combined += f"\n관련법령: {law_str}"

        items.append({
            "id": str(uuid.uuid4()),
            "text": combined[:2000],
            "metadata": {
                "source": "aihub_판결문",
                "case_no": case_no,
                "court": court,
                "topic": topic,
                "contract_type": contract_type,
            },
        })

    return items


def load_aihub_data(data_dir: str) -> list[dict]:
    """AI HUB 법률 데이터에서 임대차 관련 항목을 추출."""
    data_path = Path(data_dir)
    if not data_path.exists():
        print(f"[INFO] 데이터 디렉토리가 없습니다: {data_dir}")
        return []

    print("  약관 데이터 로딩 중...")
    clause_items = _load_clause_data(data_path)
    clause_by_type = {}
    for item in clause_items:
        ct = item["metadata"]["contract_type"]
        clause_by_type[ct] = clause_by_type.get(ct, 0) + 1
    for ct, count in clause_by_type.items():
        print(f"    약관 {ct}: {count}건")

    print("  판결문 데이터 로딩 중...")
    judgment_items = _load_judgment_data(data_path)
    judgment_by_type = {}
    for item in judgment_items:
        ct = item["metadata"]["contract_type"]
        judgment_by_type[ct] = judgment_by_type.get(ct, 0) + 1
    for ct, count in judgment_by_type.items():
        print(f"    판결문 {ct}: {count}건")

    return clause_items + judgment_items


def build_knowledge_base(data_dir: str | None = None):
    from backend.app.services import chroma_service
    from backend.app.services import bm25_service

    print("[1/3] 데이터 수집 중...")
    items = get_all_builtin_data()

    type_counts = {}
    for item in items:
        ct = item["metadata"]["contract_type"]
        type_counts[ct] = type_counts.get(ct, 0) + 1
    for ct, count in type_counts.items():
        ct_name = CONTRACT_TYPES[ct]["name"]
        print(f"  내장 데이터 ({ct_name}): {count}건")

    if data_dir:
        aihub_items = load_aihub_data(data_dir)
        print(f"  AI HUB 데이터: {len(aihub_items)}건")
        items.extend(aihub_items)

    print(f"[2/3] 임베딩 생성 + ChromaDB 저장 중... (총 {len(items)}건)")
    ids = [item["id"] for item in items]
    texts = [item["text"] for item in items]
    metadatas = [item.get("metadata", {}) for item in items]

    batch_size = 100
    for i in range(0, len(ids), batch_size):
        end = min(i + batch_size, len(ids))
        chroma_service.add_documents(
            ids=ids[i:end],
            documents=texts[i:end],
            metadatas=metadatas[i:end],
        )

    status = chroma_service.collection_status()
    print(f"  ChromaDB 컬렉션 '{status['name']}' 에 {status['count']}건 저장됨.")

    print(f"[3/3] BM25 인덱스 구축 중... (총 {len(items)}건)")
    bm25_service.build_all_indices(items)
    print("완료! ChromaDB + BM25 하이브리드 검색 준비 완료.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="법률 지식베이스 구축")
    parser.add_argument(
        "--data-dir",
        default=None,
        help="AI HUB 데이터 디렉토리 경로 (없으면 내장 데이터만 사용)",
    )
    args = parser.parse_args()
    build_knowledge_base(data_dir=args.data_dir)
