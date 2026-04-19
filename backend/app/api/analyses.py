import io
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.app.config import settings
from backend.app.models.analysis import AnalysisResponse, AnalysisResult, ClauseAnalysis
from backend.app.services.export_service import export_analysis, supported_formats

router = APIRouter()


def _result_path(analysis_id: str) -> Path:
    return Path(settings.results_dir) / f"{analysis_id}.json"


def _load_result(analysis_id: str) -> AnalysisResult:
    """저장된 분석 결과를 모델로 복원."""
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


@router.get("/analyses/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(analysis_id: str):
    result = _load_result(analysis_id)
    return AnalysisResponse(status="completed", result=result)


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
