"""위험 조항에 대한 권고 수정안 생성 서비스.

표준약관·법률 본문 KB를 근거로 LLM이 균형잡힌 톤의 수정안을 1건 작성한다.
1단계: 위험도 high/medium 조항만 대상으로 단일 수정안을 반환한다.
"""

import asyncio
import logging
import re

from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate

from backend.app.models.clause import Clause
from backend.app.models.risk import RiskDetail, RiskLevel
from backend.app.services.llm_service import get_llm
from backend.app.rag.prompts import format_references

logger = logging.getLogger(__name__)

# 동시 요청 제한 (분석 호출과 별개의 세마포어)
_REWRITE_SEMAPHORE = asyncio.Semaphore(3)
_REWRITE_TIMEOUT = 90

_REWRITE_SYSTEM = (
    "당신은 한국 계약법 전문가입니다. 사용자가 제시한 '위험 조항'을 "
    "표준약관과 관련 법률에 부합하도록 다시 작성하는 일을 합니다. "
    "수정안은 갑/을 어느 한쪽에 일방적으로 유리하지 않은 균형잡힌 표현을 사용하고, "
    "원문 조항의 본래 목적은 유지하되 위험 요소만 제거하거나 완화합니다."
)

_REWRITE_TEMPLATE = (
    "## 원문 조항\n"
    "[{clause_index}] {clause_title}\n"
    "{clause_content}\n\n"
    "## 식별된 위험\n"
    "{risk_summary}\n\n"
    "## 분석 근거 자료 (표준약관·법률 본문)\n"
    "{reference_context}\n\n"
    "## 작성 지침\n"
    "1. 원문 조항의 번호·제목 형식([{clause_index}] {clause_title})을 그대로 유지한다.\n"
    "2. 수정안은 한국어 계약서 문체로 작성한다 (단정형, 존대 없음).\n"
    "3. 위험 요소를 제거하되 양 당사자의 정당한 이익은 보존한다.\n"
    "4. 표준약관·법률에 명시된 한도(예: 차임 증액 5%)를 인용할 수 있다.\n"
    "5. 추가 설명·머리말·꼬리말 없이 **수정된 조항 본문만** 출력한다.\n\n"
    "## 수정 조항"
)


def _build_rewrite_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(_REWRITE_SYSTEM),
        HumanMessagePromptTemplate.from_template(_REWRITE_TEMPLATE),
    ])


def _summarize_risks(risks: list[RiskDetail], explanation: str) -> str:
    """RiskDetail 목록을 LLM에 전달할 텍스트로 정리."""
    lines: list[str] = []
    if explanation:
        lines.append(f"- 종합 평가: {explanation}")
    for r in risks:
        risk_type = r.risk_type or "unknown"
        desc = r.description or ""
        suggestion = r.suggestion or ""
        lines.append(f"- 위험유형: {risk_type}")
        if desc:
            lines.append(f"  설명: {desc}")
        if suggestion:
            lines.append(f"  권고: {suggestion}")
    if not lines:
        lines.append("- (구체적 위험 설명 없음 — 일반적인 균형 조정 수정안 작성)")
    return "\n".join(lines)


def _strip_thinking(text: str) -> str:
    """LLM 응답에서 <think> 태그를 제거."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    text = re.sub(r"</?think>", "", text).strip()
    return text


def _clean_rewrite_text(raw: str) -> str:
    """수정안 본문에서 코드블록·머리말 잔재를 제거."""
    text = _strip_thinking(raw)
    # 코드블록 제거
    code_block = re.search(r"```(?:\w+)?\s*(.*?)```", text, re.DOTALL)
    if code_block:
        text = code_block.group(1).strip()
    # 흔한 머리말 패턴 제거
    text = re.sub(r"^(수정\s*조항|수정안|수정된\s*조항)\s*[:：]?\s*", "", text)
    return text.strip()


async def _invoke_rewrite(messages) -> str:
    llm = get_llm()
    response = await llm.ainvoke(messages)
    text = response.content if hasattr(response, "content") else str(response)
    return _clean_rewrite_text(text or "")


async def rewrite_clause(
    clause: Clause,
    risks: list[RiskDetail],
    explanation: str,
    references: list[dict],
) -> str | None:
    """단일 조항의 수정안을 생성.

    실패(타임아웃·빈 응답) 시 None을 반환한다.
    """
    ref_text = format_references(references) or "(참고 자료 없음 — 일반 법리에 따라 작성)"
    risk_summary = _summarize_risks(risks, explanation)

    prompt = _build_rewrite_prompt()
    messages = prompt.format_messages(
        clause_index=clause.index,
        clause_title=clause.title,
        clause_content=clause.content,
        risk_summary=risk_summary,
        reference_context=ref_text,
    )

    try:
        async with _REWRITE_SEMAPHORE:
            text = await asyncio.wait_for(_invoke_rewrite(messages), timeout=_REWRITE_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning(f"조항 {clause.index} 수정안 생성 타임아웃 ({_REWRITE_TIMEOUT}초)")
        return None
    except Exception as e:
        logger.error(f"조항 {clause.index} 수정안 생성 오류: {e}")
        return None

    if not text:
        logger.warning(f"조항 {clause.index} 수정안 빈 응답")
        return None
    return text


async def rewrite_risky_clauses(
    clauses: list[Clause],
    parsed_results: list[dict],
    per_clause_refs: dict[int, list[dict]],
) -> dict[int, str]:
    """위험도 high/medium 조항에 대해 수정안을 일괄 생성.

    반환값: {clause_index: rewritten_text}
    """
    target_levels = {"high", "medium"}
    targets: list[tuple[Clause, dict]] = []
    parsed_by_index = {p.get("clause_index"): p for p in parsed_results if p.get("clause_index") is not None}

    for clause in clauses:
        parsed = parsed_by_index.get(clause.index)
        if not parsed:
            continue
        level = (parsed.get("risk_level") or "").lower().strip()
        if level not in target_levels:
            continue
        targets.append((clause, parsed))

    if not targets:
        logger.info("수정안 생성 대상 조항 없음")
        return {}

    logger.info(f"수정안 생성 시작: {len(targets)}개 조항")

    async def _one(clause: Clause, parsed: dict) -> tuple[int, str | None]:
        raw_risks = parsed.get("risks", []) or []
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
        refs = per_clause_refs.get(clause.index, [])
        rewritten = await rewrite_clause(clause, risks, explanation, refs)
        return clause.index, rewritten

    results = await asyncio.gather(*(_one(c, p) for c, p in targets), return_exceptions=True)

    out: dict[int, str] = {}
    for r in results:
        if isinstance(r, Exception):
            logger.error(f"수정안 생성 실패: {r}")
            continue
        idx, text = r
        if text:
            out[idx] = text
    logger.info(f"수정안 생성 완료: {len(out)}/{len(targets)}개 성공")
    return out


def is_rewrite_target(risk_level: RiskLevel | str) -> bool:
    """주어진 위험도가 수정안 생성 대상인지 판정."""
    if isinstance(risk_level, RiskLevel):
        return risk_level in (RiskLevel.HIGH, RiskLevel.MEDIUM)
    return str(risk_level).lower().strip() in {"high", "medium"}
