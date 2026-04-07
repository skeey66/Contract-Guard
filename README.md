# Contract Guard

로컬 LLM과 RAG 기술을 활용한 보안 특화형 AI 계약서 위험 조항 분석 시스템입니다.
외부 API 호출 없이 온프레미스 환경에서 동작하며, 계약서 내 불공정 조항을 자동 탐지하고 개선안을 제시합니다.

---

## 동작 흐름

```
PDF 업로드
  ↓
텍스트 추출 (PyMuPDF)
  ↓
계약 유형 자동 감지 (임대차 / 매매 / 근로)
  ↓
조항 분리 (제N조 패턴 + 단락 폴백)
  ↓
유사 법률·판례 검색 (ChromaDB + Ko-SBERT)
  ↓
LLM 배치 분석 (Ollama · qwen3:8b)
  ↓
위험도 분류 + 개선안 → 결과 화면 (React)
```

각 조항에 대해 **위험도(high/medium/low/safe)**, 신뢰도 점수, 위험 유형, 설명, 개선 제안, 유사 참고 조항을 제공합니다.

---

## 주요 기능

- **PDF 업로드 & 즉시 분석** — 계약서 PDF를 올리면 조항별 위험도를 바로 확인
- **계약 유형 자동 감지** — 키워드 빈도 기반으로 임대차/매매/근로 유형을 자동 판별
- **조항 자동 분리** — `제N조` 패턴 인식, 매칭 실패 시 단락 기반 폴백
- **RAG 기반 분석** — 법률 조항·판례 지식베이스에서 조항별 유사 근거 검색
- **계약 유형별 위험 유형 탐지** — 유형별 8가지 위험 유형 (보증금 미반환, 하자담보 면제, 부당해고 등)
- **분석 결과 시각화** — 위험도 배지, 조항 카드, 유사 참고 조항 표시
- **완전 로컬 실행** — 외부 API 호출 없이 온프레미스에서 동작, 계약서 데이터 유출 방지

---

## 지원 계약 유형

| 유형 | 분석 관점 | 위험 유형 예시 |
|------|-----------|---------------|
| 임대차 | 임차인(세입자) | 보증금 미반환, 일방적 해지, 수선의무 전가, 묵시적 갱신 배제 등 |
| 매매 | 매수인(구매자) | 하자담보 면제, 소유권이전 지연, 계약금 과다, 권리하자 미고지 등 |
| 근로 | 근로자(직원) | 임금 부당, 부당해고, 경업금지 과다, 연차 미보장, 퇴직금 미지급 등 |

---

## 기술 스택

### Backend
- **FastAPI** + Uvicorn — REST API 서버
- **LangChain** + langchain-ollama — LLM 오케스트레이션
- **ChromaDB** — 벡터 데이터베이스 (법률·판례 지식베이스)
- **HuggingFace** — 한국어 임베딩 (`jhgan/ko-sroberta-multitask`)
- **PyMuPDF** — PDF 텍스트 추출

### Frontend
- **React 18** + **Vite** — SPA
- **React Router** — 페이지 라우팅
- **Axios** — API 통신 (5분 타임아웃)

### LLM
- **Ollama** — 로컬 LLM 서버 (기본: `qwen3:8b`)

---

## 프로젝트 구조

```
Contract-Guard/
├── backend/
│   ├── app/
│   │   ├── api/            # 엔드포인트 (health, documents, analyses, kb)
│   │   ├── models/         # Pydantic 모델 (analysis, clause, risk)
│   │   ├── services/       # 비즈니스 로직 (pdf, clause, llm, chroma, retrieval, analysis, embedding)
│   │   ├── rag/            # 프롬프트 템플릿 + 배치 분석 체인
│   │   ├── utils/          # 파일 유틸리티
│   │   ├── config.py       # 환경변수 기반 설정
│   │   ├── contract_types.py  # 계약 유형별 프롬프트·위험유형·내장 KB 정의
│   │   └── main.py         # FastAPI 앱 진입점
│   ├── scripts/
│   │   ├── build_kb.py     # 지식베이스 구축
│   │   └── validate.py     # 분석 정확도 검증
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/          # UploadPage, ResultPage
│   │   ├── components/     # FileUploader, RiskBadge
│   │   ├── api/            # Axios 클라이언트
│   │   └── styles/         # 글로벌 CSS
│   ├── vite.config.js
│   └── package.json
├── data/
│   ├── chroma/             # ChromaDB 벡터 저장소
│   ├── uploads/            # 업로드된 PDF 원본
│   └── results/            # 분석 결과 JSON
├── start.sh / start.bat    # 전체 서비스 시작 (Linux/Windows)
├── stop.sh / stop.bat      # 전체 서비스 종료
├── .env.example            # 환경변수 템플릿
└── README.md
```

---

## 빠른 시작

### 사전 준비

- Python 3.11+
- Node.js 18+
- [Ollama](https://ollama.ai) 설치

```bash
ollama pull qwen3:8b
```

### 설치

```bash
# 환경변수 설정
cp .env.example .env

# 백엔드 의존성
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt

# 프론트엔드 의존성
cd frontend && npm install && cd ..
```

### 실행

```bash
# 방법 1: 스크립트로 한 번에 실행
./start.sh          # Linux/Mac
start.bat           # Windows

# 방법 2: 개별 실행
ollama serve
uvicorn backend.app.main:app --reload --port 8000
cd frontend && npm run dev
```

### 종료

```bash
./stop.sh           # Linux/Mac
stop.bat            # Windows
```

### 접속

| 서비스 | URL |
|--------|-----|
| 프론트엔드 | http://localhost:5173 |
| 백엔드 API | http://localhost:8000 |
| API 문서 (Swagger) | http://localhost:8000/docs |

---

## 지식베이스(KB) 구축

내장 법률 데이터(주택임대차보호법, 민법, 근로기준법 등)만으로도 분석이 가능하지만, 추가 데이터로 품질을 향상시킬 수 있습니다.

```bash
# 내장 법률 데이터로 구축
python -m backend.scripts.build_kb

# AI Hub 원천 데이터 포함 시
python -m backend.scripts.build_kb --data-dir data/raw/aihub

# KB 상태 확인
curl http://localhost:8000/api/kb/status
```

---

## 환경 변수

`.env.example`을 복사하여 `.env`를 생성하세요.

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `OLLAMA_MODEL_NAME` | `qwen3:8b` | Ollama LLM 모델 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 서버 주소 |
| `OLLAMA_TIMEOUT` | `180` | LLM 호출 타임아웃 (초) |
| `EMBEDDING_MODEL` | `jhgan/ko-sroberta-multitask` | 한국어 임베딩 모델 |
| `EMBEDDING_DEVICE` | `auto` | 임베딩 디바이스 (`auto`/`cpu`/`cuda`) |
| `CHROMA_COLLECTION` | `contract_kb` | ChromaDB 컬렉션명 |
| `RETRIEVAL_TOP_K` | `5` | 유사 조항 검색 개수 |
| `RETRIEVAL_MIN_SCORE` | `0.5` | 최소 유사도 점수 |

---

## API

| Method | Endpoint | 설명 |
|--------|----------|------|
| `GET` | `/health` | Ollama 연결 상태 + KB 문서 수 |
| `POST` | `/api/documents/upload` | PDF 업로드 및 분석 (multipart/form-data) |
| `GET` | `/api/analyses/{id}` | 저장된 분석 결과 조회 |
| `GET` | `/api/kb/status` | KB 컬렉션 상태 |

### 응답 예시

```json
{
  "status": "completed",
  "result": {
    "id": "analysis-uuid",
    "filename": "contract.pdf",
    "total_clauses": 11,
    "risky_clauses": 6,
    "summary": "총 11개 조항 중 6개 조항에서 위험 요소가 발견되었습니다...",
    "clause_analyses": [
      {
        "clause_index": 4,
        "clause_title": "제4조 (보증금 반환)",
        "risk_level": "high",
        "confidence": 0.88,
        "risks": [
          {
            "risk_type": "보증금_미반환_위험",
            "description": "보증금 반환 시기를 과도하게 지연...",
            "suggestion": "반환 시점과 공제 기준을 명확히..."
          }
        ],
        "similar_references": [
          "주택임대차보호법 제3조의2 ... (유사도: 0.78)"
        ],
        "explanation": "임차인에게 불리한 보증금 반환 제한 조항입니다."
      }
    ]
  }
}
```

---

## 유틸리티 스크립트

```bash
# 지식베이스 구축
python -m backend.scripts.build_kb

# AI Hub 데이터 포함 KB 구축
python -m backend.scripts.build_kb --data-dir data/raw/aihub

# 분석 정확도 검증
python -m backend.scripts.validate
python -m backend.scripts.validate --limit 20    # 일부만 테스트
```

---

## 알려진 제한 사항

- 분석 정확도는 LLM 모델 성능, 프롬프트, KB 품질에 의존합니다.
- 프론트엔드 결과는 라우팅 state 기반으로, 새로고침 시 소실됩니다.
- PDF 형식만 지원합니다 (HWP, DOCX 미지원).
- 인증/인가, 파일 크기 제한, 비동기 작업 큐 등은 미구현 상태입니다.

---

**K&H2** — Legal Contract Review Project Team
