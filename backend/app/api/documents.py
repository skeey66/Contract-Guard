import uuid
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException
from backend.app.models.analysis import AnalysisResponse
from backend.app.services import document_service, clause_service, analysis_service
from backend.app.utils.file_utils import save_upload

router = APIRouter()


@router.post("/documents/upload", response_model=AnalysisResponse)
async def upload_and_analyze(
    file: UploadFile = File(...),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="파일명이 없습니다.")

    ext = Path(file.filename).suffix.lower()
    if ext not in document_service.SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(document_service.SUPPORTED_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 파일 형식입니다. 지원 형식: {supported}",
        )

    document_id = str(uuid.uuid4())

    file_path = await save_upload(file, document_id)

    text, page_count = document_service.extract_text(file_path)
    if not text.strip():
        raise HTTPException(status_code=422, detail="문서에서 텍스트를 추출할 수 없습니다.")

    contract_type = clause_service.detect_contract_type(text)
    parties = clause_service.detect_parties(text, contract_type)

    clauses = clause_service.split_clauses(text)
    if not clauses:
        raise HTTPException(status_code=422, detail="계약 조항을 분리할 수 없습니다.")

    result = await analysis_service.run_analysis(
        document_id=document_id,
        filename=file.filename,
        clauses=clauses,
        contract_type=contract_type,
        parties=parties,
    )

    return AnalysisResponse(status="completed", result=result)
