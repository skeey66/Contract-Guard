"""legalize-kr GitHub 저장소에서 Contract-Guard가 다루는 계약 유형 관련 법률 본문을
backend/data/raw/laws/ 디렉토리로 내려받는다.

사용법:
    python -m backend.scripts.download_laws            # 신규 파일만 받음
    python -m backend.scripts.download_laws --force    # 기존 파일도 덮어씀

다운로드 후 build_kb.py가 이 디렉토리를 읽어 ChromaDB에 인덱싱한다.
"""

import argparse
import urllib.parse
import urllib.request
from pathlib import Path

from backend.app.config import DATA_DIR


# 계약 유형 매핑 (build_kb.py와 공유)
LAW_TO_CONTRACT_TYPES: dict[str, list[str]] = {
    # 임대차
    "주택임대차보호법": ["lease"],
    "상가건물임대차보호법": ["lease"],
    # 민법: 임대차편(618-654) / 매매편(563-595) / 도급편(664-674) / 소비대차편(598-608)
    "민법": ["lease", "sales", "service", "loan"],
    # 매매·중개
    "공인중개사법": ["sales"],
    "부동산거래신고등에관한법률": ["sales"],
    # 근로 (기존 + 강화)
    "근로기준법": ["employment"],
    "최저임금법": ["employment"],
    "기간제및단시간근로자보호등에관한법률": ["employment"],
    "남녀고용평등과일ㆍ가정양립지원에관한법률": ["employment"],
    "노동조합및노동관계조정법": ["employment"],
    "근로자퇴직급여보장법": ["employment"],
    "산업안전보건법": ["employment"],
    "직업안정법": ["employment"],
    "파견근로자보호등에관한법률": ["employment"],
    # 용역/도급 (service)
    "하도급거래공정화에관한법률": ["service"],
    "건설산업기본법": ["service"],
    # 금전소비대차 (loan)
    "이자제한법": ["loan"],
    "대부업등의등록및금융이용자보호에관한법률": ["loan"],
    "보증인보호를위한특별법": ["loan"],
    # 약관규제법: 모든 계약에 공통 적용 (불공정 약관 무효 판단의 일반 근거)
    "약관의규제에관한법률": ["lease", "sales", "employment", "service", "loan"],
    # 민사집행법: 보증금 회수·강제집행 관련 (임대차에서 가장 빈번)
    "민사집행법": ["lease"],
}

# 법률별로 다운로드할 파일 목록.
# 본법(법률.md) 외에 구체 수치(예: 5% 증액 한도)가 시행령에 위임되어 있는 경우가 많으므로
# 시행령도 함께 받아 grounding 정확도를 높인다.
DEFAULT_FILES: list[str] = ["법률.md", "시행령.md"]
LAW_TO_FILES: dict[str, list[str]] = {
    # 근로기준법은 시행규칙까지 함께 (휴게·연장근로 산정 등 세칙)
    "근로기준법": ["법률.md", "시행령.md", "시행규칙.md"],
}

GITHUB_RAW_BASE = "https://raw.githubusercontent.com/legalize-kr/legalize-kr/main/kr"


def _files_for(law_name: str) -> list[str]:
    return LAW_TO_FILES.get(law_name, DEFAULT_FILES)


def _build_url(law_name: str, filename: str) -> str:
    return f"{GITHUB_RAW_BASE}/{urllib.parse.quote(law_name)}/{urllib.parse.quote(filename)}"


def _download_file(url: str, dest: Path, timeout: int = 30) -> int:
    """파일을 다운로드하여 dest에 저장. 다운로드한 바이트 수 반환."""
    req = urllib.request.Request(url, headers={"User-Agent": "Contract-Guard-KB-Builder"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return len(data)


def download_all(force: bool = False) -> None:
    laws_dir = Path(DATA_DIR) / "raw" / "laws"
    print(f"[다운로드 위치] {laws_dir}")

    success, skipped, failed = 0, 0, 0
    for law_name, contract_types in LAW_TO_CONTRACT_TYPES.items():
        ct_label = ",".join(contract_types)
        for filename in _files_for(law_name):
            dest = laws_dir / law_name / filename
            if dest.exists() and not force:
                print(f"  [SKIP] {law_name}/{filename} (이미 존재, --force로 덮어쓰기)")
                skipped += 1
                continue

            url = _build_url(law_name, filename)
            try:
                size = _download_file(url, dest)
                print(f"  [OK]   {law_name}/{filename} ({size:,} bytes, contract_type={ct_label})")
                success += 1
            except Exception as e:
                # 일부 법률은 시행규칙이 없을 수 있음 (404). 경고만 출력하고 계속.
                print(f"  [FAIL] {law_name}/{filename}: {e}")
                failed += 1

    print(f"\n완료: 성공 {success}, 스킵 {skipped}, 실패 {failed}")
    if success or skipped:
        print(f"빌드: python -m backend.scripts.build_kb --include-laws --clear")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="legalize-kr에서 계약 관련 법률 본문 다운로드")
    parser.add_argument("--force", action="store_true", help="기존 파일도 덮어쓰기")
    args = parser.parse_args()
    download_all(force=args.force)
