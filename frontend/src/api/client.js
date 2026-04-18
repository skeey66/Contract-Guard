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

export default api;
