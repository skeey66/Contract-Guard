"""법률 데이터를 파싱하여 ChromaDB에 인덱싱하는 스크립트.

사용법:
    # 모든 계약 유형의 내장 데이터로 KB 구축
    python -m backend.scripts.build_kb

    # AI HUB 데이터 포함 (임대차)
    python -m backend.scripts.build_kb --data-dir data/raw/aihub
"""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from backend.app.contract_types import CONTRACT_TYPES
from backend.app.config import settings, DATA_DIR


def _chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """긴 텍스트를 고정 크기 청크로 분할 (오버랩 포함).

    임베딩 한 벡터에 너무 많은 토픽이 섞이지 않도록 판결문 판단 섹션 등을 쪼갤 때 사용.
    """
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def _content_id(prefix: str, text: str) -> str:
  # 동일 텍스트에 대해 항상 같은 ID를 발급하여 재빌드 시 중복 삽입 방지
  return f"{prefix}-{hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]}"


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
    """약관 라벨링데이터(JSON)에서 지원 계약 유형 항목을 파싱.

    청크 전략: 하나의 JSON 파일에 여러 clauseArticle이 있을 때
    기존처럼 전부 이어 붙이면 한 벡터에 여러 조항이 섞여 검색 정밀도가 떨어진다.
    따라서 조항 하나당 1건의 문서로 분리하되, 판단근거/관련법령은 짧은 꼬리 컨텍스트로 덧붙인다.
    """
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

        # 약관 조항 텍스트 — list면 각 원소를 별도 조항으로 처리
        articles_raw = data.get("clauseArticle", [])
        if isinstance(articles_raw, list):
            articles = [str(a).strip() for a in articles_raw if str(a).strip()]
        else:
            articles = [str(articles_raw).strip()] if str(articles_raw).strip() else []
        if not articles:
            continue

        # 위법성 판단 근거 (공통 컨텍스트)
        bases = data.get("illdcssBasiss", [])
        basis_text = "\n".join(bases) if isinstance(bases, list) else str(bases)

        # 관련 법령 (공통 컨텍스트)
        laws = data.get("relateLaword", [])
        law_text = "\n".join(laws) if isinstance(laws, list) else str(laws)

        # 유불리 판단: "1"=유리, "2"=불리
        dv = data.get("dvAntageous", "")
        advantage = "불리" if str(dv) == "2" else "유리"

        for idx, article in enumerate(articles):
            if len(article) < 10:
                continue
            combined = f"[약관-{advantage}] {article}"
            if basis_text.strip():
                combined += f"\n판단근거: {basis_text[:300]}"
            if law_text.strip():
                combined += f"\n관련법령: {law_text[:200]}"

            text_body = combined[:1500]
            items.append({
                "id": _content_id("clause", text_body),
                "text": text_body,
                "metadata": {
                    "source": "aihub_약관",
                    "filename": nfc_name,
                    "topic": topic,
                    "advantage": advantage,
                    "contract_type": contract_type,
                    "article_idx": idx,
                },
            })

    return items


def _load_judgment_data(data_path: Path) -> list[dict]:
    """판결문 라벨링데이터(JSON)에서 임대차/매매 관련 민사 판결문을 파싱.

    청크 전략: 하나의 판결문을 (판단, 기초사실) 두 섹션으로 분리 인덱싱한다.
    - 판단(dcss)은 핵심 정보이므로 1500자 청크 + 150자 오버랩으로 분할
    - 기초사실(facts)은 맥락 참조용이므로 최대 1500자 단일 문서
    기존 800자 절단으로 핵심 판단 이유가 잘리던 문제를 해결한다.
    """
    items = []
    for json_file in data_path.rglob("*.json"):
        nfc_path = _normalize_filename(str(json_file))
        if "민사" not in nfc_path:
            continue

        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue

        info = data.get("info", {})
        case_nm = info.get("caseNm", "")
        relate_laws = info.get("relateLaword", [])
        law_str = " ".join(relate_laws) if isinstance(relate_laws, list) else str(relate_laws)

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

        full_filter = f"{case_nm} {law_str} {facts_text} {dcss_text}"
        if _is_lease_related(full_filter):
            contract_type, topic = "lease", "임대차_판결"
        elif _is_sales_related(full_filter):
            contract_type, topic = "sales", "매매_판결"
        else:
            continue

        case_no = info.get("caseNo", "")
        court = info.get("courtNm", "")
        header = f"[판결문] {court} {case_no} - {case_nm}"
        law_tail = f"\n관련법령: {law_str[:200]}" if law_str.strip() else ""

        # 판단 섹션 — 청크 분할
        dcss_clean = dcss_text.strip()
        if dcss_clean:
            chunks = _chunk_text(dcss_clean, size=1500, overlap=150)
            for idx, chunk in enumerate(chunks):
                combined = f"{header}\n판단: {chunk}{law_tail}"
                items.append({
                    "id": _content_id("judgment-dcss", combined),
                    "text": combined,
                    "metadata": {
                        "source": "aihub_판결문",
                        "case_no": case_no,
                        "court": court,
                        "topic": topic,
                        "contract_type": contract_type,
                        "section": "판단",
                        "chunk_idx": idx,
                    },
                })

        # 기초사실 섹션 — 단일 문서
        facts_clean = facts_text.strip()
        if facts_clean:
            facts_trimmed = facts_clean[:1500]
            combined = f"{header}\n기초사실: {facts_trimmed}{law_tail}"
            items.append({
                "id": _content_id("judgment-facts", combined),
                "text": combined,
                "metadata": {
                    "source": "aihub_판결문",
                    "case_no": case_no,
                    "court": court,
                    "topic": topic,
                    "contract_type": contract_type,
                    "section": "기초사실",
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


def build_knowledge_base(data_dir: str | None = None, clear: bool = False):
    if clear:
        chroma_dir = Path(settings.chroma_persist_dir)
        bm25_dir = Path(DATA_DIR) / "bm25"
        if chroma_dir.exists():
            shutil.rmtree(chroma_dir)
            print(f"[CLEAR] 기존 ChromaDB 삭제: {chroma_dir}")
        if bm25_dir.exists():
            shutil.rmtree(bm25_dir)
            print(f"[CLEAR] 기존 BM25 인덱스 삭제: {bm25_dir}")

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

    # 동일 텍스트 중복 제거 (hash 기반 id 덕분에 가능)
    seen_ids = set()
    dedup_items = []
    for item in items:
      if item["id"] in seen_ids:
        continue
      seen_ids.add(item["id"])
      dedup_items.append(item)
    dropped = len(items) - len(dedup_items)
    if dropped:
      print(f"  중복 텍스트 {dropped}건 제거 → {len(dedup_items)}건")
    items = dedup_items

    print(f"[2/3] 임베딩 생성 + ChromaDB 저장 중... (총 {len(items)}건)")
    ids = [item["id"] for item in items]
    texts = [item["text"] for item in items]
    # RRF 융합을 위해 metadata 안에도 id를 포함 (retrieval_service가 doc.metadata.get("id")로 조회)
    metadatas = []
    for item in items:
      md = dict(item.get("metadata", {}))
      md["id"] = item["id"]
      metadatas.append(md)

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
    parser.add_argument(
        "--clear",
        action="store_true",
        help="빌드 전에 기존 ChromaDB/BM25 인덱스를 삭제 (재빌드 시 권장)",
    )
    args = parser.parse_args()
    build_knowledge_base(data_dir=args.data_dir, clear=args.clear)
