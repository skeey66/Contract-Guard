import re
from backend.app.models.clause import Clause

_CONTRACT_TYPE_KEYWORDS = {
    "lease": ["임대차", "임대인", "임차인", "보증금", "차임", "월세", "전세", "임대"],
    "sales": ["매매", "매도인", "매수인", "매매대금", "소유권이전", "잔금"],
    "employment": ["근로", "근로자", "사용자", "임금", "급여", "퇴직", "근무시간", "고용"],
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
}

# 계약 유형별 후보 역할명 (갑/을 주변에 출현할 수 있는 한국어 단어)
_ROLE_CANDIDATES = {
    "lease": ["임대인", "임차인"],
    "sales": ["매도인", "매수인"],
    "employment": ["사용자", "근로자", "고용주", "사업주"],
}

_ROLE_NORMALIZE = {
    "고용주": "사용자",
    "사업주": "사용자",
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
    """계약서 텍스트를 조항 단위로 분리한다."""
    # 조항 헤더만 매칭: "제N조" 또는 "제N조 (제목)"
    header_pattern = r"(제\s*\d+\s*조(?:의\s*\d+)?(?:\s*\([^)]*\))?)"
    parts = re.split(header_pattern, text)

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
        clauses = _fallback_split(text)

    return clauses


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
