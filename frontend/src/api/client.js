import axios from "axios";

const api = axios.create({
  baseURL: "/",
  timeout: 600000, // 10분 (조항별 개별 LLM 분석 시간 고려)
});

// 계약서 파일 업로드 및 분석 요청 (PDF, DOCX)
export async function uploadDocument(file) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await api.post("/api/documents/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return response.data;
}

// 지식베이스 통계 조회 (홈 화면 카운트업 애니메이션용)
export async function fetchKbStatus() {
  const response = await api.get("/api/kb/status");
  return response.data;
}

// 분석 결과 기반 수정 계약서 다운로드 URL
// 형식: docx | pdf | hwpx
export function buildExportUrl(analysisId, format) {
  return `/api/analyses/${encodeURIComponent(analysisId)}/export?format=${encodeURIComponent(format)}`;
}

// URL 새로고침/직접 접근 시 결과를 서버에서 복원
export async function fetchAnalysis(analysisId) {
  const response = await api.get(`/api/analyses/${encodeURIComponent(analysisId)}`);
  return response.data;
}

// 위험 조항에 대해 사용자가 직접 입력한 수정안을 저장(또는 제거)
// text가 null/공백이면 사용자 수정안을 제거하여 권고안으로 회귀
export async function updateClauseOverride(analysisId, clauseIndex, text) {
  const response = await api.patch(
    `/api/analyses/${encodeURIComponent(analysisId)}/clauses/${clauseIndex}`,
    { text },
  );
  return response.data;
}

export default api;
