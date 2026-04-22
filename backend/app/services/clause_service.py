import re
from backend.app.models.clause import Clause

_CONTRACT_TYPE_KEYWORDS = {
    "lease": ["임대차", "임대인", "임차인", "보증금", "차임", "월세", "전세", "임대"],
    "sales": ["매매", "매도인", "매수인", "매매대금", "소유권이전", "잔금"],
    "employment": ["근로", "근로자", "사용자", "임금", "급여", "퇴직", "근무시간", "고용"],
    # 도급/용역: '발주자/수급인' 어휘 + '도급/용역/검수/납품' 행위 어휘
    "service": ["도급", "수급인", "발주자", "발주", "용역", "검수", "납품", "산출물", "하도급", "하도급대금"],
    # 금전소비대차: '대여/차용/이자/원리금' 어휘
    "loan": ["소비대차", "차용", "차용금", "대여", "대여금", "원금", "이자", "원리금", "변제", "차주", "대주", "기한이익"],
}


def detect_contract_type(text: str) -> str:
    """계약서 텍스트에서 계약 유형을 자동 감지한다."""
    scores = {}
    for ctype, keywords in _CONTRACT_TYPE_KEYWORDS.items():
        scores[ctype] = sum(text.count(kw) for kw in keywords)
    return max(scores, key=scores.get)


# 계약 유형별 표준 갑/을 매핑 (대다수 한국 계약서의 관례)
_DEFAULT_PARTIES = {
    "lease": {"갑": "임대인", "을": "임차인"},
    "sales": {"갑": "매도인", "을": "매수인"},
    "employment": {"갑": "사용자", "을": "근로자"},
    "service": {"갑": "발주자", "을": "수급인"},
    "loan": {"갑": "대주", "을": "차주"},
}

# 계약 유형별 후보 역할명 (갑/을 주변에 출현할 수 있는 한국어 단어)
_ROLE_CANDIDATES = {
    "lease": ["임대인", "임차인"],
    "sales": ["매도인", "매수인"],
    "employment": ["사용자", "근로자", "고용주", "사업주"],
    "service": ["발주자", "수급인", "도급인", "원사업자", "수급사업자"],
    "loan": ["대주", "차주", "채권자", "채무자", "대여인", "차용인"],
}

_ROLE_NORMALIZE = {
    "고용주": "사용자",
    "사업주": "사용자",
    # service: 하도급법 용어와 민법 용어를 표준 갑/을로 정규화
    "도급인": "발주자",
    "원사업자": "발주자",
    "수급사업자": "수급인",
    # loan: 채권/채무 용어 → 대주/차주로 정규화
    "채권자": "대주",
    "대여인": "대주",
    "채무자": "차주",
    "차용인": "차주",
}


def detect_parties(text: str, contract_type: str) -> dict[str, str]:
    """계약서 헤더/말미에서 '임대인(갑)' 같은 패턴을 찾아 갑/을 역할을 추출.

    감지 실패 시 해당 계약 유형의 표준 관례를 반환한다.
    """
    result = dict(_DEFAULT_PARTIES.get(contract_type, {"갑": "갑", "을": "을"}))
    candidates = _ROLE_CANDIDATES.get(contract_type, [])
    if not candidates:
        return result

    # "{역할}(갑)" 또는 "갑({역할})" 양쪽 형태를 모두 매칭
    role_group = "|".join(candidates)
    for sym in ("갑", "을"):
        pattern1 = rf"({role_group})\s*\(\s*{sym}\s*\)"
        pattern2 = rf"{sym}\s*\(\s*({role_group})\s*\)"
        m = re.search(pattern1, text) or re.search(pattern2, text)
        if m:
            raw = m.group(1)
            result[sym] = _ROLE_NORMALIZE.get(raw, raw)
    return result


def split_clauses(text: str) -> list[Clause]:
    """계약서 텍스트를 조항 단위로 분리한다.

    1) 본문에서 특약사항 섹션을 분리 (제N조가 흡수하지 못하도록 선분리)
    2) 본문은 `제N조` 패턴으로 분리, 매칭 0건이면 단락 폴백
    3) 특약사항은 항목 단위(1./①/가. 등)로 쪼개 별도 조항으로 추가
    """
    main_text, special_items = _extract_special_terms(text)

    # 조항 헤더만 매칭: "제N조" 또는 "제N조 (제목)"
    header_pattern = r"(제\s*\d+\s*조(?:의\s*\d+)?(?:\s*\([^)]*\))?)"
    parts = re.split(header_pattern, main_text)

    clauses: list[Clause] = []

    i = 1
    while i < len(parts):
        header_match = re.match(r"제\s*(\d+)\s*조", parts[i].strip())
        if header_match:
            title = parts[i].strip()
            body = parts[i + 1].strip() if i + 1 < len(parts) else ""
            clause_num = int(header_match.group(1))
            full_content = f"{title}\n{body}" if body else title
            clauses.append(Clause(index=clause_num, title=title, content=full_content))
            i += 2
        else:
            i += 1

    if not clauses:
        clauses = _fallback_split(main_text)

    # 특약사항 항목 추가 — 본문 마지막 조항 번호 다음부터 인덱스 부여
    if special_items:
        next_index = (max(c.index for c in clauses) + 1) if clauses else 1
        for offset, item_text in enumerate(special_items):
            title = f"특약사항 {offset + 1}"
            full_content = f"{title}\n{item_text}"
            clauses.append(Clause(index=next_index + offset, title=title, content=full_content))

    return clauses


# 특약사항 헤더 — `특약사항`, `특약`, `특별약정`, `추가특약` 등을 줄 단위로 매칭.
# 다른 본문 단어("특약은", "특약이") 오탐을 피하려고 줄 단위 + 콜론/공백/구두점 경계.
_SPECIAL_TERMS_HEADER = re.compile(
    r"(?m)^\s*[\[\(<【※■◆●▶▷□■]?\s*"
    r"(특약\s*사항|특별\s*약정|추가\s*특약|기타\s*특약|특약)"
    r"\s*[\]\)>】]?\s*[:：]?\s*$"
)

# 특약사항 끝을 알리는 패턴 — 서명/날짜 블록이 시작되거나 별표/도장 영역
_SPECIAL_TERMS_END = re.compile(
    r"(?m)^\s*("
    r"임\s*대\s*인|임\s*차\s*인|매\s*도\s*인|매\s*수\s*인|"
    r"사\s*용\s*자|근\s*로\s*자|발\s*주\s*자|수\s*급\s*인|대\s*주|차\s*주|"
    r"\d{4}\s*년\s*\d{1,2}\s*월|"
    r"계\s*약\s*일|체\s*결\s*일|작\s*성\s*일"
    r")"
)


def _extract_special_terms(text: str) -> tuple[str, list[str]]:
    """텍스트에서 특약사항 섹션을 추출.

    반환: (특약사항이 제거된 본문, 특약 항목 리스트)
    특약사항이 없으면 (원본, []).
    """
    header_match = _SPECIAL_TERMS_HEADER.search(text)
    if not header_match:
        return text, []

    section_start = header_match.end()
    # 특약사항 섹션의 끝 찾기 — 서명블록 시작 또는 텍스트 끝
    end_match = _SPECIAL_TERMS_END.search(text, section_start)
    section_end = end_match.start() if end_match else len(text)

    section_body = text[section_start:section_end].strip()
    if not section_body:
        return text, []

    items = _split_special_items(section_body)
    if not items:
        return text, []

    main_text = text[:header_match.start()] + text[section_end:]
    return main_text, items


# 특약 항목 시작 패턴 — `1.`, `1)`, `①`, `가.`, `- ` 등을 줄 시작에서 매칭
_SPECIAL_ITEM_HEADER = re.compile(
    r"(?m)^\s*(?:"
    r"\d{1,2}\s*[\.\)]"           # 1. 1) 10.
    r"|[①-⑳]"                    # 환원숫자 ①-⑳
    r"|[㈀-㈎]"                   # 한글자모 환원
    r"|[가-힣]\s*[\.\)]"          # 가. 나. 다.
    r"|[-•*]\s+"                  # 글머리표 - • *
    r")\s*"
)


def _split_special_items(section: str) -> list[str]:
    """특약사항 본문을 항목 단위로 분리.

    항목 헤더가 없으면 단락 분리 폴백, 그것도 실패하면 전체를 1개 항목으로 반환.
    """
    matches = list(_SPECIAL_ITEM_HEADER.finditer(section))
    if matches:
        items: list[str] = []
        for idx, m in enumerate(matches):
            start = m.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(section)
            chunk = section[start:end].strip()
            if len(chunk) >= 5:
                items.append(chunk)
        if items:
            return items

    # 항목 헤더 없음 — 빈 줄 단락으로 분리
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", section) if p.strip()]
    if len(paragraphs) > 1:
        return [p for p in paragraphs if len(p) >= 5]

    # 단일 단락 — 통째로 1개 항목
    return [section] if len(section) >= 5 else []


def _fallback_split(text: str) -> list[Clause]:
    """조항 패턴이 없을 때 빈 줄 기준으로 분리."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    clauses = []
    for i, para in enumerate(paragraphs):
        if len(para) < 20:
            continue
        lines = para.split("\n")
        title = lines[0][:50] if lines else f"단락 {i + 1}"
        clauses.append(Clause(index=i + 1, title=title, content=para))
    return clauses
