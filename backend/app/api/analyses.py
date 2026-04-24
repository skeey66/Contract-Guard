import io
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.app.config import settings
from backend.app.models.analysis import AnalysisResponse, AnalysisResult, ClauseAnalysis
from backend.app.services.export_service import export_analysis, supported_formats

logger = logging.getLogger(__name__)
router = APIRouter()

# analysis_id는 UUID4로 발급되므로 엄격히 검증 — 경로 traversal 방지.
_ANALYSIS_ID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")


def _validate_analysis_id(analysis_id: str) -> None:
    if not _ANALYSIS_ID_RE.match(analysis_id):
        raise HTTPException(status_code=400, detail="유효하지 않은 분석 ID입니다.")


def _result_path(analysis_id: str) -> Path:
    return Path(settings.results_dir) / f"{analysis_id}.json"


def _load_result(analysis_id: str) -> AnalysisResult:
    """저장된 분석 결과를 모델로 복원."""
    _validate_analysis_id(analysis_id)
    result_file = _result_path(analysis_id)
    if not result_file.exists():
        raise HTTPException(status_code=404, detail="분석 결과를 찾을 수 없습니다.")
    with open(result_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return AnalysisResult(**data)


def _save_result(result: AnalysisResult) -> None:
    """수정된 분석 결과를 원자적으로 저장."""
    target = _result_path(result.id)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)
    tmp.replace(target)


class AnalysisSummary(BaseModel):
    """사이드바 이력 목록용 요약 모델.

    created_at은 JSON에 값이 없으면 파일 mtime으로 폴백한다.
    contract_type은 구버전 저장분에는 누락되어 있어 Optional.
    """
    id: str
    filename: str
    contract_type: str | None = None
    created_at: str  # 항상 값 보장 (본문 또는 mtime)
    total_clauses: int
    risky_clauses: int


@router.get("/analyses", response_model=list[AnalysisSummary])
async def list_analyses():
    """저장된 모든 분석 결과의 요약을 최신순으로 반환."""
    results_dir = Path(settings.results_dir)
    if not results_dir.exists():
        return []

    summaries: list[AnalysisSummary] = []
    for path in results_dir.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            created_at = data.get("created_at") or datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat(timespec="seconds")
            summaries.append(
                AnalysisSummary(
                    id=data.get("id", path.stem),
                    filename=data.get("filename", path.stem),
                    contract_type=data.get("contract_type"),
                    created_at=created_at,
                    total_clauses=int(data.get("total_clauses", 0) or 0),
                    risky_clauses=int(data.get("risky_clauses", 0) or 0),
                )
            )
        except Exception as e:
            # 단일 파일 파싱 실패가 전체 목록 조회를 중단시키지 않도록 건너뜀
            logger.warning(f"분석 이력 파싱 실패 ({path.name}): {e}")

    summaries.sort(key=lambda s: s.created_at, reverse=True)
    return summaries


@router.get("/analyses/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(analysis_id: str):
    result = _load_result(analysis_id)
    return AnalysisResponse(status="completed", result=result)


@router.delete("/analyses/{analysis_id}", status_code=204)
async def delete_analysis(analysis_id: str):
    """분석 결과 JSON 파일을 삭제."""
    _validate_analysis_id(analysis_id)
    target = _result_path(analysis_id)
    if not target.exists():
        raise HTTPException(status_code=404, detail="분석 결과를 찾을 수 없습니다.")
    try:
        target.unlink()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"삭제 실패: {e}")
    return None


class ClauseOverrideUpdate(BaseModel):
    text: str | None = None  # null이면 사용자 수정안 제거(원안/권고안으로 회귀)


@router.patch("/analyses/{analysis_id}/clauses/{clause_index}", response_model=ClauseAnalysis)
async def update_clause_override(
    analysis_id: str,
    clause_index: int,
    body: ClauseOverrideUpdate,
):
    """위험 조항에 대한 사용자 수정안을 저장하거나 제거.

    - body.text가 비어있지 않은 문자열이면 user_override로 저장
    - body.text가 null 또는 공백뿐이면 user_override를 제거(되돌리기)
    """
    result = _load_result(analysis_id)
    target = next(
        (c for c in result.clause_analyses if c.clause_index == clause_index),
        None,
    )
    if target is None:
        raise HTTPException(status_code=404, detail="해당 조항을 찾을 수 없습니다.")

    new_text = (body.text or "").strip()
    if new_text:
        target.user_override = new_text
        target.user_override_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    else:
        target.user_override = None
        target.user_override_at = None

    _save_result(result)
    return target


@router.get("/analyses/{analysis_id}/export")
async def export_contract(analysis_id: str, format: str = "docx"):
    """분석 결과로 수정안이 반영된 계약서를 다운로드.

    format: docx | pdf | hwpx
    """
    fmt = (format or "").lower().strip()
    if fmt not in supported_formats():
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 형식입니다: {format} (지원: {', '.join(supported_formats())})",
        )
    result = _load_result(analysis_id)
    try:
        data, mime, filename = export_analysis(result, fmt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"파일 생성 실패: {e}")

    # 한글 파일명을 위해 RFC 5987 인코딩 사용
    encoded_name = quote(filename)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
    }
    return StreamingResponse(io.BytesIO(data), media_type=mime, headers=headers)
