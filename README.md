# Contract Guard

로컬 LLM과 RAG 기술을 활용한 **보안 특화형 AI 계약서 위험 조항 분석 시스템**입니다.
외부 API 호출 없이 내 컴퓨터에서만 동작하므로 계약서 데이터가 외부로 유출되지 않습니다.

PDF, DOCX, HWP, HWPX 형식의 계약서를 업로드하면 각 조항별 위험도를 자동 분석하고 개선안을 제시합니다.

---

## 동작 흐름

```
계약서 업로드 (PDF / DOCX / HWP / HWPX)
  ↓
텍스트 추출 (PyMuPDF / python-docx / hwp2yaml)
  ↓
계약 유형 자동 감지 (임대차 / 매매 / 근로)
  ↓
조항 분리 (제N조 패턴 + 단락 폴백)
  ↓
룰 기반 사전 필터링 (명백한 safe/high 패턴 결정적 분류)
  ↓
유사 법률·판례 검색 (ChromaDB + Ko-SBERT)
  ↓
LLM 배치 분석 (Ollama · qwen3:8b, 4-bit 양자화)
  ↓
위험도 분류 + 개선안 → 결과 화면 (React)
```

각 조항에 대해 **위험도(high/medium/low/safe)**, 신뢰도 점수, 위험 유형, 설명, 개선 제안, 유사 참고 조항을 제공합니다.

---

## 주요 기능

- **계약서 업로드 & 즉시 분석** — PDF, DOCX, HWP, HWPX 파일을 올리면 조항별 위험도를 바로 확인
- **계약 유형 자동 감지** — 키워드 빈도 기반으로 임대차/매매/근로 유형을 자동 판별
- **조항 자동 분리** — `제N조` 패턴 인식, 매칭 실패 시 단락 기반 폴백
- **룰 기반 사전 필터링** — 명백한 독소조항/안전조항은 LLM 호출 전에 결정적으로 분류
- **RAG 기반 분석** — 법률 조항·판례 지식베이스에서 조항별 유사 근거 검색
- **계약 유형별 위험 유형 탐지** — 유형별 8가지 위험 유형 (보증금 미반환, 하자담보 면제, 부당해고 등)
- **분석 결과 시각화** — 위험도 배지, 조항 카드, 유사 참고 조항 표시
- **완전 로컬 실행** — 외부 API 호출 없이 내 컴퓨터에서만 동작, 계약서 데이터 유출 방지

---

## 지원 계약 유형

| 유형 | 분석 관점 | 위험 유형 예시 |
|------|-----------|---------------|
| 임대차 | 임차인(세입자) | 보증금 미반환, 일방적 해지, 수선의무 전가, 묵시적 갱신 배제 등 |
| 매매 | 매수인(구매자) | 하자담보 면제, 소유권이전 지연, 계약금 과다, 권리하자 미고지 등 |
| 근로 | 근로자(직원) | 임금 부당, 부당해고, 경업금지 과다, 연차 미보장, 퇴직금 미지급 등 |

---

## 지원 파일 형식

| 형식 | 확장자 | 추출 방식 |
|------|--------|-----------|
| PDF | `.pdf` | PyMuPDF |
| Word | `.docx` | python-docx |
| 한글 | `.hwp` | hwp2yaml (순수 Python, 한글 프로그램 불필요) |
| 한글 (신규) | `.hwpx` | hwp2yaml |

---

## 기술 스택

### Backend
- **FastAPI** + Uvicorn — REST API 서버
- **LangChain** + langchain-ollama — LLM 오케스트레이션
- **ChromaDB** — 벡터 데이터베이스 (법률·판례 지식베이스)
- **HuggingFace** — 한국어 임베딩 (`jhgan/ko-sroberta-multitask`)
- **PyMuPDF** — PDF 텍스트 추출
- **python-docx** — DOCX 텍스트 추출
- **hwp2yaml** — HWP/HWPX 텍스트 추출

### Frontend
- **React 18** + **Vite** — SPA
- **React Router** — 페이지 라우팅
- **Axios** — API 통신 (10분 타임아웃)

### LLM
- **Ollama** — 로컬 LLM 서버 (기본: `qwen3:8b`, 4-bit 양자화)

---

## 프로젝트 구조

```
Contract-Guard/
├── backend/
│   ├── app/
│   │   ├── api/            # 엔드포인트 (health, documents, analyses, kb)
│   │   ├── models/         # Pydantic 모델 (analysis, clause, risk)
│   │   ├── services/       # 비즈니스 로직 (document, clause, llm, chroma, retrieval, analysis, embedding, rule_filter)
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
│   ├── uploads/            # 업로드된 파일 원본
│   └── results/            # 분석 결과 JSON
├── start.sh / start.bat    # 전체 서비스 시작 (Linux·Mac / Windows)
├── stop.sh / stop.bat      # 전체 서비스 종료
├── .env.example            # 환경변수 템플릿
└── README.md
```

---

## 설치 및 실행 가이드

아래 순서대로 따라하면 프로그래밍 경험이 없어도 실행할 수 있습니다.

### 1단계: 필수 프로그램 설치

아래 3가지 프로그램을 먼저 설치해주세요. 모두 무료입니다.

| 프로그램 | 다운로드 | 설명 |
|----------|----------|------|
| **Python 3.11 이상** | https://www.python.org/downloads/ | 설치 시 **"Add Python to PATH"** 반드시 체크 |
| **Node.js 18 이상** | https://nodejs.org/ | LTS 버전 권장 |
| **Ollama** | https://ollama.ai | AI 모델을 내 컴퓨터에서 실행하는 프로그램 |

### 2단계: AI 모델 다운로드

Ollama 설치 후, 터미널(명령 프롬프트)을 열고 아래 명령어를 입력합니다.

```bash
ollama pull qwen3:8b
```

약 5GB를 다운로드하므로 시간이 걸릴 수 있습니다. "success"가 나오면 완료입니다.

### 3단계: 프로젝트 설정

프로젝트 폴더에서 터미널을 열고 아래 명령어를 순서대로 실행합니다.

**Windows (명령 프롬프트):**

```bat
:: 환경변수 파일 생성
copy .env.example .env

:: 백엔드 설정
python -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt

:: 프론트엔드 설정
cd frontend
npm install
cd ..
```

**Mac / Linux (터미널):**

```bash
# 환경변수 파일 생성
cp .env.example .env

# 백엔드 설정
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt

# 프론트엔드 설정
cd frontend && npm install && cd ..
```

### 4단계: 지식베이스 구축

내장된 법률 데이터(주택임대차보호법, 민법, 근로기준법 등)를 검색 가능한 형태로 변환합니다.
이 작업은 최초 1회만 실행하면 됩니다.

```bash
python -m backend.scripts.build_kb
```

AI Hub 원천 데이터가 있는 경우 추가로 포함할 수 있습니다:

```bash
python -m backend.scripts.build_kb --data-dir data/raw/aihub
```

### 5단계: 실행

**Windows:**

`start.bat` 파일을 더블클릭하면 됩니다.

또는 터미널에서:

```bat
start.bat
```

**Mac / Linux:**

```bash
./start.sh
```

Ollama OK, 백엔드 OK, 프론트엔드 OK가 모두 표시되면 준비 완료입니다.

### 6단계: 사용

브라우저에서 아래 주소로 접속합니다:

```
http://localhost:5173
```

계약서 파일(PDF, DOCX, HWP, HWPX)을 업로드하면 자동으로 분석이 시작됩니다.

### 종료

**Windows:** `stop.bat` 더블클릭

**Mac / Linux:**

```bash
./stop.sh
```

---

## 접속 주소

| 서비스 | URL |
|--------|-----|
| 웹 화면 | http://localhost:5173 |
| 백엔드 API | http://localhost:8000 |
| API 문서 (Swagger) | http://localhost:8000/docs |

---

## 환경 변수

`.env.example`을 복사하여 `.env`를 생성합니다. 대부분의 경우 기본값 그대로 사용하면 됩니다.

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `OLLAMA_MODEL_NAME` | `qwen3:8b` | Ollama LLM 모델 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 서버 주소 |
| `OLLAMA_TIMEOUT` | `60` | LLM 호출 타임아웃 (초) |
| `EMBEDDING_DEVICE` | `auto` | 임베딩 디바이스 (`auto`/`cpu`/`cuda`) |
| `CHROMA_COLLECTION` | `contract_kb` | ChromaDB 컬렉션명 |
| `RETRIEVAL_TOP_K` | `5` | 유사 조항 검색 개수 |
| `RETRIEVAL_MIN_SCORE` | `0.5` | 최소 유사도 점수 |

---

## API

| Method | Endpoint | 설명 |
|--------|----------|------|
| `GET` | `/health` | Ollama 연결 상태 + KB 문서 수 |
| `POST` | `/api/documents/upload` | 파일 업로드 및 분석 (multipart/form-data) |
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

## 자주 발생하는 문제

| 증상 | 해결 방법 |
|------|-----------|
| `start.bat` 실행 시 "Ollama 실패" | Ollama가 설치되어 있는지 확인. 터미널에서 `ollama serve` 직접 실행 |
| `start.bat` 실행 시 "백엔드 실패" | `.venv`가 생성되었는지, `pip install`이 완료되었는지 확인 |
| 분석 시 오랜 시간 소요 | 정상입니다. 조항 수에 따라 1~5분 소요될 수 있습니다 |
| 임베딩 모델 다운로드 오류 | 최초 실행 시 인터넷 연결 필요 (이후 오프라인 가능) |
| HWP 업로드 시 텍스트 추출 실패 | 스캔 이미지로만 구성된 HWP는 지원하지 않습니다 |
| 페이지 새로고침 시 결과 사라짐 | 현재 알려진 제한사항입니다. 분석 결과 화면에서 새로고침하지 마세요 |

---

## 유틸리티 스크립트

```bash
# 지식베이스 구축 (최초 1회)
python -m backend.scripts.build_kb

# AI Hub 데이터 포함 KB 구축
python -m backend.scripts.build_kb --data-dir data/raw/aihub

# 분석 정확도 검증
python -m backend.scripts.validate
```

---

## 알려진 제한 사항

- 분석 정확도는 LLM 모델 성능, 프롬프트, KB 품질에 의존합니다.
- 프론트엔드 결과는 라우팅 state 기반으로, 새로고침 시 소실됩니다.
- 스캔 이미지로만 구성된 파일은 텍스트 추출이 불가합니다.
- 인증/인가, 파일 크기 제한, 비동기 작업 큐 등은 미구현 상태입니다.

---

**K&H2** — Legal Contract Review Project Team
