import io
import json
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.app.config import settings
from backend.app.models.analysis import AnalysisResponse, AnalysisResult
from backend.app.services.export_service import export_analysis, supported_formats

router = APIRouter()


def _load_result(analysis_id: str) -> AnalysisResult:
    """저장된 분석 결과를 모델로 복원."""
    result_file = Path(settings.results_dir) / f"{analysis_id}.json"
    if not result_file.exists():
        raise HTTPException(status_code=404, detail="분석 결과를 찾을 수 없습니다.")
    with open(result_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    return AnalysisResult(**data)


@router.get("/analyses/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(analysis_id: str):
    result = _load_result(analysis_id)
    return AnalysisResponse(status="completed", result=result)


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
