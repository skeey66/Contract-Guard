import re
from backend.app.models.clause import Clause


def split_clauses(text: str) -> list[Clause]:
    """계약서 텍스트를 조항 단위로 분리한다."""
    pattern = r"(제\s*\d+\s*조(?:의\s*\d+)?[^\n]*)"
    parts = re.split(pattern, text)

    clauses: list[Clause] = []

    i = 1
    while i < len(parts):
        title_match = re.match(r"(제\s*(\d+)\s*조(?:의\s*\d+)?)\s*(.*)", parts[i].strip())
        if title_match:
            title = parts[i].strip()
            content = parts[i + 1].strip() if i + 1 < len(parts) else ""
            # 조항 번호를 인덱스로 사용 (제9조 → index 9)
            clause_num = int(title_match.group(2))
            # 한 줄짜리 조항은 title 자체가 content
            full_content = f"{title}\n{content}" if content else title
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
