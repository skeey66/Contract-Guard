import asyncio
import json
import logging
import re
import time
from pathlib import Path

from backend.app.models.clause import Clause
from backend.app.config import DATA_DIR
from backend.app.services.llm_service import get_llm
from backend.app.services.retrieval_service import retrieve_similar
from backend.app.services.rule_filter import check_safe_rule, check_high_rule
from backend.app.rag.prompts import (
    get_analysis_prompt,
    get_no_reference_context,
    format_references,
    format_parties,
)

logger = logging.getLogger(__name__)

_PARSE_DEBUG_DIR = Path(DATA_DIR) / "debug" / "parse_failures"


def _dump_parse_failure(clause_index: int, status: str, text: str) -> str:
    """파싱 실패 시 LLM 원문을 파일로 덤프. 원인 분석에 사용."""
    try:
        _PARSE_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        fname = f"{ts}_clause{clause_index}_{status}.txt"
        fpath = _PARSE_DEBUG_DIR / fname
        fpath.write_text(text or "<EMPTY>", encoding="utf-8")
        return str(fpath)
    except Exception as e:
        logger.error(f"덤프 실패: {e}")
        return ""

# Ollama 동시 요청 수 제한 (병목 방지)
_LLM_SEMAPHORE = asyncio.Semaphore(3)
MAX_RETRIES = 1
# 개별 조항 LLM 호출 타임아웃 (초)
PER_CLAUSE_TIMEOUT = 90

# 다중 항(項) 분리용 정규식. ①②③ 또는 "1." / "1)" 형태의 리스트 마커.
# 한 조항 안에 2개 이상 매칭되면 항별 검색 분할을 적용한다.
_CIRCLED_NUM_RE = re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮]")
_NUMBERED_ITEM_RE = re.compile(r"(?:^|\n)\s*\(?(\d{1,2})[.)]\s+")


def _split_clause_into_items(content: str) -> list[str]:
    """조항 본문을 항(項) 단위로 분리. 분리 불가 시 빈 리스트 반환."""
    if len(_CIRCLED_NUM_RE.findall(content)) >= 2:
        parts = _CIRCLED_NUM_RE.split(content)
        items = [p.strip() for p in parts if p.strip()]
        return items if len(items) >= 2 else []

    matches = list(_NUMBERED_ITEM_RE.finditer(content))
    if len(matches) >= 2:
        items = []
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            chunk = content[start:end].strip()
            if chunk:
                items.append(chunk)
        return items if len(items) >= 2 else []

    return []


# 짧은 특약·자유서술 조항은 키워드 기반 query expansion으로 RAG recall 향상
# (특약 본문이 30자 미만이면 보수적, 100자 미만이면 보통, 그 이상이면 미적용)
_SHORT_CLAUSE_THRESHOLD = 100

# 도메인별 query expansion 사전 — 본문에 trigger 키워드가 있으면 해당 법령·쟁점 키워드 추가
_QUERY_EXPANSION: dict[str, list[tuple[str, str]]] = {
    "lease": [
        # (본문에 등장하면, 추가할 검색 키워드)
        ("청소비", "원상복구 임차인 부담 비용 약관규제법 부당"),
        ("관리비", "관리비 산정 내역 공개 임대인 일방 결정"),
        ("중개보수", "중개보수 부담 공인중개사법 임차인 부담"),
        ("이사", "묵시적 갱신 해지 통지 3개월 임차인 해지권 주임법 제6조의2"),
        ("새로운 임차인", "묵시적 갱신 해지 통지 3개월 임차인 해지권 주임법 제6조의2"),
        ("반려동물", "특약 약관규제법 임차인 권리제한"),
        ("흡연", "특약 임차인 생활 제한"),
        ("쓰레기", "관리 의무 임차인 부담"),
        ("연체", "차임연체 해지 주임법 제6조의2 민법 제640조 2기"),
        ("해지", "차임연체 해지 주임법 제6조의2 민법 제640조"),
        ("전대", "민법 제629조 무단 전대 임차권 양도"),
        ("양도", "민법 제629조 무단 전대 임차권 양도"),
        ("원상회복", "원상복구 자연마모 통상 사용 판례"),
        ("원상복구", "원상복구 자연마모 통상 사용 판례"),
        ("계약금", "민법 제565조 해약금 배액상환 포기"),
        ("증액", "주임법 제7조 차임증감청구권 5%"),
        ("보증금", "보증금 반환 우선변제권 주임법 제3조의2"),
    ],
    "sales": [
        ("하자", "민법 제580조 하자담보책임 매도인 6개월"),
        ("계약금", "민법 제565조 해약금 배액상환 포기"),
        ("소유권이전", "동시이행 민법 제536조 이전등기"),
        ("근저당", "근저당 말소 매도인 부담"),
    ],
    "employment": [
        ("위약금", "근로기준법 제20조 위약예정 금지"),
        ("해고", "근로기준법 제23조 정당사유 제26조 30일 예고"),
        ("연차", "근로기준법 제60조 연차유급휴가"),
        ("퇴직", "퇴직급여보장법 제8조 1년 30일분"),
        ("경업", "경업금지 합리적 범위 보상"),
        ("비밀유지", "영업비밀 합리적 범위"),
    ],
    "service": [
        ("대금", "하도급법 제13조 60일 대금 지급"),
        ("검수", "검수 기간 통지 의무 이의제기"),
        ("지식재산", "산출물 저작권 보상"),
        ("하자", "민법 제667조 수급인 담보책임 1년"),
    ],
    "loan": [
        ("이자", "이자제한법 제2조 연 20% 한도"),
        ("기한이익", "기한이익 상실 통지 시정 기회"),
        ("보증", "보증인보호특별법 서면 보증 최고액"),
        ("중도상환", "중도상환 수수료 변제 자유"),
    ],
}


def _expand_query_for_short_clause(clause: Clause, contract_type: str) -> str:
    """짧은 특약·자유서술 조항에 대해 키워드 기반 query expansion 적용.

    원본 본문에 trigger 키워드가 등장하면 관련 법령·쟁점 키워드를 추가하여
    RAG 검색 recall을 높인다. 길이 임계 미만이거나 trigger 미매칭이면 원본 그대로.
    """
    body = clause.content
    if len(body) >= _SHORT_CLAUSE_THRESHOLD and "특약" not in clause.title:
        return body

    expansions = _QUERY_EXPANSION.get(contract_type, [])
    if not expansions:
        return body

    extra_keywords: list[str] = []
    for trigger, keywords in expansions:
        if trigger in body and keywords not in extra_keywords:
            extra_keywords.append(keywords)

    if not extra_keywords:
        return body

    expanded = body + "\n[검색키워드] " + " ".join(extra_keywords)
    logger.info(
        f"[retrieve] 조항 {clause.index} query expansion: "
        f"+{len(extra_keywords)}개 키워드 그룹 ({len(body)}자 → {len(expanded)}자)"
    )
    return expanded


def _retrieve_for_clause(clause: Clause, contract_type: str) -> list[dict]:
    """다중 항 조항이면 항별 검색 후 union, 단일 항이면 기존 방식.

    짧은 특약·자유서술 조항은 query expansion으로 검색 recall 향상.
    """
    items = _split_clause_into_items(clause.content)
    if not items:
        # 짧은 조항·특약은 query expansion 적용
        query_text = _expand_query_for_short_clause(clause, contract_type)
        logger.info(
            f"[retrieve] 조항 {clause.index} 단일항 처리 (content {len(clause.content)}자)"
        )
        return retrieve_similar(query_text, contract_type=contract_type)
    logger.info(
        f"[retrieve] 조항 {clause.index} 항 분할 적용: {len(items)}개 항"
    )

    seen_ids: set[str] = set()
    merged: list[dict] = []
    for item in items:
        for ref in retrieve_similar(item, contract_type=contract_type):
            ref_id = ref.get("id") or ref.get("text", "")[:80]
            if ref_id in seen_ids:
                continue
            seen_ids.add(ref_id)
            merged.append(ref)

    # 다중 항 merge 후 stratified 재선택 — 단일 retrieve_similar의 quota는
    # 항별 호출에서만 보장되므로, merged 후 격차가 큰 표면 키워드 매칭(법률 5개+)이
    # 핵심 패턴 매칭(unfair_clause 1개, sim은 낮지만 의미적으로 정답)을 누르는 문제를 막는다.
    def _cat(r: dict) -> str:
        src = (r.get("metadata") or {}).get("source", "")
        if src in ("law",) or src.startswith("aihub") is False and src in (
            "민법", "주택임대차보호법", "근로기준법", "약관규제법/판례",
            "상가건물임대차보호법", "근로자퇴직급여보장법", "최저임금법",
        ):
            return "law"
        if src == "precedent_kr" or src == "aihub_판결문" or src == "판례/실무":
            return "judgment"
        if src in ("safe_clause", "실무"):
            return "safe_clause"
        if src == "unfair_clause":
            return "unfair_clause"
        return "law" if src else "other"

    by_cat: dict[str, list[dict]] = {"law": [], "safe_clause": [], "judgment": [], "unfair_clause": [], "other": []}
    for r in merged:
        by_cat[_cat(r)].append(r)
    for cat in by_cat:
        by_cat[cat].sort(key=lambda r: r.get("similarity", 0) or 0, reverse=True)

    # 카테고리별 보장 quota: law 3, safe 2, judgment 2, unfair 1 (총 8 reserved, top_k와 정합)
    quota = {"law": 3, "safe_clause": 2, "judgment": 2, "unfair_clause": 1}
    selected: list[dict] = []
    selected_ids: set[str] = set()
    for cat, n in quota.items():
        for r in by_cat[cat][:n]:
            rid = r.get("id") or r.get("text", "")[:80]
            if rid in selected_ids:
                continue
            selected.append(r)
            selected_ids.add(rid)
    # 잔여 슬롯은 전체 유사도 순으로 보충 (사용자에게 노출되는 references_detail용)
    for r in sorted(merged, key=lambda x: x.get("similarity", 0) or 0, reverse=True):
        rid = r.get("id") or r.get("text", "")[:80]
        if rid in selected_ids:
            continue
        selected.append(r)
        selected_ids.add(rid)

    return selected


# 임대차 sub-type별 적용 법령 hint — 분석 프롬프트의 reference_context 앞에 prepend
_LEASE_SUBTYPE_HINTS = {
    "residential": (
        "## 적용 법령 힌트 (반드시 준수)\n"
        "이 계약은 주거용 부동산 임대차로 판단됩니다. **주택임대차보호법(주임법)**이 우선 적용됩니다.\n"
        "- 차임 연체 해지: 주임법 제6조의2 / 민법 제640조 — **2기** 연체 시 해지 가능 (법대로의 기준)\n"
        "- 묵시적 갱신: 임차인은 언제든 해지 통지 가능, 통지 후 3개월 후 효력 (주임법 제6조의2)\n"
        "- 차임 증액: 약정 차임의 5% 이내 (주임법 제7조)\n"
        "- 임차권등기명령·우선변제권: 주임법 제3조·제3조의2\n"
        "- 갱신요구권: 임차인은 1회 갱신 요구 가능 (주임법 제6조의3)\n"
        "조항 내용이 위 법률 기준과 동일하면 위험으로 평가하지 마세요. 상가건물임대차보호법(상임법, 3기 기준)은 **적용되지 않습니다**.\n"
    ),
    "commercial": (
        "## 적용 법령 힌트 (반드시 준수)\n"
        "이 계약은 영업용·상가건물 임대차로 판단됩니다. **상가건물 임대차보호법(상임법)**이 우선 적용됩니다.\n"
        "- 차임 연체 해지: 상임법 제10조의8 — **3기** 연체 시 해지 가능. 2기 연체 해지 조항은 임차인에게 불리(상임법 위반).\n"
        "- 갱신요구권: 임차인은 최초 임대차 기간 포함 10년까지 갱신 요구 가능 (상임법 제10조)\n"
        "- 권리금 회수기회 보호: 상임법 제10조의4\n"
        "- 차임 증액: 약정 차임의 5% 이내 (상임법 제11조)\n"
        "조항 내용이 위 법률 기준과 동일하면 위험으로 평가하지 마세요. 주택임대차보호법(주임법, 2기 기준)은 **적용되지 않습니다**.\n"
    ),
}


def _build_reference_context(
    references: list[dict],
    contract_type: str,
    sub_type: str | None,
) -> str:
    """RAG 참고 자료 텍스트 + sub-type hint를 결합."""
    ref_text = format_references(references)
    if not ref_text:
        ref_text = get_no_reference_context(contract_type)

    # 임대차 sub-type hint를 reference 앞에 prepend
    if contract_type == "lease" and sub_type in _LEASE_SUBTYPE_HINTS:
        return _LEASE_SUBTYPE_HINTS[sub_type] + "\n" + ref_text
    return ref_text


def _strip_thinking(text: str) -> str:
    """thinking 태그를 제거하되, 태그 안에 JSON이 있으면 보존."""
    original = text

    think_blocks = re.findall(r"<think>(.*?)</think>", text, re.DOTALL)
    text_without_think = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)

    if "<think>" in text_without_think:
        after_think = text_without_think.split("<think>", 1)[1]
        text_without_think = text_without_think.split("<think>", 1)[0]
        think_blocks.append(after_think)

    if "</think>" in text_without_think:
        text_without_think = text_without_think.split("</think>", 1)[1]

    cleaned = text_without_think.strip()

    if cleaned and re.search(r"[\[{]", cleaned):
        return cleaned

    for block in think_blocks:
        if re.search(r'"clause_index"|"risk_level"', block):
            return block.strip()

    return cleaned if cleaned else re.sub(r"</?think>", "", original).strip()


def _clean_json_text(text: str) -> str:
    """JSON 파싱 전에 흔한 오류를 정리."""
    # trailing comma 제거
    text = re.sub(r",\s*([}\]])", r"\1", text)
    # LLM이 객체를 } 대신 ] 로 닫는 패턴 교정
    # e.g. "description":"..."],  → "description":"..."},
    text = re.sub(r'"\s*\]\s*,\s*\[\s*"', '"},{"', text)  # "],["  → "},{"
    text = re.sub(r'"\s*\]\s*,\s*\{\s*"', '"},{"', text)  # "],{"  → "},{"
    text = re.sub(r'"\)\s*\]\s*,', '")},', text)           # )"],  → ")},
    # 줄바꿈 제거
    text = text.replace("\n", " ")
    return text


def _try_parse_json(text: str) -> list[dict] | None:
    """JSON 텍스트를 파싱 시도. 성공 시 리스트 반환, 실패 시 None."""
    for candidate in (text, _clean_json_text(text)):
        try:
            data = json.loads(candidate)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return [data]
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _extract_json_from_response(text: str) -> list[dict]:
    """응답 텍스트에서 JSON 배열을 추출. 여러 패턴을 시도."""

    # 1. 코드 블록 안의 JSON
    code_block = re.search(r"```(?:json)?\s*([\[{].*?[}\]])\s*```", text, re.DOTALL)
    if code_block:
        parsed = _try_parse_json(code_block.group(1))
        if parsed:
            return parsed

    # 2. 그대로 파싱 시도 (정상 JSON)
    parsed = _try_parse_json(text)
    if parsed:
        return parsed

    # 3. 대괄호로 둘러싸인 JSON 배열
    bracket_match = re.search(r"\[.*\]", text, re.DOTALL)
    if bracket_match:
        raw = bracket_match.group(0)
        parsed = _try_parse_json(raw)
        if parsed:
            return parsed

    # 4. 깨진 내부 배열 교정 후 재시도 (risks 배열이 깨진 경우)
    fixed_text = re.sub(r'"risks"\s*:\s*\[.*?\]', '"risks":[]', text, flags=re.DOTALL)
    parsed = _try_parse_json(fixed_text)
    if parsed:
        valid = [o for o in parsed if isinstance(o, dict) and ("clause_index" in o or "risk_level" in o)]
        if valid:
            return valid

    # 5. 개별 완성된 JSON 객체 수집
    results = _repair_truncated_array(text)
    if results:
        valid = [o for o in results if isinstance(o, dict) and ("clause_index" in o or "risk_level" in o)]
        if valid:
            return valid

    # 6. 개별 객체에서도 깨진 배열 교정
    results = _repair_truncated_array(fixed_text)
    if results:
        valid = [o for o in results if isinstance(o, dict) and ("clause_index" in o or "risk_level" in o)]
        if valid:
            return valid

    # 7. 최후 폴백 — 정규식으로 clause_index/risk_level만 추출
    # (risks 배열이 과도하게 커서 완성된 객체가 없는 케이스 구제)
    head_match = re.search(
        r'"clause_index"\s*:\s*(\d+).*?"risk_level"\s*:\s*"(safe|low|medium|high)"',
        text,
        re.DOTALL,
    )
    if head_match:
        return [{
            "clause_index": int(head_match.group(1)),
            "risk_level": head_match.group(2),
            "confidence": 0.7,
            "risks": [],
            "explanation": "[JSON 잘림 — 최소 정보만 복구]",
        }]

    return []


def _repair_truncated_array(text: str) -> list[dict] | None:
    """잘린 JSON 배열에서 완성된 객체들만 추출."""
    results = []
    depth = 0
    start = None

    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                fragment = text[start:i + 1]
                try:
                    obj = json.loads(fragment)
                    results.append(obj)
                except json.JSONDecodeError:
                    # 내부 배열이 깨진 경우, 깨진 배열을 제거 후 재시도
                    obj = _try_fix_broken_object(fragment)
                    if obj:
                        results.append(obj)
                start = None

    return results if results else None


def _try_fix_broken_object(fragment: str) -> dict | None:
    """JSON 객체 내부의 깨진 배열을 빈 배열로 대체하여 파싱 시도."""
    # risks 배열이 깨진 경우: "risks":[...깨진내용...] → "risks":[]
    fixed = re.sub(r'"risks"\s*:\s*\[.*?\]', '"risks":[]', fragment, flags=re.DOTALL)
    for candidate in (fixed, _clean_json_text(fixed)):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            continue
    return None


async def _invoke_llm(llm, messages) -> str:
    """LLM 호출 후 응답 텍스트를 반환."""
    response = await llm.ainvoke(messages)
    text = response.content
    if not text and hasattr(response, "text"):
        text = response.text
    if not text:
        text = str(response)
    return _strip_thinking(text)


_SAFE_EXPLANATIONS = {
    "목적물 식별 기재": "임대 목적물의 소재지와 면적을 특정하는 기본 기재 사항으로, 법적 위험이 없는 조항입니다.",
    "단순 임대 조건 기재": "임대 목적물과 보증금·월차임 금액만을 명시한 단순 사실 기재 조항으로, 임차인에게 위험 요소가 없는 기본 조항입니다.",
    "보증금·차임 금액 및 지급 일정 기재": "보증금·차임 금액과 계약금·잔금 지급 일정을 명시한 단순 사실 기재 조항으로, 임차인에게 위험 요소가 없습니다.",
    "단순 금액·납부일정 기재": "보증금, 차임 등 금액과 납부 일정을 기재한 조항으로, 특별한 위험 요소가 없습니다.",
    "종료일 보증금 반환": "임대차 종료 시 보증금 반환을 규정한 조항으로, 임차인의 권리를 보장하는 내용입니다.",
    "법정 증액 한도 준수": "주택임대차보호법 제7조에 따른 연 5% 이내 증액 한도를 준수하고 있어 안전합니다.",
    "자연마모 제외": "통상적인 사용에 따른 자연마모를 원상복구 대상에서 제외하여 임차인을 보호하는 조항입니다.",
    "법률상 당연한 전대 제한": "민법상 임대인의 동의 없는 전대·양도를 제한하는 것은 법률상 당연한 규정입니다.",
    "법정 수선 의무 분담": "민법 제623조에 따라 주요 수선은 임대인, 소규모 수선은 임차인이 부담하는 합리적 분담입니다.",
    "갱신요구권 인정": "임차인의 계약 갱신 요구권을 인정하는 조항으로, 임차인 보호에 부합합니다.",
}

_HIGH_EXPLANATIONS = {
    "차임증액_무제한": "주택임대차보호법상 연 5% 한도를 초과하는 증액을 허용하고 있어, 임차인에게 과도한 부담이 될 수 있습니다.",
    "보증금_미반환_위험": "보증금 반환이 지연되거나 거부될 수 있는 조건이 포함되어 있어, 임차인의 보증금 회수에 위험이 있습니다.",
    "수선의무_전가": "임대인이 부담해야 할 수선 의무를 임차인에게 전가하고 있어, 민법 제623조에 반하는 불공정한 조항입니다.",
    "권리제한": "임차인의 정당한 권리를 부당하게 제한하거나, 임대인에게 과도한 재량권을 부여하는 조항입니다.",
    "묵시적_갱신_배제": "주택임대차보호법상 보장되는 묵시적 갱신 또는 갱신요구권을 배제하는 조항으로, 임차인에게 불리합니다.",
}


def _rule_safe_result(clause: Clause, reason: str) -> dict:
    """사전 safe 룰 매칭 시 LLM 호출 없이 반환할 결과."""
    explanation = _SAFE_EXPLANATIONS.get(reason, f"해당 조항은 법률상 일반적인 내용으로, 특별한 위험 요소가 없습니다.")
    return {
      "clause_index": clause.index,
      "risk_level": "safe",
      "confidence": 0.95,
      "risks": [],
      "explanation": explanation,
    }


def _rule_high_result(clause: Clause, risk_type: str, reason: str) -> dict:
    """사후 high 룰 매칭 시 LLM 결과를 교정할 때 사용."""
    explanation = _HIGH_EXPLANATIONS.get(risk_type, reason)
    return {
      "clause_index": clause.index,
      "risk_level": "high",
      "confidence": 0.95,
      "risks": [{
        "risk_type": risk_type,
        "description": reason,
        "suggestion": "해당 조항 삭제 또는 법정 기준에 맞게 재협상 필요",
      }],
      "explanation": explanation,
    }


async def _analyze_single_clause(
    clause: Clause,
    contract_type: str = "lease",
    parties: dict[str, str] | None = None,
    sub_type: str | None = None,
) -> tuple[Clause, str, list[dict], str]:
    """단일 조항을 LLM으로 분석. 세마포어로 동시 요청 제한, 파싱 실패 시 1회 재시도.

    반환값 4번째 원소는 상태 힌트: "ok" | "timeout" | "empty" | "parse_failed".
    호출자는 이 힌트로 무음 폴백을 가시화한다.
    """
    references = _retrieve_for_clause(clause, contract_type)

    ref_text = _build_reference_context(references, contract_type, sub_type)

    clauses_text = f"\n[{clause.index}] {clause.title}: {clause.content}\n"

    prompt = get_analysis_prompt(contract_type)
    llm = get_llm()
    messages = prompt.format_messages(
        clauses_text=clauses_text,
        reference_context=ref_text,
        parties_text=format_parties(parties),
    )

    last_text = ""
    last_status = "empty"
    for attempt in range(1 + MAX_RETRIES):
        try:
            async with _LLM_SEMAPHORE:
                text = await asyncio.wait_for(
                    _invoke_llm(llm, messages),
                    timeout=PER_CLAUSE_TIMEOUT,
                )
        except asyncio.TimeoutError:
            logger.warning(f"조항 {clause.index} 타임아웃 ({PER_CLAUSE_TIMEOUT}초, 시도 {attempt + 1})")
            last_status = "timeout"
            continue

        if not text:
            logger.warning(f"조항 {clause.index} 빈 응답 (시도 {attempt + 1})")
            last_status = "empty"
            continue

        parsed = _extract_json_from_response(text)
        if parsed:
            return clause, text, references, "ok"

        last_text = text
        last_status = "parse_failed"
        logger.warning(
            f"조항 {clause.index} 파싱 실패 (시도 {attempt + 1}/{1 + MAX_RETRIES}). "
            f"응답 앞부분: {text[:200]}"
        )

    return clause, last_text, references, last_status


async def analyze_all_clauses(
    clauses: list[Clause],
    contract_type: str = "lease",
    parties: dict[str, str] | None = None,
    sub_type: str | None = None,
) -> dict:
    """전체 조항을 조항별 개별 LLM 호출로 분석.

    결정적 룰 레이어 적용 순서:
      1. 사전 safe 룰 매칭 시 LLM 호출 없이 safe 확정
      2. LLM 호출 후 사후 high 룰 매칭 시 high로 강제 교정
    """
    sub_label = f"/{sub_type}" if sub_type else ""
    logger.info(
        f"LLM 분석 시작: {len(clauses)}개 조항 (유형: {contract_type}{sub_label})"
    )

    all_parsed = []
    per_clause_refs: dict[int, list[dict]] = {}

    # 1단계: 사전 safe / high 룰로 LLM 호출 대상 필터링
    llm_target_clauses: list[Clause] = []
    pre_safe_count = 0
    pre_high_count = 0
    for clause in clauses:
        is_safe, reason = check_safe_rule(clause, contract_type)
        if is_safe:
            all_parsed.append(_rule_safe_result(clause, reason))
            per_clause_refs[clause.index] = []
            pre_safe_count += 1
            logger.info(f"조항 {clause.index} 사전 safe 룰 매칭: {reason}")
            continue
        is_high, risk_type, high_reason = check_high_rule(clause, contract_type)
        if is_high:
            all_parsed.append(_rule_high_result(clause, risk_type, high_reason))
            per_clause_refs[clause.index] = []
            pre_high_count += 1
            logger.info(f"조항 {clause.index} 사전 high 룰 매칭: {risk_type} ({high_reason})")
            continue
        llm_target_clauses.append(clause)

    logger.info(
        f"사전 필터: safe {pre_safe_count}개 / high {pre_high_count}개 확정, "
        f"{len(llm_target_clauses)}개 LLM 분석"
    )

    # 2단계: 남은 조항만 LLM 호출
    tasks = [
        _analyze_single_clause(c, contract_type, parties, sub_type)
        for c in llm_target_clauses
    ]
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    for i, resp in enumerate(responses):
        clause = llm_target_clauses[i]
        if isinstance(resp, Exception):
            # 무음 폴백 방지: 예외도 명시적 스텁으로 남긴다
            logger.error(f"조항 {clause.index} 분석 실패: {resp}")
            all_parsed.append({
                "clause_index": clause.index,
                "risk_level": "medium",
                "confidence": 0.3,
                "risks": [],
                "explanation": f"[분석 오류] LLM 호출 중 오류가 발생했습니다: {type(resp).__name__}. 수동 검토가 필요합니다.",
                "_status": "llm_error",
            })
            per_clause_refs[clause.index] = []
            continue

        _, text, refs, status_hint = resp
        per_clause_refs[clause.index] = refs

        parsed = _extract_json_from_response(text)

        if not parsed:
            logger.warning(f"조항 {clause.index} 파싱 실패. LLM 원문:\n{text[:500]}")
            # 파싱 실패 시 룰 레이어로 폴백 (사전 필터에서 매칭되지 않은 조항이지만,
            # 패턴이 추가되거나 정규화 차이로 사후에 매칭될 수 있음)
            is_high_fb, risk_type_fb, reason_fb = check_high_rule(clause, contract_type)
            if is_high_fb:
                all_parsed.append(_rule_high_result(clause, risk_type_fb, reason_fb))
                logger.info(f"조항 {clause.index} 파싱 실패 → high 룰 폴백: {risk_type_fb}")
                continue
            is_safe_fb, safe_reason_fb = check_safe_rule(clause, contract_type)
            if is_safe_fb:
                all_parsed.append(_rule_safe_result(clause, safe_reason_fb))
                logger.info(f"조항 {clause.index} 파싱 실패 → safe 룰 폴백: {safe_reason_fb}")
                continue
            # 룰 폴백도 실패 → 파싱 실패 상태를 명시적으로 남긴다 (드롭 금지)
            status_label = status_hint if status_hint != "ok" else "parse_failed"
            # 원문 덤프 — 원인 분석용
            dump_path = _dump_parse_failure(clause.index, status_label, text)
            if dump_path:
                logger.warning(f"조항 {clause.index} 원문 덤프: {dump_path}")
            explanation_map = {
                "timeout": "[분석 실패] LLM 응답 타임아웃. 수동 검토가 필요합니다.",
                "empty": "[분석 실패] LLM이 빈 응답을 반환했습니다. 수동 검토가 필요합니다.",
                "parse_failed": "[분석 실패] LLM 응답을 JSON으로 해석할 수 없습니다. 수동 검토가 필요합니다.",
            }
            all_parsed.append({
                "clause_index": clause.index,
                "risk_level": "medium",
                "confidence": 0.3,
                "risks": [],
                "explanation": explanation_map.get(status_label, explanation_map["parse_failed"]),
                "_status": status_label,
            })
            continue

        result = parsed[0]
        result["clause_index"] = clause.index

        # 3단계: 사후 high 룰 교정 — LLM이 safe로 판정했지만 명백한 high 패턴이면 교정
        # medium은 LLM의 판단을 존중 (맥락상 이유가 있을 수 있음)
        is_high, risk_type, reason = check_high_rule(clause, contract_type)
        llm_level = (result.get("risk_level") or "").lower().strip()
        if is_high and llm_level == "safe":
            logger.info(
                f"조항 {clause.index} 사후 high 룰 교정: "
                f"LLM={llm_level} → high ({reason})"
            )
            result = _rule_high_result(clause, risk_type, reason)

        all_parsed.append(result)
        logger.info(f"조항 {clause.index} 파싱 성공")

    logger.info(f"총 {len(all_parsed)}/{len(clauses)}개 조항 완료")

    return {
        "parsed_list": all_parsed,
        "per_clause_refs": per_clause_refs,
    }
