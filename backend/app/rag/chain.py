import asyncio
import json
import logging
import re

from backend.app.models.clause import Clause
from backend.app.services.llm_service import get_llm
from backend.app.services.retrieval_service import retrieve_similar
from backend.app.services.rule_filter import check_safe_rule, check_high_rule
from backend.app.rag.prompts import get_analysis_prompt, get_no_reference_context, format_references

logger = logging.getLogger(__name__)

# Ollama 동시 요청 수 제한 (병목 방지)
_LLM_SEMAPHORE = asyncio.Semaphore(3)
MAX_RETRIES = 1
# 개별 조항 LLM 호출 타임아웃 (초)
PER_CLAUSE_TIMEOUT = 90


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


def _rule_safe_result(clause: Clause, reason: str) -> dict:
    """사전 safe 룰 매칭 시 LLM 호출 없이 반환할 결과."""
    return {
      "clause_index": clause.index,
      "risk_level": "safe",
      "confidence": 0.95,
      "risks": [],
      "explanation": f"[룰] {reason}",
    }


def _rule_high_result(clause: Clause, risk_type: str, reason: str) -> dict:
    """사후 high 룰 매칭 시 LLM 결과를 교정할 때 사용."""
    return {
      "clause_index": clause.index,
      "risk_level": "high",
      "confidence": 0.95,
      "risks": [{
        "risk_type": risk_type,
        "description": reason,
        "suggestion": "해당 조항 삭제 또는 법정 기준에 맞게 재협상 필요",
      }],
      "explanation": f"[룰] {reason}",
    }


async def _analyze_single_clause(
    clause: Clause,
    contract_type: str = "lease",
) -> tuple[Clause, str, list[dict]]:
    """단일 조항을 LLM으로 분석. 세마포어로 동시 요청 제한, 파싱 실패 시 1회 재시도."""
    references = retrieve_similar(clause.content, contract_type=contract_type)

    ref_text = format_references(references)
    if not ref_text:
        ref_text = get_no_reference_context(contract_type)

    clauses_text = f"\n[{clause.index}] {clause.title}: {clause.content}\n"

    prompt = get_analysis_prompt(contract_type)
    llm = get_llm()
    messages = prompt.format_messages(
        clauses_text=clauses_text,
        reference_context=ref_text,
    )

    last_text = ""
    for attempt in range(1 + MAX_RETRIES):
        try:
            async with _LLM_SEMAPHORE:
                text = await asyncio.wait_for(
                    _invoke_llm(llm, messages),
                    timeout=PER_CLAUSE_TIMEOUT,
                )
        except asyncio.TimeoutError:
            logger.warning(f"조항 {clause.index} 타임아웃 ({PER_CLAUSE_TIMEOUT}초, 시도 {attempt + 1})")
            continue

        if not text:
            logger.warning(f"조항 {clause.index} 빈 응답 (시도 {attempt + 1})")
            continue

        parsed = _extract_json_from_response(text)
        if parsed:
            return clause, text, references

        last_text = text
        logger.warning(
            f"조항 {clause.index} 파싱 실패 (시도 {attempt + 1}/{1 + MAX_RETRIES}). "
            f"응답 앞부분: {text[:200]}"
        )

    return clause, last_text, references


async def analyze_all_clauses(
    clauses: list[Clause],
    contract_type: str = "lease",
) -> dict:
    """전체 조항을 조항별 개별 LLM 호출로 분석.

    결정적 룰 레이어 적용 순서:
      1. 사전 safe 룰 매칭 시 LLM 호출 없이 safe 확정
      2. LLM 호출 후 사후 high 룰 매칭 시 high로 강제 교정
    """
    logger.info(f"LLM 분석 시작: {len(clauses)}개 조항 (유형: {contract_type})")

    all_parsed = []
    per_clause_refs: dict[int, list[dict]] = {}

    # 1단계: 사전 safe 룰로 LLM 호출 대상 필터링
    llm_target_clauses: list[Clause] = []
    for clause in clauses:
        is_safe, reason = check_safe_rule(clause, contract_type)
        if is_safe:
            all_parsed.append(_rule_safe_result(clause, reason))
            per_clause_refs[clause.index] = []
            logger.info(f"조항 {clause.index} 사전 safe 룰 매칭: {reason}")
        else:
            llm_target_clauses.append(clause)

    logger.info(
        f"사전 필터: {len(clauses) - len(llm_target_clauses)}개 safe 확정, "
        f"{len(llm_target_clauses)}개 LLM 분석"
    )

    # 2단계: 남은 조항만 LLM 호출
    tasks = [_analyze_single_clause(c, contract_type) for c in llm_target_clauses]
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    for i, resp in enumerate(responses):
        clause = llm_target_clauses[i]
        if isinstance(resp, Exception):
            logger.error(f"조항 {clause.index} 분석 실패: {resp}")
            continue

        _, text, refs = resp
        per_clause_refs[clause.index] = refs

        parsed = _extract_json_from_response(text)

        if not parsed:
            logger.warning(f"조항 {clause.index} 파싱 실패. LLM 원문:\n{text[:500]}")
            continue

        result = parsed[0]
        result["clause_index"] = clause.index

        # 3단계: 사후 high 룰 교정 — LLM 판정이 safe/medium인데 명백한 high 패턴이면 high로 강제
        is_high, risk_type, reason = check_high_rule(clause, contract_type)
        llm_level = (result.get("risk_level") or "").lower().strip()
        if is_high and llm_level not in ("high",):
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
