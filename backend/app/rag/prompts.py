from langchain_core.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from backend.app.contract_types import get_contract_config


def get_analysis_prompt(contract_type: str = "lease") -> ChatPromptTemplate:
    """계약 유형에 맞는 분석 프롬프트를 반환."""
    config = get_contract_config(contract_type)
    return ChatPromptTemplate.from_messages([
        SystemMessagePromptTemplate.from_template(config["system_prompt"]),
        HumanMessagePromptTemplate.from_template(config["analysis_template"]),
    ])


def get_no_reference_context(contract_type: str = "lease") -> str:
    """계약 유형에 맞는 참고문헌 없을 때 기본 텍스트."""
    config = get_contract_config(contract_type)
    return config["no_reference_context"]


_REFERENCE_LABEL_GUIDE = (
    "## 참고 자료 라벨 안내 (반드시 숙지 — 우선순위 순)\n"
    "1. [법률] / [시행령] / [시행규칙]: 법률 본문 — **가장 강한 근거**. 조문 번호·수치 인용 시 이 라벨의 내용만 사용\n"
    "2. [표준-안전]: 을(약자측: 임차인/근로자/매수인)에게 **유리하거나 표준적인** 약관 사례 — 본 계약 조항이 이와 유사하면 **안전 신호**\n"
    "3. [판결문] / [판례]: 법원 판결 사례 — 법률·표준약관만으로 판단이 어려운 회색지대 해석 참고\n"
    "4. [약관-불공정]: 을(약자측)에게 **불리한** 약관 사례 — 본 계약 조항이 이와 유사하면 **위험 신호** (안전 신호 아님!)\n"
    "\n"
    "판단 우선순위: 법률 → 표준-안전 → 판결문 → 약관-불공정. 1·2번 라벨로 결론이 명확하면 그것을 따르고, 애매한 경우에만 판결문을 참고하세요.\n"
)


def format_references(references: list[dict]) -> str:
    """참고 법률/판례를 프롬프트용 텍스트로 변환.

    라벨 의미를 prepend하여 LLM이 [약관-불공정]을 정반대로 해석하지 않도록 하고,
    법률·표준약관·판례·불공정약관 우선순위를 명시한다.
    """
    if not references:
        return ""
    ref_lines = []
    for i, ref in enumerate(references[:5], 1):
        text = ref.get("text", "")[:300]
        ref_lines.append(f"[참고{i}] {text}")
    return _REFERENCE_LABEL_GUIDE + "\n" + "\n".join(ref_lines)


def format_parties(parties: dict[str, str] | None) -> str:
    """감지된 갑/을 역할을 프롬프트에 주입할 텍스트로 변환."""
    if not parties:
        return ""
    gap = parties.get("갑", "?")
    eul = parties.get("을", "?")
    return (
        "## 당사자 역할 정의 (반드시 준수)\n"
        f"이 계약서에서 '갑'은 {gap}이고, '을'은 {eul}입니다.\n"
        "조항 본문에 '갑', '을' 이 등장하면 위 정의를 그대로 적용하여 해석하세요. "
        "갑/을의 역할을 바꿔 해석하거나 혼동하지 마세요."
    )
