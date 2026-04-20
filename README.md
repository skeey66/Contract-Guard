# Contract Guard

로컬 LLM과 RAG 기술을 활용한 **보안 특화형 AI 계약서 위험 조항 분석 시스템**입니다.
외부 API 호출 없이 내 컴퓨터에서만 동작하므로 계약서 데이터가 외부로 유출되지 않습니다.

PDF, DOCX, HWP, HWPX 형식의 계약서를 업로드하면 각 조항별 위험도를 자동 분석하고 개선안을 제시하며,
수정안이 반영된 계약서를 DOCX/PDF/HWPX로 내보낼 수 있습니다.

---

## 동작 흐름

```
계약서 업로드 (PDF / DOCX / HWP / HWPX)
  ↓
텍스트 추출 (PyMuPDF / python-docx / hwp2yaml)
  ↓
계약 유형 자동 감지 (임대차 / 매매 / 근로 / 용역·도급 / 금전소비대차)
  ↓
조항 분리 (제N조 패턴 + 단락 폴백)
  ↓
룰 기반 사전 필터링 (명백한 safe/high 패턴 결정적 분류)
  ↓
하이브리드 검색 (ChromaDB 벡터 + BM25, RRF 결합, 법률 본문 부스트)
  ↓
LLM 배치 분석 (Ollama · exaone3.5:7.8b, 4-bit 양자화, BATCH_SIZE=3)
  ↓
위험도 + 개선안 + 권고 수정안 생성 → 결과 화면 (React)
  ↓
(선택) 수정안 반영 계약서 내보내기 (DOCX / PDF / HWPX)
```

각 조항에 대해 **위험도(high/medium/low/safe)**, 신뢰도 점수, 위험 유형, 설명, 개선 제안,
유사 참고 조항(법률/판례/약관), 그리고 표준약관 기반 **권고 수정안**을 제공합니다.

---

## 주요 기능

- **계약서 업로드 & 즉시 분석** — PDF, DOCX, HWP, HWPX 파일을 올리면 조항별 위험도를 바로 확인
- **계약 유형 자동 감지** — 키워드 빈도 기반으로 5가지 계약 유형 자동 판별
- **조항 자동 분리** — `제N조` 패턴 인식, 매칭 실패 시 단락 기반 폴백
- **룰 기반 사전 필터링** — 명백한 독소조항/안전조항은 LLM 호출 전에 결정적으로 분류
- **하이브리드 RAG 검색** — 벡터 검색(Ko-SBERT) + BM25 키워드 검색을 RRF로 결합,
  법률 본문(source=law)에 가중치를 부여해 grounding 근거 확보
- **계약 유형별 위험 유형 탐지** — 유형별 8가지 위험 유형 (보증금 미반환, 하자담보 면제, 부당해고 등)
- **권고 수정안 생성** — 위험 조항에 대해 표준약관 기반 수정안 자동 생성
- **사용자 수정안 저장** — 권고안을 참고해 사용자가 직접 수정한 최종안 저장/수정
- **수정안 반영 계약서 내보내기** — DOCX / PDF / HWPX 중 원하는 형식으로 다운로드
- **분석 결과 시각화** — 위험도 배지, 조항 카드, 파이차트, 유사 참고 조항 카테고리 분류
- **완전 로컬 실행** — 외부 API 호출 없이 내 컴퓨터에서만 동작, 계약서 데이터 유출 방지

---

## 지원 계약 유형

| 유형 | 분석 관점 | 위험 유형 예시 |
|------|-----------|---------------|
| 임대차 (lease) | 임차인(세입자) | 보증금 미반환, 일방적 해지, 수선의무 전가, 묵시적 갱신 배제 등 |
| 매매 (sales) | 매수인(구매자) | 하자담보 면제, 소유권이전 지연, 계약금 과다, 권리하자 미고지 등 |
| 근로 (employment) | 근로자(직원) | 임금 부당, 부당해고, 경업금지 과다, 연차 미보장, 퇴직금 미지급 등 |
| 용역·도급 (service) | 수급인(용역 수행자) | 대금 지급 지연, 과도한 하자담보, 일방적 해제, 지식재산권 전가 등 |
| 금전소비대차 (loan) | 차주(돈을 빌리는 사람) | 이자제한법 초과, 과도한 지연손해금, 기한이익 상실 남용 등 |

---

## 지원 파일 형식

| 형식 | 확장자 | 추출/생성 방식 |
|------|--------|-----------|
| PDF | `.pdf` | PyMuPDF (입력) / reportlab (출력) |
| Word | `.docx` | python-docx |
| 한글 | `.hwp` / `.hwpx` | hwp2yaml (순수 Python, 한글 프로그램 불필요) |

---

## 기술 스택

### Backend
- **FastAPI** + Uvicorn — REST API 서버
- **LangChain** + langchain-ollama — LLM 오케스트레이션
- **ChromaDB** — 벡터 데이터베이스 (법률·판례·약관 지식베이스)
- **rank-bm25** — BM25 키워드 검색 (벡터 검색과 RRF로 결합)
- **HuggingFace** — 한국어 임베딩 (`jhgan/ko-sroberta-multitask`)
- **PyMuPDF / python-docx / hwp2yaml** — 문서 텍스트 추출
- **reportlab / python-docx / zipfile** — 계약서 내보내기 (PDF/DOCX/HWPX)

### Frontend
- **React 18** + **Vite** — SPA
- **React Router** — 페이지 라우팅
- **Axios** — API 통신 (5분 타임아웃)

### LLM
- **Ollama** — 로컬 LLM 서버 (기본: `exaone3.5:7.8b`, 4-bit 양자화)

---

## 프로젝트 구조

```
Contract-Guard/
├── backend/
│   ├── app/
│   │   ├── api/            # 엔드포인트 (health, documents, analyses, kb)
│   │   ├── models/         # Pydantic 모델 (analysis, clause, risk)
│   │   ├── services/       # 비즈니스 로직
│   │   │   ├── document_service.py    # 파일 텍스트 추출
│   │   │   ├── clause_service.py      # 계약 유형 감지·조항 분리
│   │   │   ├── rule_filter.py         # 룰 기반 사전 필터링
│   │   │   ├── embedding_service.py   # Ko-SBERT 임베딩 싱글턴
│   │   │   ├── chroma_service.py      # ChromaDB 벡터 검색
│   │   │   ├── bm25_service.py        # BM25 키워드 검색
│   │   │   ├── retrieval_service.py   # 하이브리드 검색(RRF) + 법률 부스트
│   │   │   ├── llm_service.py         # Ollama LLM 싱글턴
│   │   │   ├── analysis_service.py    # 분석 오케스트레이션
│   │   │   ├── rewrite_service.py     # 권고 수정안 생성
│   │   │   ├── summary_service.py     # 전체 요약 생성
│   │   │   └── export_service.py      # DOCX/PDF/HWPX 내보내기
│   │   ├── rag/            # 프롬프트 템플릿 + 배치 분석 체인
│   │   ├── utils/          # 파일 유틸리티
│   │   ├── config.py       # 환경변수 기반 설정
│   │   ├── contract_types.py  # 5개 계약 유형별 프롬프트·위험유형·내장 KB
│   │   └── main.py         # FastAPI 앱 진입점
│   ├── scripts/
│   │   ├── download_laws.py   # legalize-kr GitHub에서 법률 본문 다운로드
│   │   ├── build_kb.py        # 지식베이스 구축(ChromaDB + BM25)
│   │   └── validate.py        # 분석 정확도 검증
│   ├── data/
│   │   └── raw/            # AI Hub·법률 원천 데이터 저장 위치
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/          # UploadPage, ResultPage
│   │   ├── components/     # FileUploader, RiskBadge, RiskPieChart
│   │   ├── api/            # Axios 클라이언트
│   │   └── styles/         # 글로벌 CSS
│   ├── vite.config.js
│   └── package.json
├── data/
│   ├── chroma/             # ChromaDB 벡터 저장소
│   ├── bm25/               # BM25 인덱스 (pkl/json)
│   ├── uploads/            # 업로드된 파일 원본
│   └── results/            # 분석 결과 JSON (사용자 수정안 포함)
├── start.sh / start.bat    # 전체 서비스 시작 (Linux·Mac / Windows)
├── stop.sh / stop.bat      # 전체 서비스 종료
├── setup.sh / setup.bat    # 초기 환경 설정
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
ollama pull exaone3.5:7.8b
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
# (권장) legalize-kr 법률 본문 다운로드 → ChromaDB 인덱싱
python -m backend.scripts.download_laws
python -m backend.scripts.build_kb --include-laws --clear

# 내장 데이터만으로 빠르게 구축
python -m backend.scripts.build_kb

# AI Hub 약관/판결문 원천 데이터가 있는 경우(위치: backend/data/raw/aihub/)
python -m backend.scripts.build_kb --data-dir backend/data/raw/aihub
```

> ⚠️ 재빌드 시에는 `--clear` 옵션을 사용하거나 `data/chroma/` 디렉토리를 먼저 삭제하세요.
> AI Hub 항목은 매 실행마다 새로운 ID로 삽입되어 중복이 쌓일 수 있습니다.

### 5단계: 실행

**Windows:** `start.bat` 파일을 더블클릭하거나 터미널에서 `start.bat` 실행

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
분석 결과 화면에서 각 위험 조항의 권고 수정안을 확인하고, 필요 시 직접 편집한 뒤
**DOCX / PDF / HWPX** 형식으로 수정본을 내려받을 수 있습니다.

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
| `OLLAMA_MODEL_NAME` | `exaone3.5:7.8b` | Ollama LLM 모델 |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 서버 주소 |
| `OLLAMA_TIMEOUT` | `60` | LLM 호출 타임아웃 (초) |
| `EMBEDDING_DEVICE` | `auto` | 임베딩 디바이스 (`auto`/`cpu`/`cuda`) |
| `CHROMA_COLLECTION` | `contract_kb` | ChromaDB 컬렉션명 |
| `RULE_SCORE_THRESHOLD` | `0.3` | 룰 기반 필터 점수 임계값 |
| `RETRIEVAL_TOP_K` | `5` | 유사 조항 검색 개수 |
| `RETRIEVAL_MIN_SCORE` | `0.5` | 최소 유사도 점수 |

> `temperature`, `num_ctx(8192)`, `num_predict(4096)`, `BATCH_SIZE(3)` 등은 코드에 하드코딩되어 있습니다.

---

## API

| Method | Endpoint | 설명 |
|--------|----------|------|
| `GET` | `/health` | Ollama 연결 상태 + KB 문서 수 |
| `POST` | `/api/documents/upload` | 파일 업로드 및 분석 (multipart/form-data) |
| `GET` | `/api/analyses/{id}` | 저장된 분석 결과 조회 |
| `PATCH` | `/api/analyses/{id}/clauses/{clause_index}` | 특정 조항의 사용자 수정안 저장/삭제 |
| `GET` | `/api/analyses/{id}/export?format=docx\|pdf\|hwpx` | 수정안 반영 계약서 다운로드 |
| `GET` | `/api/kb/status` | KB 컬렉션 상태 (법률/판례/약관 카테고리별 집계) |

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
        "explanation": "임차인에게 불리한 보증금 반환 제한 조항입니다.",
        "suggested_rewrite": "임대인은 계약 종료일로부터 1개월 이내에 보증금을 반환한다...",
        "user_override": null,
        "analysis_status": "ok"
      }
    ]
  }
}
```


## 유틸리티 스크립트

```bash
# legalize-kr에서 법률 본문 다운로드 (최초 1회)
python -m backend.scripts.download_laws

# 지식베이스 구축 (법률 본문 포함, ChromaDB 초기화)
python -m backend.scripts.build_kb --include-laws --clear

# 내장 데이터만으로 KB 구축
python -m backend.scripts.build_kb

# AI Hub 데이터 포함 KB 구축
python -m backend.scripts.build_kb --data-dir backend/data/raw/aihub

# 분석 정확도 검증 (프롬프트 수정 후 권장)
python -m backend.scripts.validate
```

---

**K&H2** — Legal Contract Review Project Team
