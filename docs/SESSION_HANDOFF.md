# Contract-Guard 세션 핸드오프 (2026-05-03)

새 컨텍스트에서 이어받을 때 필수로 알아야 할 핵심 내용.

## 1. 현재 시스템 상태

- **임베딩**: `nlpai-lab/KURE-v1` (한국어 retrieval SOTA, bge-m3 기반)
- **검색**: BM25 + 벡터 + RRF + stratified quota (law 2 + safe 1 + judgment 1 + unfair 1)
- **KB**: 23,902건 (5도메인: lease/sales/employment/service/loan)
- **LLM**: EXAONE 3.5 7.8B (Ollama, GPU)
- **검증 정확도**: **96.8%** (538건 lease, safe 100% / risky 96.6%)

## 2. 위험도 분류 — B안 (액션 중심 4단계)

enum은 유지(`HIGH/MEDIUM/LOW/SAFE`), 라벨만 의미 재정의:

| enum | 라벨 | 의미 |
|---|---|---|
| HIGH | **법률 위반** | 약관규제법·민법·주임법 명백 위반, 즉시 수정 |
| MEDIUM | **계약자 불리** | 위법은 아니나 일방적 부담, 협상 권장 |
| LOW | **검토 권장** | 회색지대·정보 부족 |
| SAFE | **안전** | 표준 정형 표현 |

라벨 정의 위치: `frontend/src/components/RiskBadge.jsx`, `RiskPieChart.jsx`, `backend/app/services/export_service.py:_risk_label`, 5개 도메인 `contract_types.py` 프롬프트 high/medium/low 정의.

## 3. 핵심 아키텍처 — Evidence-based Hallucination Filtering ★

**가장 중요한 기능**. `analysis_service.py`의 `_build_clause_analyses`에서:

1. LLM이 위험(HIGH/MEDIUM)으로 판정 + `risks[].quote` 필수
2. `_validate_quote(raw, clause_text)`: quote가 본 조항의 substring인지 검증
3. quote 누락 시 `_extract_risky_excerpt()`로 위험 시그널 단어 자동 추출 폴백
4. 모든 risk가 quote 없으면 → 환각으로 간주 → safe로 강등

**효과**: 정확도 91.1% → 96.8%, 거짓 경보 29건 → 0건. 본질적으로 "본문 인용 없는 위험 주장 = 환각"이라는 원칙.

위험 시그널 단어(`_RISK_SIGNAL_WORDS`)는 도메인 중립 50+개: 없이/포기/단독/일방/즉시/면제/배제/초과/공제/유보/제한/박탈/본사/소재지/지정/전속관할/전액 부담/분담한다/충당/전가 등.

룰 기반 결과(`_status="kb_high"/"kb_safe"`)는 환각 차단 예외 (룰은 신뢰).

## 4. KB 기반 분류기 한계 (중요)

`chain.py`의 `_classify_by_kb`:
- KURE-v1 임베딩 유사도로 1차 분류 시도
- 임계값: HIGH 0.85 / SAFE 0.88 (매우 높게 설정)
- 표면 어휘 유사도가 의미 매칭 못 따라가서 false-positive 多 → 임계값 매우 보수적
- **거의 모든 조항이 LLM 판단으로 위임됨** — 실질적으로 KB 분류기는 명백한 케이스만 처리
- 사용자 의도("KB 데이터로 판단")는 임베딩 한계로 100% 달성 불가. 대신 LLM이 RAG 인용 강제로 grounded 판단.

## 5. Frontend 주요 변경

### 헤더 강화 (`ResultPage.jsx` `result-top-bar-v2`)
- 파일명 + 계약유형 + 조항수 + 평균 신뢰도
- 위험도 카운트 배지 (법률 위반 N / 계약자 불리 N / 안전 N)
- "위험 조항만 (N)" 토글 버튼 (showRiskyOnly state)
- PDF 보고서 버튼은 헤더에서 제거됨

### 대시보드 (`OverviewDashboard`)
한 줄 3개 카드 (1.4fr/1fr/1fr):
- **종합 요약** (좌): SummaryRenderer, ■ 라벨 단락 단위 + `**X**` 형광펜
- **위험도 분포** (중): 도넛 차트 + 회색 구분선 + 히트맵 + 회색 구분선 + 위험 유형 Top 3
- **참고 자료** (우): GroupedReferencesPanel (4 카테고리 + 유사도 막대)

도넛은 **2분류만 표시** (위험 빨강 vs 안전 초록). 세부 분류는 헤더 배지·히트맵으로.

### 시각 핵심 컴포넌트
- `EvidenceComparisonPanel`: 본 조항 ↔ KB 매칭 사례 세로 비교, 양쪽 형광펜, 클릭 시 KbDetailModal
- `ClauseTextHighlighted`: 조항 본문에 quote 형광펜
- `ExplanationWithCitations`: explanation의 [참고N] 클릭 가능 popover
- `RewriteEditDrawer`: **가운데 모달** (이전 우측 drawer에서 변경), `ref-modal-overlay` 패턴 사용, 슬라이드인 애니메이션, max-width 1100px / height 90vh, textarea min-height 480px

### `**...**` markdown 처리 (사용자 명시 요구사항)
- **종합요약(SummaryRenderer)**: `renderWithMdMarks()` → `<mark>` 형광펜
- **수정안(RewriteEditor)**: `stripMdMarks()` → 평문
- **근거자료(KB·법률·판례)**: `stripMdMarks()` → 평문
- **본 조항**: `stripMdMarks()`
- 두 헬퍼: `frontend/src/pages/ResultPage.jsx` 상단

## 6. 발생했던 문제·해결

### LLM이 quote 누락하면 진짜 위험도 환각으로 차단 (false negative)
→ `_extract_risky_excerpt` 자동 폴백 (위험 시그널 단어 매칭). 1차 시그널 매칭만 사용 (2차 "본문 첫 문장 폴백"은 환각도 통과시켜서 제거).

### "즉시 해지"가 단독으로 high 판정 → 민법 제640조 정형 표현 false positive
→ `_COMMON_LAW_VERBATIM_VETO`에서 "즉시 해지" 제거. 절차 박탈 패턴("최고 없이 즉시", "통지 없이 즉시")만 유지. 프롬프트 환각 방지 룰도 동일 수정.

### 표준 임대차 정형 조항(중개보수·계약금 배액·서면 최고 등)을 LLM이 medium으로 over-flag
→ `rule_filter.py`의 `_LEASE_LAW_VERBATIM_PATTERNS`에 정형 패턴 추가:
  - 민법 제640조 (2기 차임 연체 해지)
  - 민법 제565조 (계약금 배액 상환·포기)
  - 주임법 제6조의2 (해지 통지 3개월)
  - 공인중개사법 (확인설명서 교부, 중개보수 쌍방 지급)
  - 민법 제628조 (보증금 정산 후 반환)
  - 민법 제390조 (서면 최고 후 해제·손해배상)

→ `contract_types.py` lease 프롬프트 safe 기준에 위 정형 표현 명시.

정규식은 `[^\n]` 사용 (마침표 허용 — 한 조항 본문에 마침표 있을 수 있음).

### 룰 기반 high 매칭 시 quote 누락 → 형광펜 안 됨
→ `check_high_rule()` 4-튜플로 변경 `(is_high, risk_type, reason, quote)`. 매칭된 substring을 quote로 사용.

### 사전 룰 매칭된 조항은 retrieve 안 했음 → references_detail 비어있음
→ chain.py에서 모든 조항에 retrieve 먼저 실행, per_clause_refs 채움. LLM 호출 시 사전 fetch한 refs를 references 매개변수로 전달 (중복 호출 방지).

## 7. 주요 설정값

`.env`:
- `RETRIEVAL_TOP_K=8` (기본 5에서 상향 — 다중 항 조항에서 unfair_clause 매칭 보존)
- `OLLAMA_MODEL_NAME=exaone3.5:7.8b`

`backend/app/config.py`:
- `embedding_model: "nlpai-lab/KURE-v1"`
- `reranker_enabled: False` (12GB VRAM에서 EXAONE+bge-m3와 병행 시 GPU swap)

`chain.py`:
- `PER_CLAUSE_TIMEOUT = 120` (이전 90, 프롬프트 길어져서 상향)
- `MAX_RETRIES = 1`, `_LLM_SEMAPHORE = 3`

`contract_types.py` 프롬프트 핵심 룰:
- `★★★ risks[].quote 필드 — 위험 판정 시 절대 누락 금지 ★★★`
- 길이 10~80자, 정확 substring, 의역 금지
- explanation 3단 구조: 조항 인용 → 법률 비교 → 구체적 결과
- `[참고N]` 인용 강제

## 8. 미해결·향후 과제

### LLM 환각 일부 잔존
EXAONE 7.8B는 "정보 부족·미명시"를 위험 근거로 삼는 경향. 프롬프트로 완전히 제거 어려움. 환각 차단 필터로 대부분 잡지만 quote가 채워진 환각은 통과.

### KB 분류기 임계값 0.85/0.88
한국어 임베딩의 의미 매칭 한계로 매우 높게 설정. 거의 활용 안 됨. 진짜 KB 기반 분류는 cross-encoder reranker 또는 fine-tuned 임베딩 필요.

### Multi-domain 검증 데이터 부재
validate.py는 lease 538건만. sales/employment/service/loan 정확도는 측정 안 됨. CLAUDE.md 일반화 원칙에 따라 모든 변경은 다도메인에서 후퇴 없도록 확인 필요.

### 룰 분포 불균형
- lease: 14 high 룰 (풍부)
- service/loan: 4-5 high 룰
- **sales/employment: high 룰 0개** (LLM 의존)
- safe 룰은 모든 도메인 있음

## 9. 파일 위치 빠른 참조

```
backend/app/
├── config.py               # 임베딩·retrieval 설정
├── contract_types.py       # 5도메인 프롬프트 + risk_types
├── models/
│   ├── analysis.py         # ClauseAnalysis, AnalysisResult
│   └── risk.py             # RiskDetail (quote 필드)
├── rag/
│   ├── chain.py            # _classify_by_kb, _retrieve_for_clause, _rule_high_result
│   └── prompts.py          # _REFERENCE_LABEL_GUIDE, format_references[:8]
└── services/
    ├── analysis_service.py # _build_clause_analyses, _validate_quote, _extract_risky_excerpt
    ├── chroma_service.py   # contract_type 필터링
    ├── retrieval_service.py # RRF + stratified, _RISK_SIGNAL_WORDS
    ├── rule_filter.py      # check_safe_rule, check_high_rule (4-tuple)
    └── export_service.py   # _final_clause_text (수정안 우선), _risk_label

frontend/src/
├── pages/ResultPage.jsx    # 모든 핵심 UI 컴포넌트 모여 있음 (1700+ lines)
├── components/
│   ├── RiskBadge.jsx       # B안 라벨
│   └── RiskPieChart.jsx    # 2분류 도넛 + 시계방향 애니메이션
└── styles/global.css       # 디자인 토큰: --primary #1a1a1a, --gold #c5a55a

backend/scripts/
├── build_kb.py             # CLAUSE_FILE_MAPPING, JUDGMENT_KEYWORDS 5도메인
├── validate.py             # 538건 임대차 검증
└── test_real_pdf.py        # 단일 PDF 직접 분석 (디버깅용)
```

## 10. 절대 잊지 말 것 (CLAUDE.md 원칙)

- **일반화 우선**: 특정 PDF·도메인에 과적합 금지. 모든 프롬프트·룰 변경은 5도메인 공통 적용 가능해야 함
- **위험도 그라디언트가 아닌 액션 중심**: 사용자가 "이걸 어떻게 해야 하나" 즉시 알 수 있어야
- **데이터 기반 판단**: explanation에 [참고N] 인용 강제, quote 본문 substring 검증
- **사용자 지적 받은 적 있음**: "임의 룰" 작성 비판 받음. 수동 룰은 보조이고 KB 데이터가 우선

## 11. 다음 세션에서 자주 받을 질문 패턴

- "X PDF에서 N조가 [잘못 판정]됐는데?" → quote 검증, 환각 차단, 룰 매칭 확인
- "이거 너무 위험으로 잡힘 / 너무 안전으로 잡힘" → false-positive/negative 분석, 임계값 또는 패턴 조정
- "디자인 OOO 바꿔줘" → 사이트 톤은 검정+골드 미니멀. 화려한 색상·이모지 지양
- "이거 일반화 가능한가?" → CLAUDE.md 원칙 따라 솔직히 평가. 과적합이면 옵션 제시
