# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프롬프트 개선 지침

- 프롬프트를 개선할 때는 특정 데이터셋, 특정 문서군, 특정 계약 유형에만 과도하게 최적화되지 않도록 한다.
- 프롬프트 수정은 **일반화 성능 유지**를 우선으로 하며, 특정 영역에서만 성능이 상승하고 다른 영역의 성능이 저하되는 방식은 지양한다.
- 특정 사례에 맞춘 규칙성 강화보다는, 다양한 계약 유형과 표현 방식에 공통적으로 적용 가능한 방향으로 개선한다.
- 프롬프트 개선 후에는 임대차, 매매, 근로 등 **복수 도메인 샘플**에서 함께 검증하여 편향된 최적화 여부를 확인한다.
- 한 도메인에서만 성능 향상이 확인될 경우, 이를 전체 성능 향상으로 간주하지 않는다.

## 응답 생성 원칙

- 특정 데이터셋에 과적합된 표현이나 결론을 반복하지 않는다.
- 근거 기반 추론을 우선하며, 검색된 자료의 범위를 벗어나는 단정은 피한다.
- 데이터 출처와 적용 범위를 구분하여, 특정 샘플에만 유효한 패턴을 일반 규칙처럼 답변하지 않는다.

## 개발 명령어

```bash
# 전체 시작/종료
./start.sh                  # Ollama + 백엔드(8000) + 프론트엔드(5173)
./stop.sh

# 백엔드 단독
source .venv/bin/activate && uvicorn backend.app.main:app --reload --port 8000

# 프론트엔드 단독
cd frontend && npm run dev

# 지식베이스 구축 (프로젝트 루트에서 실행)
python -m backend.scripts.build_kb                                    # 내장 법률 데이터만 (약 43건)
python -m backend.scripts.build_kb --data-dir backend/data/raw/aihub  # AI Hub 포함 (약 3,474건)

# 정확도 검증 (프롬프트 수정 후 반드시 실행)
python -m backend.scripts.validate
```

사전 조건: Python 3.11+, Node.js 18+, Ollama (`ollama pull qwen3:8b`), `cp .env.example .env`

## 위험 유형(risk_type) 3중 정의 — 반드시 동기화

계약 유형별 risk_type은 `contract_types.py` 안에서 **세 곳에 동시 정의**되어 있다:
1. `*_ANALYSIS_TEMPLATE` 프롬프트 본문의 `위험유형:` 줄 (LLM이 읽는 텍스트)
2. `*_RISK_TYPES` 리스트 상수
3. `CONTRACT_TYPES` 딕셔너리의 `risk_types` 필드

위험 유형을 추가/변경/삭제할 때 세 곳을 모두 수정하지 않으면 LLM 출력과 시스템 정의가 불일치한다. 현재 LLM 반환값에 대한 risk_type 검증은 없으므로, 프롬프트에 적힌 이름이 사실상 유일한 제약이다.

## 지식베이스(KB) 빌드 주의사항

- **AI Hub 원천 데이터 위치**: `backend/data/raw/aihub/` (프로젝트 루트의 `data/raw/`가 아님). `build_kb.py`는 경로가 존재하지 않으면 `[INFO] 데이터 디렉토리가 없습니다`만 찍고 내장 데이터만 인덱싱하므로 **silent fail**에 주의할 것.
- **ChromaDB persist 경로**: `.env`의 `CHROMA_PERSIST_DIR`로 결정되며 기본값은 `data/chroma`가 아닐 수 있다. 현재 환경은 `C:/temp/contract-guard-chroma`. BM25 pkl/json은 `data/bm25/`에 저장.
- **재빌드 시 중복 삽입 버그**: `build_kb.py:104`에서 aihub 항목을 `str(uuid.uuid4())`로 매번 새로 발급하기 때문에, ChromaDB를 비우지 않고 `--data-dir` 옵션으로 재빌드하면 **텍스트가 동일한 문서가 2배로 쌓인다**. 내장 데이터는 고정 ID라 idempotent. 재빌드 전에는 반드시 `CHROMA_PERSIST_DIR`로 지정된 디렉토리를 먼저 삭제할 것.
- **KB 빌드 결과 (참고)**: 정상 빌드 시 lease 1,648 / sales 1,814 / employment 12 (= 3,474). employment은 AI Hub 약관 데이터셋에 근로계약 카테고리 자체가 없어 내장 12건뿐이다.
- **파싱 로직**: `_load_clause_data()`는 파일명에 `임대차`/`매매계약` 키워드가 포함된 JSON만, `_load_judgment_data()`는 경로에 `민사`가 포함된 판결문 중 `LEASE_KEYWORDS`/`SALES_KEYWORDS`로 분류. employment은 두 파서 모두 대상에서 제외된다.

## 계약 유형 추가 시 필요한 작업

`contract_types.py`에서:
1. `*_SYSTEM_PROMPT`, `*_ANALYSIS_TEMPLATE`, `*_NO_REFERENCE`, `*_RISK_TYPES`, `*_BUILTIN_KB` 상수 정의
2. `CONTRACT_TYPES` 딕셔너리에 엔트리 추가
3. `build_kb.py`로 해당 유형의 KB 데이터를 ChromaDB에 인덱싱

동적 등록은 불가하며 코드 변경이 필요하다.

## LLM 응답 파싱 — 4단계 폴백 (`rag/chain.py`)

`_extract_json_from_response()`는 LLM의 불안정한 JSON 출력을 처리하기 위해 4단계 폴백을 사용한다:
1. ` ```json ``` ` 코드블록 추출
2. 가장 바깥 `[...]` 대괄호 매칭
3. 개별 `{...}` 객체 수집 후 `clause_index`/`risk_level` 키 존재 여부로 필터
4. 모두 실패 시 빈 리스트 반환 (경고 로그)

절단된 JSON은 `_repair_truncated_array()`로 완성된 객체만 추출한다. `<think>` 태그도 자동 제거된다. 이 로직을 수정할 때는 각 단계의 독립성을 유지해야 한다.

## 분석 실패 시 동작 — 무음 폴백

- **조항 분리 실패**: `제n조` 패턴 미매칭 시 빈 줄 기준 단락 분리로 폴백 (clause_service.py)
- **LLM 파싱 실패**: 매칭 안 된 조항은 `risk_level=safe`, `confidence=0.3`, `explanation="분석 결과를 파싱하지 못했습니다"`로 처리 — 프론트엔드에서 "안전"으로 표시됨
- **배치 실패**: `asyncio.gather(return_exceptions=True)`로 개별 배치 오류를 삼킴. 10개 배치 중 1개 실패하면 3개 조항이 누락되지만 에러 없이 결과 반환
- **유사 조항 검색 0건**: `no_reference_context` 폴백 텍스트(한 줄)만 LLM에 전달

## 싱글턴 서비스 주의사항

`embedding_service.py`와 `llm_service.py`는 모듈 레벨 전역 변수로 싱글턴을 구현한다. 첫 호출 시 초기화되며, 이후 설정 변경이 반영되지 않는다. 설정을 변경하려면 `reset_llm()` 또는 `reset_embeddings()`를 명시적으로 호출해야 한다. LLM의 `temperature=0.3`, `num_ctx=8192`, `num_predict=4096`은 하드코딩되어 있고 환경변수로 변경 불가하다.

## 프론트엔드 상태 관리

분석 결과는 React Router의 `location.state`로만 전달된다. 페이지 새로고침이나 직접 URL 접근 시 결과가 소실된다. `/api/analyses/{id}` 엔드포인트가 존재하지만, 업로드 응답에서 analysis ID를 프론트엔드에 반환하지 않아 실질적으로 사용되지 않는다.

## 배치 처리

`BATCH_SIZE=3`은 `rag/chain.py`에 하드코딩. Ollama 병렬 처리 수(`OLLAMA_NUM_PARALLEL`)는 `.env`로 설정 가능. 프론트엔드 Axios 타임아웃은 5분(300초)이며, 이를 초과하면 백엔드 분석이 계속 진행되더라도 프론트엔드는 에러를 표시한다.
