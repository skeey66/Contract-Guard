"""계약서 전체에 대한 LLM 기반 종합 평가 생성.

조항별 분석 결과를 입력받아 계약 전반의 균형성·주요 쟁점·당사자 영향에 대한
3~5문장 평가 단락을 생성한다. 위험 카운트(고/중/저)는 별도 한 줄로 덧붙인다.
"""

import asyncio
import logging
import re

from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate

from backend.app.models.analysis import ClauseAnalysis
from backend.app.models.risk import RiskLevel
from backend.app.services.llm_service import get_llm

logger = logging.getLogger(__name__)

_SUMMARY_TIMEOUT = 90
_SUMMARY_SEMAPHORE = asyncio.Semaphore(1)

# 계약 유형 라벨 — 프롬프트 가독성용 (없으면 contract_type 그대로 사용)
_CONTRACT_TYPE_LABELS = {
  "lease": "임대차계약",
  "sales": "매매계약",
  "employment": "근로계약",
}

_SUMMARY_SYSTEM = (
  "당신은 한국 계약법 전문가입니다. 사용자가 제시한 계약서의 조항별 분석 결과를 종합하여, "
  "계약 전반의 균형성·주요 쟁점·당사자에게 미치는 영향을 평가하는 한 단락의 한국어 요약을 작성합니다. "
  "특정 조항 번호의 단순 나열이 아니라, 계약 전체를 관통하는 패턴과 핵심 메시지를 전달해야 합니다."
)

_SUMMARY_TEMPLATE = (
  "## 계약 정보\n"
  "- 계약 유형: {contract_type_label}\n"
  "- 전체 조항 수: {total_clauses}\n"
  "- 위험 조항 수: 고위험 {high_count} / 중위험 {medium_count} / 저위험 {low_count}\n\n"
  "## 위험 조항 요약 (상위 {top_n}건)\n"
  "{risky_summary}\n\n"
  "## 안전 조항 개요\n"
  "{safe_overview}\n\n"
  "## 작성 지침\n"
  "다음 **세 개의 짧은 단락**을 정확한 라벨과 함께 출력한다. 각 단락은 2~3문장으로 작성하며, "
  "단락 사이에는 빈 줄을 둔다. 라벨은 `■ 라벨명` 형식으로 단락 첫 줄에 단독 배치한다.\n\n"
  "■ 전반 평가\n"
  "(계약 전체의 균형성·일반적 인상을 한국어 평어체로 2~3문장)\n\n"
  "■ 핵심 쟁점\n"
  "(가장 주의가 필요한 위험 패턴과 그 영향을 2~3문장)\n\n"
  "■ 권고 사항\n"
  "(체결 전 조정·검토가 필요한 실무적 권고 2~3문장)\n\n"
  "**규칙:**\n"
  "1. 조항 번호의 단순 나열은 피하고 위험 패턴을 일반화하여 설명한다.\n"
  "2. 분석 자료에 명시되지 않은 사실은 추측하지 않는다.\n"
  "3. 머리말·꼬리말·코드블록·이모지 없이 위 형식 그대로 출력한다.\n\n"
  "## 출력"
)


def _build_summary_prompt() -> ChatPromptTemplate:
  return ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(_SUMMARY_SYSTEM),
    HumanMessagePromptTemplate.from_template(_SUMMARY_TEMPLATE),
  ])


def _strip_thinking(text: str) -> str:
  text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
  text = re.sub(r"</?think>", "", text).strip()
  return text


def _clean_summary_text(raw: str) -> str:
  text = _strip_thinking(raw)
  code_block = re.search(r"```(?:\w+)?\s*(.*?)```", text, re.DOTALL)
  if code_block:
    text = code_block.group(1).strip()
  text = re.sub(r"^(##\s*)?(종합\s*평가|종합\s*요약|평가|출력)\s*[:：]?\s*\n?", "", text)
  # 단락 라벨이 굵게 강조된 경우(`**■ 전반 평가**`)는 굵기 마커 제거
  text = re.sub(r"\*\*\s*(■\s*[^\n*]+?)\s*\*\*", r"\1", text)
  # 3개 이상 연속 빈 줄을 2줄로 정규화
  text = re.sub(r"\n{3,}", "\n\n", text)
  return text.strip()


def _summarize_risky_clauses(risky: list[ClauseAnalysis], top_n: int = 8) -> str:
  """위험 조항을 LLM에 전달할 텍스트로 정리. 고→중→저 순으로 상위 N건."""
  order = {RiskLevel.HIGH: 0, RiskLevel.MEDIUM: 1, RiskLevel.LOW: 2}
  sorted_risky = sorted(
    risky,
    key=lambda c: (order.get(c.risk_level, 3), -c.confidence),
  )[:top_n]

  if not sorted_risky:
    return "(위험 조항 없음)"

  lines: list[str] = []
  level_label = {
    RiskLevel.HIGH: "고위험",
    RiskLevel.MEDIUM: "중위험",
    RiskLevel.LOW: "저위험",
  }
  for c in sorted_risky:
    label = level_label.get(c.risk_level, "위험")
    title = c.clause_title or f"제{c.clause_index}조"
    lines.append(f"- [{label}] {title}")
    if c.explanation:
      lines.append(f"  · 분석: {c.explanation[:200]}")
    risk_types = [r.risk_type for r in c.risks if r.risk_type]
    if risk_types:
      lines.append(f"  · 위험유형: {', '.join(risk_types[:4])}")
  return "\n".join(lines)


def _safe_overview(safe_clauses: list[ClauseAnalysis], max_titles: int = 5) -> str:
  if not safe_clauses:
    return "(안전 조항 없음)"
  titles = [c.clause_title or f"제{c.clause_index}조" for c in safe_clauses[:max_titles]]
  remainder = len(safe_clauses) - len(titles)
  base = ", ".join(titles)
  if remainder > 0:
    return f"{len(safe_clauses)}개 조항이 안전으로 분석됨 (예: {base} 외 {remainder}건)"
  return f"{len(safe_clauses)}개 조항이 안전으로 분석됨 ({base})"


def _fallback_summary(all_analyses: list[ClauseAnalysis], risky: list[ClauseAnalysis]) -> str:
  total = len(all_analyses)
  risky_count = len(risky)

  if risky_count == 0:
    return f"총 {total}개 조항을 분석한 결과, 특별히 불리한 조항이 발견되지 않았습니다."

  high = sum(1 for a in risky if a.risk_level == RiskLevel.HIGH)
  medium = sum(1 for a in risky if a.risk_level == RiskLevel.MEDIUM)
  low = sum(1 for a in risky if a.risk_level == RiskLevel.LOW)

  parts = []
  if high:
    parts.append(f"고위험 {high}개")
  if medium:
    parts.append(f"중위험 {medium}개")
  if low:
    parts.append(f"저위험 {low}개")

  return (
    f"총 {total}개 조항 중 {risky_count}개 조항에서 위험 요소가 발견되었습니다 "
    f"({', '.join(parts)}). 세부 내용을 확인하고 계약 전 수정을 요청하세요."
  )


async def _invoke_summary(messages) -> str:
  llm = get_llm()
  response = await llm.ainvoke(messages)
  text = response.content if hasattr(response, "content") else str(response)
  return _clean_summary_text(text or "")


async def generate_overall_summary(
  clause_analyses: list[ClauseAnalysis],
  contract_type: str = "lease",
) -> str:
  """계약서 전체에 대한 LLM 기반 종합 평가 단락을 반환.

  실패 시 카운트 기반 폴백 요약을 반환한다.
  """
  risky = [c for c in clause_analyses if c.risk_level != RiskLevel.SAFE]
  safe = [c for c in clause_analyses if c.risk_level == RiskLevel.SAFE]

  high_count = sum(1 for c in risky if c.risk_level == RiskLevel.HIGH)
  medium_count = sum(1 for c in risky if c.risk_level == RiskLevel.MEDIUM)
  low_count = sum(1 for c in risky if c.risk_level == RiskLevel.LOW)

  contract_type_label = _CONTRACT_TYPE_LABELS.get(contract_type, contract_type)

  prompt = _build_summary_prompt()
  messages = prompt.format_messages(
    contract_type_label=contract_type_label,
    total_clauses=len(clause_analyses),
    high_count=high_count,
    medium_count=medium_count,
    low_count=low_count,
    top_n=min(8, len(risky)) if risky else 0,
    risky_summary=_summarize_risky_clauses(risky),
    safe_overview=_safe_overview(safe),
  )

  try:
    async with _SUMMARY_SEMAPHORE:
      narrative = await asyncio.wait_for(_invoke_summary(messages), timeout=_SUMMARY_TIMEOUT)
  except asyncio.TimeoutError:
    logger.warning(f"종합 요약 생성 타임아웃 ({_SUMMARY_TIMEOUT}초) — 폴백 사용")
    return _fallback_summary(clause_analyses, risky)
  except Exception as e:
    logger.error(f"종합 요약 생성 오류 — 폴백 사용: {e}")
    return _fallback_summary(clause_analyses, risky)

  if not narrative:
    logger.warning("종합 요약 빈 응답 — 폴백 사용")
    return _fallback_summary(clause_analyses, risky)

  # 카운트 한 줄을 단락 끝에 부가 — LLM이 카운트를 누락해도 사용자가 항상 볼 수 있도록.
  # 프론트는 `■ 분석 통계` 라벨로 별도 단락처럼 렌더링.
  count_line = (
    f"■ 분석 통계\n"
    f"전체 {len(clause_analyses)}개 조항 중 고위험 {high_count}개, "
    f"중위험 {medium_count}개, 저위험 {low_count}개로 분석되었습니다."
  )
  return f"{narrative}\n\n{count_line}"
