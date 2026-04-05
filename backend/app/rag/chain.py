import asyncio
import json
import logging
import re

from backend.app.models.clause import Clause
from backend.app.services.llm_service import get_llm
from backend.app.services.retrieval_service import retrieve_similar
from backend.app.rag.prompts import get_analysis_prompt, get_no_reference_context, format_references

logger = logging.getLogger(__name__)

BATCH_SIZE = 3


def _strip_thinking(text: str) -> str:
    """thinking 태그 내용을 제거하고 실제 응답만 반환."""
    if "</think>" in text:
        return text.split("</think>", 1)[1].strip()
    if "<think>" in text:
        return text.split("<think>", 1)[0].strip()
    return text.strip()


def _clean_json_text(text: str) -> str:
    """JSON 파싱 전에 흔한 오류를 정리."""
    # 마지막 쉼표 제거 (trailing comma)
    text = re.sub(r",\s*([}\]])", r"\1", text)
    # 줄바꿈이 포함된 문자열 값 처리
    text = text.replace("\n", " ")
    return text


def _extract_json_from_response(text: str) -> list[dict]:
    """응답 텍스트에서 JSON 배열을 추출. 여러 패턴을 시도."""

    # 1. 코드 블록 안의 JSON
    code_block = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if code_block:
        try:
            return json.loads(_clean_json_text(code_block.group(1)))
        except json.JSONDecodeError:
            pass

    # 2. 대괄호로 둘러싸인 JSON 배열 (가장 바깥쪽 매칭)
    bracket_match = re.search(r"\[.*\]", text, re.DOTALL)
    if bracket_match:
        raw = bracket_match.group(0)
        # 그대로 시도
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        # 정리 후 시도
        try:
            return json.loads(_clean_json_text(raw))
        except json.JSONDecodeError:
            pass
        # 잘린 JSON 복구: 마지막 완성된 객체까지만 파싱
        repaired = _repair_truncated_array(raw)
        if repaired:
            return repaired

    # 3. 개별 JSON 객체들 수집
    objects = re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text)
    result = []
    for obj_str in objects:
        try:
            obj = json.loads(obj_str)
            if "clause_index" in obj or "risk_level" in obj:
                result.append(obj)
        except json.JSONDecodeError:
            try:
                obj = json.loads(_clean_json_text(obj_str))
                if "clause_index" in obj or "risk_level" in obj:
                    result.append(obj)
            except json.JSONDecodeError:
                continue
    return result


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
                try:
                    obj = json.loads(text[start:i + 1])
                    results.append(obj)
                except json.JSONDecodeError:
                    pass
                start = None

    return results if results else None


async def _analyze_batch(
    clauses: list[Clause],
    contract_type: str = "lease",
) -> tuple[str, list[dict]]:
    """조항 배치를 LLM으로 분석하고 (응답 텍스트, 참고문헌) 반환."""
    batch_text = "\n".join(c.content for c in clauses)
    references = retrieve_similar(batch_text, contract_type=contract_type)

    ref_text = format_references(references)
    if not ref_text:
        ref_text = get_no_reference_context(contract_type)

    clauses_text = ""
    for clause in clauses:
        clauses_text += f"\n[{clause.index}] {clause.title}: {clause.content}\n"

    prompt = get_analysis_prompt(contract_type)
    llm = get_llm()
    messages = prompt.format_messages(
        clauses_text=clauses_text,
        reference_context=ref_text,
    )

    response = await llm.ainvoke(messages)

    text = response.content
    if not text and hasattr(response, "text"):
        text = response.text
    if not text:
        text = str(response)

    return _strip_thinking(text), references


async def analyze_all_clauses(
    clauses: list[Clause],
    contract_type: str = "lease",
) -> dict:
    """전체 조항을 배치로 나눠 병렬 LLM 호출로 분석."""
    batches = [clauses[i:i + BATCH_SIZE] for i in range(0, len(clauses), BATCH_SIZE)]
    logger.info(f"LLM 분석 시작: {len(clauses)}개 조항, {len(batches)}개 배치 (유형: {contract_type})")

    tasks = [_analyze_batch(batch, contract_type) for batch in batches]
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    all_parsed = []
    all_references = []
    for i, resp in enumerate(responses):
        if isinstance(resp, Exception):
            logger.error(f"배치 {i} 실패: {resp}")
            continue
        text, refs = resp
        all_references.extend(refs)
        parsed = _extract_json_from_response(text)

        if not parsed:
            logger.warning(f"배치 {i} 파싱 실패. LLM 원문:\n{text[:500]}")
        else:
            logger.info(f"배치 {i}: {len(parsed)}개 조항 파싱 성공")

        all_parsed.extend(parsed)

    # 중복 참고문헌 제거
    seen_texts = set()
    unique_refs = []
    for ref in all_references:
        t = ref.get("text", "")[:100]
        if t not in seen_texts:
            seen_texts.add(t)
            unique_refs.append(ref)

    logger.info(f"총 {len(all_parsed)}/{len(clauses)}개 조항 파싱 완료")

    return {
        "parsed_list": all_parsed,
        "references": unique_refs,
    }
