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


def format_references(references: list[dict]) -> str:
    """참고 법률/판례를 프롬프트용 텍스트로 변환."""
    if not references:
        return ""
    ref_lines = []
    for i, ref in enumerate(references, 1):
        text = ref.get("text", "")[:300]
        ref_lines.append(f"[참고{i}] {text}")
    return "\n".join(ref_lines[:5])


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
