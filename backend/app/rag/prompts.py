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
    "## 참고 자료 라벨 안내 (반드시 숙지)\n"
    "1. [법률] / [시행령] / [시행규칙]: 법률 본문 — 조문 번호·수치 인용 시 이 라벨의 내용만 사용\n"
    "2. [표준-안전]: 을(약자측: 임차인/근로자/매수인)에게 **유리하거나 표준적인** 약관 사례 — 본 계약 조항이 이와 유사하면 **안전 신호**\n"
    "3. [판결문] / [판례]: 법원 판결 사례 — 회색지대 해석 참고\n"
    "4. [약관-불공정]: 을(약자측)에게 **불리한** 약관 사례 — 본 계약 조항이 이와 유사하면 **위험 신호** (안전 신호 아님!)\n"
    "\n"
    "## 판단 원칙 — 표면 키워드가 아니라 **문맥 일치도**로 결정하세요\n"
    "- 같은 키워드(예: '통지', '송달', '해지')라도 누가 누구에게 어떤 효과를 주는 조항인지가 다르면 다른 케이스입니다.\n"
    "- [법률]은 절차적·일반적 규정인 경우가 많아 표면 키워드만 같고 본 조항의 맥락과 다를 수 있습니다. 법률이 본 조항과 동일한 상황을 직접 규율하는지 반드시 확인하세요.\n"
    "- **[약관-불공정]에 본 조항과 패턴이 명확히 일치하는 사례가 있으면 그것이 가장 강한 위험 신호입니다.** 법률 라벨이 다수더라도 그것들이 본 조항의 맥락과 다르면 [약관-불공정]을 우선하세요.\n"
    "- [약관-불공정] 라벨에 포함된 '판단근거' 문구는 해당 조항이 왜 불공정한지를 설명한 것이므로 인용해서 위험 신호로 사용하세요.\n"
)


def format_references(references: list[dict]) -> str:
    """참고 법률/판례를 프롬프트용 텍스트로 변환.

    라벨 의미를 prepend하여 LLM이 [약관-불공정]을 정반대로 해석하지 않도록 하고,
    법률·표준약관·판례·불공정약관 우선순위를 명시한다.
    """
    if not references:
        return ""
    ref_lines = []
    # top 8: stratified quota(law 2 + safe 1 + judgment 1 + unfair 1)가 보존되도록 충분히 확보.
    # top 5만 사용하면 LAW_BOOST로 법률이 4~5개 슬롯을 차지해 unfair_clause 매칭이 잘려나가
    # 발송간주·도달의제 같은 정답 패턴이 LLM에 전달되지 않는 문제가 있었음.
    for i, ref in enumerate(references[:8], 1):
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
