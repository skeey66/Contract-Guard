import uuid
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from backend.app.models.analysis import AnalysisResponse
from backend.app.services import pdf_service, clause_service, analysis_service
from backend.app.utils.file_utils import save_upload
from backend.app.contract_types import SUPPORTED_CONTRACT_TYPES

router = APIRouter()


@router.post("/documents/upload", response_model=AnalysisResponse)
async def upload_and_analyze(
    file: UploadFile = File(...),
    contract_type: str = Form("lease"),
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드 가능합니다.")

    if contract_type not in SUPPORTED_CONTRACT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 계약 유형: '{contract_type}'. 지원 유형: {SUPPORTED_CONTRACT_TYPES}",
        )

    document_id = str(uuid.uuid4())

    file_path = await save_upload(file, document_id)

    text, page_count = pdf_service.extract_text(file_path)
    if not text.strip():
        raise HTTPException(status_code=422, detail="PDF에서 텍스트를 추출할 수 없습니다.")

    clauses = clause_service.split_clauses(text)
    if not clauses:
        raise HTTPException(status_code=422, detail="계약 조항을 분리할 수 없습니다.")

    result = await analysis_service.run_analysis(
        document_id=document_id,
        filename=file.filename,
        clauses=clauses,
        contract_type=contract_type,
    )

    return AnalysisResponse(status="completed", result=result)
