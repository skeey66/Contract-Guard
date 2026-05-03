import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import RiskBadge from "../components/RiskBadge";
import RiskPieChart from "../components/RiskPieChart";
import { buildExportUrl, fetchAnalysis, updateClauseOverride } from "../api/client";

const EXPORT_FORMATS = [
  { key: "docx", label: "DOCX", desc: "MS Word" },
  { key: "pdf", label: "PDF", desc: "인쇄용" },
  { key: "hwpx", label: "HWPX", desc: "한글" },
];

// 헤더 메타 라벨 — contract_type 사용자 친화 표시
const CONTRACT_TYPE_LABELS = {
  lease: "임대차 계약서",
  sales: "매매 계약서",
  employment: "근로 계약서",
  service: "용역·도급 계약서",
  loan: "금전소비대차 계약서",
};

// 텍스트 안의 `**X**` markdown bold 패턴을 형광펜(`<mark>`)으로 변환.
// **수정안(권고 사항)에만** 적용 — LLM이 권고 수정안에서 강조하고 싶은 부분을 `**X**`로 표시.
// 근거자료(법률·약관)의 `**`는 단순 항 번호 강조라서 별개 함수로 제거 처리.
function renderWithMdMarks(text) {
  if (!text) return null;
  const parts = String(text).split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) => {
    const m = p.match(/^\*\*([^*]+)\*\*$/);
    if (m) return <mark key={i} className="clause-highlight">{m[1]}</mark>;
    return <span key={i}>{p}</span>;
  });
}

// 근거자료(KB·법률·약관) 텍스트의 `**X**` markdown 마크를 단순 X로 정리.
// 형광펜 처리하지 않고 평문으로만 표시 — 항 번호 등 구조적 강조라 시각적 의미 없음.
function stripMdMarks(text) {
  if (!text) return "";
  return String(text).replace(/\*\*([^*]+)\*\*/g, "$1");
}

// KB 매칭 사례 전문 보기 모달 — 사이드 패널의 좁은 비교 박스에서 클릭 시 띄움.
// 카테고리·source·유사도·전문(메타 섹션 포함) 모두 표시.
function KbDetailModal({ reference, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  if (!reference) return null;
  const sim = Math.round((reference.similarity || 0) * 100);
  const fullText = reference.text || "";
  return (
    <div className="ref-modal-overlay" onClick={onClose}>
      <div className="ref-modal kb-detail-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ref-modal-header">
          <h2 className="ref-modal-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
              <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
            </svg>
            KB 매칭 사례 전문
          </h2>
          <button type="button" className="ref-modal-close" onClick={onClose} aria-label="닫기">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        <div className="kb-detail-meta">
          <span className="kb-detail-meta-item"><span className="kb-detail-meta-label">출처</span> {reference.source || "unknown"}</span>
          <span className="kb-detail-meta-item"><span className="kb-detail-meta-label">유사도</span> {sim}%</span>
          {reference.article && (
            <span className="kb-detail-meta-item"><span className="kb-detail-meta-label">조문</span> {reference.article}</span>
          )}
        </div>
        <div className="ref-modal-body">
          <div className="kb-detail-text">{stripMdMarks(fullText)}</div>
        </div>
      </div>
    </div>
  );
}

// references_detail의 metadata.source를 4분류로 그룹핑.
// 카테고리별 분류 + 시각적 강도 표시(유사도 막대)로 "어떤 근거가 강한지"를 직관적으로 전달.
const REF_CATEGORIES = [
  { key: "law", label: "법률", icon: "法",
    sources: ["law", "민법", "주택임대차보호법", "근로기준법", "약관규제법/판례",
              "상가건물임대차보호법", "근로자퇴직급여보장법", "최저임금법", "이자제한법",
              "공인중개사법", "민사집행법", "건설산업기본법", "하도급거래공정화에관한법률"] },
  { key: "judgment", label: "판례", icon: "判",
    sources: ["precedent_kr", "aihub_판결문", "판례/실무"] },
  { key: "safe_clause", label: "표준약관", icon: "標",
    sources: ["safe_clause", "실무"] },
  { key: "unfair_clause", label: "불공정약관", icon: "違",
    sources: ["unfair_clause"] },
];

function categorizeReference(ref) {
  const src = (ref?.source || "").trim();
  for (const cat of REF_CATEGORIES) {
    if (cat.sources.includes(src)) return cat.key;
  }
  return "law"; // default
}

function groupReferencesByCategory(references) {
  const grouped = { law: [], judgment: [], safe_clause: [], unfair_clause: [] };
  for (const ref of references || []) {
    const cat = categorizeReference(ref);
    grouped[cat].push(ref);
  }
  // 카테고리 안에서 유사도 내림차순 정렬
  for (const k of Object.keys(grouped)) {
    grouped[k].sort((a, b) => (b.similarity || 0) - (a.similarity || 0));
  }
  return grouped;
}

// 카테고리별 그룹된 참고문헌 패널 + 유사도 막대 시각화.
// "법률·판례·표준약관·불공정약관" 4분류 + 유사도 % 막대로 어떤 근거가 강한지 한눈에.
// 각 항목 클릭 시 KbDetailModal로 전문 보기 가능.
function GroupedReferencesPanel({ references }) {
  const [activeRef, setActiveRef] = useState(null);
  if (!references || references.length === 0) return null;
  const grouped = groupReferencesByCategory(references);

  return (
    <>
      <div className="ref-grouped">
        {REF_CATEGORIES.map((cat) => {
          const items = grouped[cat.key];
          if (!items || items.length === 0) return null;
          return (
            <div key={cat.key} className={`ref-grouped-cat ref-grouped-cat-${cat.key}`}>
              <div className="ref-grouped-header">
                <span className="ref-grouped-icon">{cat.icon}</span>
                <span className="ref-grouped-label">{cat.label}</span>
                <span className="ref-grouped-count">{items.length}건</span>
              </div>
              <ul className="ref-grouped-list">
                {items.map((ref, i) => {
                  const sim = Math.round((ref.similarity || 0) * 100);
                  const text = (ref.text || "").replace(/^\[[^\]]+\]\s*/, "");
                  const preview = text.slice(0, 200);
                  return (
                    <li key={i} className="ref-grouped-item">
                      <button
                        type="button"
                        className="ref-grouped-item-btn"
                        onClick={() => setActiveRef(ref)}
                        title="클릭하여 전문 보기"
                      >
                        <div className="ref-grouped-bar-wrap" title={`유사도 ${sim}%`}>
                          <div className="ref-grouped-bar-track">
                            <div
                              className="ref-grouped-bar"
                              style={{ width: `${Math.max(2, sim)}%` }}
                            />
                          </div>
                          <span className="ref-grouped-pct">{sim}%</span>
                        </div>
                        <p className="ref-grouped-text">
                          {stripMdMarks(preview)}
                          {text.length > 200 ? "…" : ""}
                        </p>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </div>
      {activeRef && (
        <KbDetailModal reference={activeRef} onClose={() => setActiveRef(null)} />
      )}
    </>
  );
}

// KB 매칭 사례에서 본 조항(userQuote)과 가장 유사한 문장을 찾는다.
// 한국어 2-gram 오버랩 기반 단순 스코어링 — 의미적 매칭은 아니지만 어휘 중복 가장 높은 문장을 선택.
// 이렇게 찾은 문장에 형광펜을 칠하면 양쪽에서 같은 패턴이 시각적으로 매칭됨.
function findBestMatchingKbSentence(userQuote, kbRawText) {
  if (!kbRawText) return null;
  const noLabel = kbRawText.replace(/^\[[^\]]+\]\s*/, "");
  // 메타 섹션(판단근거·관련법령) 이후는 매칭 대상에서 제외 — 약관 본문만 사용
  let body = noLabel;
  for (const meta of ["판단근거:", "관련법령:", "관련법령 :"]) {
    const idx = body.indexOf(meta);
    if (idx > 0) body = body.slice(0, idx);
  }
  // 문장 분리 — 마침표·줄바꿈·세미콜론 기준
  const sentences = body
    .split(/[.\n;]/)
    .map((s) => s.trim())
    .filter((s) => s.length >= 12 && s.length <= 280);
  if (sentences.length === 0) return null;
  // userQuote가 없으면 가장 긴 문장 반환 (대표 문장)
  if (!userQuote || userQuote.length < 4) {
    return sentences.reduce((a, b) => (a.length >= b.length ? a : b));
  }
  // 사용자 인용문에서 2-gram 추출
  const userBigrams = new Set();
  const cleanQuote = userQuote.replace(/\s+/g, "");
  for (let i = 0; i < cleanQuote.length - 1; i++) {
    userBigrams.add(cleanQuote.slice(i, i + 2));
  }
  // 각 KB 문장 스코어링
  let best = null;
  let bestScore = 0;
  for (const sent of sentences) {
    const cleanSent = sent.replace(/\s+/g, "");
    let score = 0;
    for (let i = 0; i < cleanSent.length - 1; i++) {
      if (userBigrams.has(cleanSent.slice(i, i + 2))) score++;
    }
    // 매우 짧은 문장의 우연 매칭 방지를 위해 길이로 정규화
    const normalized = score / Math.max(20, cleanSent.length);
    if (normalized > bestScore) {
      bestScore = normalized;
      best = sent;
    }
  }
  // 최소 매칭 임계값 — 너무 약하면 첫 문장(대표)
  if (bestScore < 0.05) return sentences[0];
  return best;
}

// 본 조항 quote ↔ 가장 유사한 KB 매칭 사례를 나란히 보여주는 evidence 패널.
// 좁은 사이드 패널에 맞춘 세로 스택 + 양쪽 형광펜 + 가운데 연결 화살표 구조.
// KB 블록 클릭 시 전문 모달이 열려 메타 섹션·전체 본문을 확인 가능.
function EvidenceComparisonPanel({ analysis }) {
  const [detailOpen, setDetailOpen] = useState(false);
  if (!analysis) return null;
  const refs = analysis.references_detail || [];
  if (refs.length === 0) return null;

  // 위험 판정 시: unfair_clause 중 최고 유사도 / 안전 판정 시: law 또는 safe_clause 중 최고
  const isRisky = analysis.risk_level === "high" || analysis.risk_level === "medium";
  const targetCats = isRisky ? ["unfair_clause"] : ["law", "safe_clause"];
  const candidates = refs.filter((r) => targetCats.includes(categorizeReference(r)));
  if (candidates.length === 0) return null;
  const bestMatch = candidates.reduce(
    (best, r) => (!best || (r.similarity || 0) > (best.similarity || 0) ? r : best),
    null
  );
  if (!bestMatch) return null;

  // 본 조항의 위험 quote
  const risks = analysis.risks || [];
  const quote = risks.find((r) => r.quote)?.quote || "";
  const sim = Math.round((bestMatch.similarity || 0) * 100);

  // KB 사례 본문에서 본 조항 quote와 가장 유사한 문장을 찾아 형광펜 대상으로 사용
  // 단순 첫 문장이 아니라 어휘 매칭이 가장 강한 문장을 골라야 시각적 비교가 의미 있음
  const kbHighlight = findBestMatchingKbSentence(quote, bestMatch.text || "");
  const kbFullNoLabel = (bestMatch.text || "")
    .replace(/^\[[^\]]+\]\s*/, "")
    .split(/(?:판단근거:|관련법령:)/)[0]
    .trim();
  // KB 본문에서 highlight 부분을 분리해 prefix/match/suffix 렌더링
  let kbBefore = "";
  let kbMatch = "";
  let kbAfter = "";
  if (kbHighlight) {
    const idx = kbFullNoLabel.indexOf(kbHighlight);
    if (idx >= 0) {
      kbBefore = kbFullNoLabel.slice(0, idx);
      kbMatch = kbHighlight;
      kbAfter = kbFullNoLabel.slice(idx + kbHighlight.length);
    } else {
      kbMatch = kbFullNoLabel.slice(0, 240);
    }
  } else {
    kbMatch = kbFullNoLabel.slice(0, 240);
  }
  // 매칭 문장 양옆 컨텍스트 길이 제한 — 좁은 패널에 맞게 짧게
  const kbBeforeTrim = kbBefore.length > 50 ? "…" + kbBefore.slice(-50) : kbBefore;
  const kbAfterTrim = kbAfter.length > 80 ? kbAfter.slice(0, 80) + "…" : kbAfter;

  return (
    <>
      <div className={`evidence-compare evidence-compare-${isRisky ? "risk" : "safe"}`}>
        {/* 본 조항 */}
        <div className="evidence-compare-block">
          <div className="evidence-compare-block-header">
            <span className="evidence-compare-label">본 조항 (위험 부분)</span>
          </div>
          <div className="evidence-compare-doc">
            {quote ? (
              <span>
                <mark className="clause-highlight">{stripMdMarks(quote)}</mark>
              </span>
            ) : (
              <span>{stripMdMarks((analysis.clause_content || "").slice(0, 200))}</span>
            )}
          </div>
        </div>

        {/* 가운데 연결 — 매칭 정보 */}
        <div className="evidence-compare-connector">
          <span className="evidence-compare-connector-line" />
          <span className="evidence-compare-connector-info">
            <span className="evidence-compare-sim">{sim}% 유사</span>
            <span className="evidence-compare-tag">
              {isRisky ? "불공정 패턴" : "정형 표현"}
            </span>
          </span>
          <span className="evidence-compare-connector-line" />
        </div>

        {/* KB 매칭 사례 — 클릭 시 전문 모달 */}
        <button
          type="button"
          className="evidence-compare-block evidence-compare-block-clickable"
          onClick={() => setDetailOpen(true)}
          title="클릭하여 전문 보기"
        >
          <div className="evidence-compare-block-header">
            <span className="evidence-compare-label">
              KB 매칭 [{bestMatch.source || "unknown"}]
            </span>
            <span className="evidence-compare-block-action">전문 보기 →</span>
          </div>
          <div className="evidence-compare-doc evidence-compare-doc-kb">
            {kbBeforeTrim && <span>{stripMdMarks(kbBeforeTrim)}</span>}
            {kbMatch && <mark className="clause-highlight">{stripMdMarks(kbMatch)}</mark>}
            {kbAfterTrim && <span>{stripMdMarks(kbAfterTrim)}</span>}
          </div>
        </button>
      </div>
      {detailOpen && (
        <KbDetailModal reference={bestMatch} onClose={() => setDetailOpen(false)} />
      )}
    </>
  );
}

// explanation에서 LLM이 작은따옴표·큰따옴표로 직접 인용한 조항 문구를 추출한다.
// 추출된 문구를 조항 본문(clause_content)에서 찾아 <mark>로 감싸 형광펜 효과를 주기 위한 helper.
// 5자 이상 200자 이하 인용만 허용 (너무 짧으면 일반 단어, 너무 길면 줄바꿈·노이즈 가능).
const _QUOTE_REGEXES = [
  /'([^']{5,200})'/g,
  /‘([^’]{5,200})’/g,
  /"([^"]{5,200})"/g,
  /“([^”]{5,200})”/g,
];

function extractQuotedSnippets(explanation) {
  if (!explanation) return [];
  const set = new Set();
  for (const re of _QUOTE_REGEXES) {
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(explanation)) !== null) {
      const s = m[1].trim();
      if (s.length >= 5) set.add(s);
    }
  }
  return [...set];
}

// 조항 본문에 형광펜 효과로 위험 부분을 강조해 렌더링.
// 우선순위: (1) risks[].quote — LLM이 명시적으로 발췌한 위험 부분 (가장 신뢰)
//         (2) explanation 내 작은따옴표 인용 — 폴백
// 둘 다 본문 정확 substring일 때만 <mark>로 감싸서 false-positive 방지.
function ClauseTextHighlighted({ content, explanation, risks, enabled }) {
  if (!enabled || !content) {
    return <p className="doc-clause-text">{content || ""}</p>;
  }
  // 1차: risks[].quote 사용
  const quoteSet = new Set();
  if (Array.isArray(risks)) {
    for (const r of risks) {
      const q = r && typeof r.quote === "string" ? r.quote.trim() : "";
      if (q.length >= 4) quoteSet.add(q);
    }
  }
  // 2차: explanation에서 작은따옴표 인용 (폴백)
  if (quoteSet.size === 0 && explanation) {
    extractQuotedSnippets(explanation).forEach((s) => quoteSet.add(s));
  }
  const snippets = [...quoteSet];
  if (snippets.length === 0) {
    return <p className="doc-clause-text">{content}</p>;
  }
  // 긴 문구부터 매칭해야 짧은 문구가 긴 문구 안에 흡수되는 중복을 막는다.
  const sorted = [...snippets].sort((a, b) => b.length - a.length);
  const matches = [];
  for (const snippet of sorted) {
    let from = 0;
    while (from < content.length) {
      const idx = content.indexOf(snippet, from);
      if (idx < 0) break;
      const end = idx + snippet.length;
      const overlaps = matches.some((m) => !(end <= m.start || idx >= m.end));
      if (!overlaps) matches.push({ start: idx, end, text: snippet });
      from = end;
    }
  }
  if (matches.length === 0) {
    return <p className="doc-clause-text">{content}</p>;
  }
  matches.sort((a, b) => a.start - b.start);

  const parts = [];
  let cursor = 0;
  matches.forEach((m, i) => {
    if (m.start > cursor) {
      parts.push(<span key={`t${i}`}>{content.slice(cursor, m.start)}</span>);
    }
    parts.push(
      <mark key={`m${i}`} className="clause-highlight" title="LLM이 explanation에서 직접 인용한 부분">
        {m.text}
      </mark>
    );
    cursor = m.end;
  });
  if (cursor < content.length) {
    parts.push(<span key="tail">{content.slice(cursor)}</span>);
  }
  return <p className="doc-clause-text">{parts}</p>;
}

// explanation의 [참고N] 토큰을 클릭 가능한 인용 뱃지로 변환.
// 클릭 시 references_detail[N-1]의 실제 본문을 보여줘 LLM 인용과 RAG 자료를 직접 대조 가능하게 한다.
// (LLM 환각으로 조문번호 등이 변형되는 경우를 사용자가 즉시 검증할 수 있게 하는 신뢰성 장치)
function ExplanationWithCitations({ explanation, references }) {
  const [activeIdx, setActiveIdx] = useState(null);
  if (!explanation) return null;
  const refs = references || [];
  const parts = explanation.split(/(\[참고\d+\])/g);
  return (
    <>
      <p className="ref-explanation">
        {parts.map((part, i) => {
          const match = part.match(/^\[참고(\d+)\]$/);
          if (!match) return part;
          const refIdx = parseInt(match[1], 10) - 1;
          const ref = refs[refIdx];
          if (!ref) {
            return <span key={i} className="citation-missing">{part}</span>;
          }
          const isActive = activeIdx === refIdx;
          return (
            <button
              key={i}
              type="button"
              className={`citation-badge${isActive ? " citation-badge-active" : ""}`}
              onClick={() => setActiveIdx(isActive ? null : refIdx)}
              title="클릭하여 실제 참고 자료 확인"
            >
              {part}
            </button>
          );
        })}
      </p>
      {activeIdx !== null && refs[activeIdx] && (
        <div className="citation-popup">
          <div className="citation-popup-header">
            <span className="citation-popup-num">[참고{activeIdx + 1}]</span>
            <span className="citation-popup-source">
              {refs[activeIdx].source || "unknown"}
              {refs[activeIdx].similarity != null
                ? ` · 유사도 ${refs[activeIdx].similarity.toFixed(2)}`
                : ""}
            </span>
            <button
              type="button"
              className="citation-popup-close"
              onClick={() => setActiveIdx(null)}
              aria-label="닫기"
            >
              ×
            </button>
          </div>
          <div className="citation-popup-body">{stripMdMarks(refs[activeIdx].text)}</div>
        </div>
      )}
    </>
  );
}

function ExportPanel({ analysisId }) {
  if (!analysisId) return null;
  const handleDownload = (fmt) => {
    const url = buildExportUrl(analysisId, fmt);
    const a = document.createElement("a");
    a.href = url;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
  };
  return (
    <div className="export-panel">
      <div className="export-panel-label">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
        권고 수정안 반영 계약서 다운로드
      </div>
      <div className="export-panel-buttons">
        {EXPORT_FORMATS.map((f) => (
          <button
            key={f.key}
            type="button"
            className="export-btn"
            onClick={() => handleDownload(f.key)}
          >
            <span className="export-btn-fmt">{f.label}</span>
            <span className="export-btn-desc">{f.desc}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

// LLM이 생성한 종합 요약을 `■ 라벨` 단락 단위로 분할하여 렌더링.
// LLM이 라벨을 누락한 경우 단순 텍스트로 폴백.
function SummaryRenderer({ text }) {
  if (!text) {
    return <p className="dash-summary-text">분석된 조항을 종합한 요약입니다.</p>;
  }

  const sections = parseSummarySections(text);
  if (sections.length === 0) {
    return <p className="dash-summary-text">{text}</p>;
  }

  return (
    <div className="dash-summary">
      {sections.map((sec, i) => (
        <div
          key={i}
          className={`dash-summary-section ${sec.label === "분석 통계" ? "dash-summary-stats" : ""}`}
        >
          {sec.label && <h4 className="dash-summary-label">{sec.label}</h4>}
          {/* LLM이 종합 요약·권고사항에서 강조한 부분(`**X**`)은 형광펜으로 표시 */}
          <p className="dash-summary-body">{renderWithMdMarks(sec.body)}</p>
        </div>
      ))}
    </div>
  );
}

// `■ 라벨\n본문` 패턴을 파싱. 라벨 없는 단락은 첫 섹션에 본문만 들어감.
function parseSummarySections(text) {
  const lines = text.split("\n");
  const sections = [];
  let current = null;

  for (const line of lines) {
    const labelMatch = line.match(/^\s*■\s*(.+?)\s*$/);
    if (labelMatch) {
      if (current) sections.push(current);
      current = { label: labelMatch[1], body: "" };
    } else if (current) {
      current.body += (current.body ? "\n" : "") + line;
    } else if (line.trim()) {
      // 라벨 없이 본문이 먼저 나오는 경우 — 라벨 없는 첫 섹션
      if (sections.length === 0 || sections[sections.length - 1].label) {
        sections.push({ label: null, body: line });
      } else {
        sections[sections.length - 1].body += "\n" + line;
      }
    }
  }
  if (current) sections.push(current);

  return sections
    .map((s) => ({ ...s, body: s.body.trim() }))
    .filter((s) => s.body);
}

// 종합 요약 + 위험도 원그래프 + 카테고리 카운트 — 대시보드 헤드.
// KPI 카드 한 줄 — 대시보드 첫인상의 핵심.
// 큰 숫자 + 작은 라벨 + 미세한 컨텍스트로 5초 안에 핵심 파악 가능.
function KpiCardsRow({ result, counts, totalRefs }) {
  const total = result.clause_analyses.length;
  const risky = counts.high + counts.medium + counts.low;
  const riskRate = total > 0 ? Math.round((risky / total) * 100) : 0;
  const userOverrides = result.clause_analyses.filter((c) => c.user_override).length;
  return (
    <div className="kpi-row">
      <div className="kpi-card">
        <div className="kpi-num">{total}</div>
        <div className="kpi-label">전체 조항</div>
        <div className="kpi-sub">분석 완료</div>
      </div>
      <div className="kpi-card kpi-card-warn">
        <div className="kpi-num">{risky}</div>
        <div className="kpi-label">위험 조항</div>
        <div className="kpi-sub">법률 위반·계약자 불리</div>
      </div>
      <div className="kpi-card">
        <div className="kpi-num">{riskRate}<span className="kpi-num-unit">%</span></div>
        <div className="kpi-label">위험 비율</div>
        <div className="kpi-sub">전체 대비</div>
      </div>
      <div className="kpi-card">
        <div className="kpi-num">{totalRefs}</div>
        <div className="kpi-label">근거 자료</div>
        <div className="kpi-sub">법률·판례·약관</div>
      </div>
      <div className="kpi-card kpi-card-success">
        <div className="kpi-num">{userOverrides}</div>
        <div className="kpi-label">수정안 적용</div>
        <div className="kpi-sub">사용자 편집</div>
      </div>
    </div>
  );
}

// 위험 분포 히트맵 — 조항 번호별로 색상 박스. 한 줄로 전체 위험 분포 시각화.
// 클릭 시 해당 조항으로 점프. 조항 위에 hover 시 제목 툴팁.
function RiskHeatmapBar({ clauseAnalyses, onScrollToClause }) {
  if (!clauseAnalyses || clauseAnalyses.length === 0) return null;
  const sorted = [...clauseAnalyses].sort((a, b) => a.clause_index - b.clause_index);
  return (
    <div className="risk-heatmap">
      <div className="risk-heatmap-label">위험 분포 맵</div>
      <div className="risk-heatmap-bar">
        {sorted.map((c) => (
          <button
            key={c.clause_index}
            type="button"
            className={`risk-heatmap-cell risk-heatmap-cell-${c.risk_level}`}
            onClick={() => onScrollToClause(c.clause_index)}
            title={`제${c.clause_index}조 ${c.clause_title}`}
          >
            <span className="risk-heatmap-num">{c.clause_index}</span>
          </button>
        ))}
      </div>
      <div className="risk-heatmap-legend">
        <span className="risk-heatmap-legend-item"><span className="risk-heatmap-dot risk-heatmap-cell-high" />법률 위반</span>
        <span className="risk-heatmap-legend-item"><span className="risk-heatmap-dot risk-heatmap-cell-medium" />계약자 불리</span>
        <span className="risk-heatmap-legend-item"><span className="risk-heatmap-dot risk-heatmap-cell-low" />검토 권장</span>
        <span className="risk-heatmap-legend-item"><span className="risk-heatmap-dot risk-heatmap-cell-safe" />안전</span>
      </div>
    </div>
  );
}

// 위험 유형 Top 3 카드 — 가장 자주 나타나는 risk_type 분포.
function RiskTypeBreakdown({ clauseAnalyses }) {
  const typeCount = useMemo(() => {
    const m = new Map();
    for (const ca of clauseAnalyses) {
      if (ca.risk_level === "safe") continue;
      for (const r of ca.risks || []) {
        const t = (r.risk_type || "기타").trim();
        m.set(t, (m.get(t) || 0) + 1);
      }
    }
    return [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3);
  }, [clauseAnalyses]);
  if (typeCount.length === 0) return null;
  return (
    <div className="risk-type-breakdown">
      <div className="risk-type-label">자주 나타난 위험 유형</div>
      <div className="risk-type-cards">
        {typeCount.map(([type, count]) => (
          <div key={type} className="risk-type-card">
            <span className="risk-type-name">{type.replace(/_/g, " ")}</span>
            <span className="risk-type-count">{count}건</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function OverviewDashboard({ result, counts, aggregated, onScrollToClause, onOpenRefs }) {
  const refStats = {
    law: aggregated.law.length,
    judgment: aggregated.judgment.length,
    clause: aggregated.clause.length,
  };
  // 핵심 위험 조항 상위 3개 (high → medium 순)
  const topRisky = useMemo(() => {
    const order = { high: 0, medium: 1, low: 2, safe: 3 };
    return [...result.clause_analyses]
      .filter((c) => c.risk_level === "high" || c.risk_level === "medium")
      .sort((a, b) => (order[a.risk_level] - order[b.risk_level]) || (b.confidence - a.confidence))
      .slice(0, 3);
  }, [result.clause_analyses]);

  return (
    <section className="dashboard-section">
      <h2 className="dashboard-section-title">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="3" y="3" width="7" height="9" />
          <rect x="14" y="3" width="7" height="5" />
          <rect x="14" y="12" width="7" height="9" />
          <rect x="3" y="16" width="7" height="5" />
        </svg>
        분석 대시보드
      </h2>

      <div className="dashboard-grid">
        {/* 종합 요약 */}
        <div className="dash-card dash-card-summary">
          <div className="dash-card-header">
            <span className="dash-card-icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="16" x2="12" y2="12" />
                <line x1="12" y1="8" x2="12.01" y2="8" />
              </svg>
            </span>
            <h3>종합 요약</h3>
          </div>
          <SummaryRenderer text={result.summary} />

          {topRisky.length > 0 && (
            <div className="dash-top-risky">
              <h4>주의 깊게 살펴볼 조항</h4>
              <ul>
                {topRisky.map((c) => (
                  <li key={c.clause_index}>
                    <button
                      type="button"
                      className="dash-top-risky-link"
                      onClick={() => onScrollToClause(c.clause_index)}
                    >
                      <RiskBadge level={c.risk_level} />
                      <span className="dash-risky-title">제{c.clause_index}조 {c.clause_title}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* 위험도 원그래프 + 조항별 히트맵 (정보 보완 관계로 같은 카드에 통합) */}
        <div className="dash-card dash-card-chart">
          <div className="dash-card-header">
            <span className="dash-card-icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21.21 15.89A10 10 0 1 1 8 2.83" />
                <path d="M22 12A10 10 0 0 0 12 2v10z" />
              </svg>
            </span>
            <h3>위험도 분포</h3>
          </div>
          <RiskPieChart counts={counts} />
          {/* 도넛 아래 — 히트맵 + 위험 유형 Top3 (좁은 카드라 세로 stack) */}
          <RiskHeatmapBar
            clauseAnalyses={result.clause_analyses}
            onScrollToClause={onScrollToClause}
          />
          <RiskTypeBreakdown clauseAnalyses={result.clause_analyses} />
        </div>

        {/* 참고자료 카운트 */}
        <div className="dash-card dash-card-refs">
          <div className="dash-card-header">
            <span className="dash-card-icon">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
              </svg>
            </span>
            <h3>참고 자료</h3>
          </div>
          <div className="dash-ref-stats">
            <div className="dash-ref-stat">
              <span className="dash-ref-num">{refStats.law}</span>
              <span className="dash-ref-label">법률·시행령</span>
            </div>
            <div className="dash-ref-stat">
              <span className="dash-ref-num">{refStats.judgment}</span>
              <span className="dash-ref-label">판례</span>
            </div>
            <div className="dash-ref-stat">
              <span className="dash-ref-num">{refStats.clause}</span>
              <span className="dash-ref-label">표준약관·실무</span>
            </div>
          </div>
          <p className="dash-ref-note">
            전체 {refStats.law + refStats.judgment + refStats.clause}건의 자료를 근거로 분석했습니다.
          </p>
          <button
            type="button"
            className="dash-ref-view-all"
            onClick={onOpenRefs}
            disabled={refStats.law + refStats.judgment + refStats.clause === 0}
          >
            전체 자료 보기
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </button>
        </div>
      </div>
    </section>
  );
}

const REF_CATEGORY_TABS = [
  { key: "law", label: "법률·시행령" },
  { key: "judgment", label: "판례" },
  { key: "clause", label: "표준약관·실무" },
];

// 모든 조항의 references_detail을 카테고리별로 합치고 텍스트 기준 중복 제거.
// 동일 자료가 여러 조항에서 인용되면 가장 높은 유사도로 기록하고 인용 조항 목록을 모은다.
function aggregateReferences(clauseAnalyses) {
  const buckets = { law: new Map(), judgment: new Map(), clause: new Map() };
  for (const ca of clauseAnalyses) {
    const refs = ca.references_detail || [];
    for (const ref of refs) {
      const cat = ref.category || "law";
      const bucket = buckets[cat] || buckets.law;
      const key = (ref.text || "").trim().slice(0, 200);
      if (!key) continue;
      const existing = bucket.get(key);
      if (existing) {
        existing.similarity = Math.max(existing.similarity, ref.similarity || 0);
        if (!existing.cited_by.includes(ca.clause_index)) {
          existing.cited_by.push(ca.clause_index);
        }
      } else {
        bucket.set(key, {
          text: ref.text,
          source: ref.source,
          article: ref.article,
          similarity: ref.similarity || 0,
          cited_by: [ca.clause_index],
        });
      }
    }
  }
  const sortBucket = (m) =>
    [...m.values()].sort((a, b) => b.similarity - a.similarity);
  return {
    law: sortBucket(buckets.law),
    judgment: sortBucket(buckets.judgment),
    clause: sortBucket(buckets.clause),
  };
}

// 전체 참고 자료 모달 — 카테고리 탭으로 분류된 자료를 한 번에 열람.
function ReferencesModal({ aggregated, onClose, onScrollToClause }) {
  const initialTab = aggregated.law.length > 0
    ? "law"
    : aggregated.judgment.length > 0
      ? "judgment"
      : aggregated.clause.length > 0
        ? "clause"
        : "law";
  const [activeTab, setActiveTab] = useState(initialTab);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const totalAll = aggregated.law.length + aggregated.judgment.length + aggregated.clause.length;
  const items = aggregated[activeTab] || [];

  const handleCitedClick = (idx) => {
    onScrollToClause(idx);
    onClose();
  };

  return (
    <div className="ref-modal-overlay" onClick={onClose}>
      <div className="ref-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ref-modal-header">
          <h2 className="ref-modal-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
              <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
            </svg>
            분석에 사용된 참고 자료 ({totalAll}건)
          </h2>
          <button type="button" className="ref-modal-close" onClick={onClose} aria-label="닫기">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div className="ref-modal-tabs">
          {REF_CATEGORY_TABS.map((tab) => {
            const count = aggregated[tab.key]?.length || 0;
            const isActive = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                type="button"
                className={`agg-tab ${isActive ? "agg-tab-active" : ""}`}
                onClick={() => setActiveTab(tab.key)}
                disabled={count === 0}
              >
                {tab.label}
                <span className="agg-tab-count">{count}</span>
              </button>
            );
          })}
        </div>

        <div className="ref-modal-body">
          {items.length === 0 ? (
            <p className="agg-refs-empty">이 카테고리에 해당하는 자료가 없습니다.</p>
          ) : (
            <ul className="agg-refs-list">
              {items.map((item, i) => (
                <RefItem key={i} item={item} onCitedClick={handleCitedClick} />
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

// 참고자료 텍스트의 선두 카테고리 태그(`[판례]`, `[판결문]`, `[약관-불리]`, `[법률]`)를 추출.
function extractRefTag(text) {
  const m = text.match(/^\s*\[([^\]]{1,12})\]\s*/);
  if (m) return { tag: m[1], rest: text.slice(m[0].length) };
  return { tag: null, rest: text };
}

// 본문에서 알려진 섹션 헤더(`판시사항:`, `판결요지:`, `참조조문:`, `기초사실:`,
// `판단근거:`, `관련법령:`)를 인식해 단락으로 분할.
const REF_SECTION_HEADERS = [
  "판시사항", "판결요지", "참조조문", "참조판례",
  "기초사실", "사실관계", "판결주문", "이유",
  "판단근거", "관련법령", "관련 조문", "조문내용",
];

function splitRefSections(text) {
  const sections = [];
  // 섹션 헤더 패턴: "헤더명:" 또는 "헤더명 :" — 줄 시작 또는 콜론 앞에서 매칭
  const headerPattern = new RegExp(
    `(?:^|\\n)\\s*(${REF_SECTION_HEADERS.join("|")})\\s*[:：]`,
    "g",
  );
  const matches = [...text.matchAll(headerPattern)];

  if (matches.length === 0) {
    return [{ label: null, body: text.trim() }];
  }

  // 첫 매치 이전 텍스트는 라벨 없는 도입부
  const firstStart = matches[0].index + (matches[0][0].startsWith("\n") ? 1 : 0);
  const intro = text.slice(0, firstStart).trim();
  if (intro) sections.push({ label: null, body: intro });

  for (let i = 0; i < matches.length; i++) {
    const m = matches[i];
    const labelStart = m.index + (m[0].startsWith("\n") ? 1 : 0);
    const bodyStart = m.index + m[0].length;
    const bodyEnd = i + 1 < matches.length ? matches[i + 1].index : text.length;
    const body = text.slice(bodyStart, bodyEnd).trim();
    if (body) sections.push({ label: m[1], body });
  }

  return sections;
}

// `**굵게**` 마크다운 표시를 React 노드로 변환.
function renderInlineBold(text) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    const m = part.match(/^\*\*(.+)\*\*$/);
    return m ? <strong key={i}>{m[1]}</strong> : <span key={i}>{part}</span>;
  });
}

// 참고자료 항목 — 클릭 시 전체 본문 펼치기/접기.
// 본문은 카테고리 태그·섹션 헤더를 인식해 가독성 있게 재구성.
function RefItem({ item, onCitedClick }) {
  const [expanded, setExpanded] = useState(false);
  // similarity 필드는 벡터(0~1)·BM25 정규화(0~0.92) 혼재. 레거시 데이터 보호를 위해 클램프.
  const simPct = Math.round(Math.max(0, Math.min(1, item.similarity || 0)) * 100);

  const rawText = item.text || "";
  const { tag, rest } = extractRefTag(rawText);
  const sections = splitRefSections(rest);
  const isLong = rest.length > 280;
  const previewBody = !expanded && isLong ? rest.slice(0, 280).trim() + "…" : null;

  return (
    <li className={`agg-refs-item ${expanded ? "agg-refs-item-expanded" : ""}`}>
      <button
        type="button"
        className="agg-refs-item-toggle"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <div className="agg-refs-item-head">
          <span className="agg-refs-source">
            {tag && <span className={`agg-refs-tag agg-refs-tag-${item.category || "law"}`}>{tag}</span>}
            <span className="agg-refs-source-name">
              {item.source}
              {item.article ? <span className="agg-refs-article"> · {item.article}</span> : null}
            </span>
          </span>
          <span className="agg-refs-meta">
            <span className="agg-refs-sim">유사도 {simPct}%</span>
            {isLong && (
              <span className="agg-refs-expand-icon" aria-hidden="true">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                  <polyline points={expanded ? "18 15 12 9 6 15" : "6 9 12 15 18 9"} />
                </svg>
              </span>
            )}
          </span>
        </div>

        {previewBody !== null ? (
          <p className="agg-refs-text">{renderInlineBold(previewBody)}</p>
        ) : (
          <div className="agg-refs-body">
            {sections.map((sec, i) => (
              <div key={i} className="agg-refs-sec">
                {sec.label && <h5 className="agg-refs-sec-label">{sec.label}</h5>}
                <p className="agg-refs-sec-body">{renderInlineBold(sec.body)}</p>
              </div>
            ))}
          </div>
        )}
      </button>
      <div className="agg-refs-cited">
        <span className="agg-refs-cited-label">인용된 조항:</span>
        {item.cited_by.map((idx) => (
          <button
            key={idx}
            type="button"
            className="agg-refs-cited-btn"
            onClick={() => onCitedClick(idx)}
          >
            제{idx}조
          </button>
        ))}
      </div>
    </li>
  );
}

// 권고안 편집 — 가운데 정렬 모달 + 슬라이드 인 애니메이션 (ref-modal 패턴 재사용).
// 인라인 편집은 좁아서 큰 textarea + 원문 비교 UX 어려우므로 별도 모달로 분리.
function RewriteEditDrawer({ analysisId, analysis, onClose, onSaved }) {
  const initialDraft = analysis.user_override ?? analysis.suggested_rewrite ?? "";
  const [draft, setDraft] = useState(initialDraft);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const orig = analysis.clause_content || "";

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const handleSave = async () => {
    if (!analysisId) return;
    const trimmed = (draft || "").trim();
    if (!trimmed) {
      setError("수정안 내용을 입력해주세요.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await updateClauseOverride(analysisId, analysis.clause_index, trimmed);
      onSaved(updated);
    } catch (e) {
      setError(e.response?.data?.detail || e.message || "저장 실패");
      setSaving(false);
    }
  };

  const charCount = (draft || "").length;
  const lineCount = (draft || "").split("\n").length;
  const diff = charCount - orig.length;

  return (
    <div className="ref-modal-overlay" onClick={onClose}>
      <div className="ref-modal rewrite-edit-modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="권고안 편집">
        <header className="ref-modal-header">
          <div className="rewrite-drawer-title">
            <span className="rewrite-drawer-eyebrow">권고안 편집</span>
            <h3 className="rewrite-drawer-clause">제{analysis.clause_index}조 {analysis.clause_title}</h3>
          </div>
          <button
            type="button"
            className="ref-modal-close"
            onClick={onClose}
            aria-label="닫기"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </header>
        <div className="ref-modal-body rewrite-edit-modal-body">
          <section className="rewrite-drawer-section">
            <h4 className="rewrite-drawer-section-label">원문 ({orig.length}자)</h4>
            <pre className="rewrite-drawer-orig">{orig}</pre>
          </section>
          <section className="rewrite-drawer-section">
            <h4 className="rewrite-drawer-section-label">수정안</h4>
            <textarea
              className="rewrite-drawer-textarea"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="수정안을 입력하세요"
              disabled={saving}
              autoFocus
            />
            <div className="rewrite-drawer-meta">
              <span>{charCount}자 · {lineCount}줄</span>
              {orig && (
                <span className={diff < 0 ? "rewrite-meta-shorter" : "rewrite-meta-longer"}>
                  원문 대비 {diff > 0 ? "+" : ""}{diff}자
                </span>
              )}
            </div>
          </section>
          {error && <p className="rewrite-drawer-error">{error}</p>}
        </div>
        <footer className="rewrite-edit-modal-footer">
          <button
            type="button"
            className="rewrite-btn"
            onClick={onClose}
            disabled={saving}
          >
            취소
          </button>
          <button
            type="button"
            className="rewrite-btn rewrite-btn-primary"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? "저장 중…" : "저장"}
          </button>
        </footer>
      </div>
    </div>
  );
}

function RewriteEditor({ analysisId, analysis, onUpdated }) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [showOriginal, setShowOriginal] = useState(false);

  useEffect(() => {
    setDrawerOpen(false);
    setError(null);
    setShowOriginal(false);
  }, [analysis.clause_index, analysis.user_override, analysis.suggested_rewrite]);

  const isUserModified = !!analysis.user_override;
  const hasSuggestion = !!analysis.suggested_rewrite;

  const handleRevert = async () => {
    if (!analysisId) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await updateClauseOverride(analysisId, analysis.clause_index, null);
      onUpdated(updated);
    } catch (e) {
      setError(e.response?.data?.detail || e.message || "되돌리기 실패");
    } finally {
      setSaving(false);
    }
  };

  const handleSaved = (updated) => {
    onUpdated(updated);
    setDrawerOpen(false);
  };

  const displayText = analysis.user_override ?? analysis.suggested_rewrite ?? "";
  if (!displayText) {
    return (
      <>
        <div className="ref-rewrite-empty">
          <p>AI가 수정안을 생성하지 못했습니다. 직접 작성하실 수 있습니다.</p>
          <button
            type="button"
            className="rewrite-edit-btn"
            onClick={() => setDrawerOpen(true)}
          >
            ✎ 수정안 직접 작성
          </button>
        </div>
        {drawerOpen && (
          <RewriteEditDrawer
            analysisId={analysisId}
            analysis={analysis}
            onClose={() => setDrawerOpen(false)}
            onSaved={handleSaved}
          />
        )}
      </>
    );
  }

  const orig = analysis.clause_content || "";
  return (
    <div className="ref-rewrite">
      <div className="rewrite-header-row">
        {isUserModified ? (
          <span className="rewrite-source-badge rewrite-source-user">
            사용자 직접 수정
            {analysis.user_override_at && (
              <span className="rewrite-source-time"> · {new Date(analysis.user_override_at).toLocaleString("ko-KR")}</span>
            )}
          </span>
        ) : (
          <span className="rewrite-source-badge rewrite-source-ai">
            AI 권고안 (RAG 근거 기반)
          </span>
        )}
        <button
          type="button"
          className="rewrite-toggle-original"
          onClick={() => setShowOriginal((v) => !v)}
          title={showOriginal ? "원문 숨기기" : "원문과 비교"}
        >
          {showOriginal ? "원문 숨기기" : "원문 비교"}
        </button>
      </div>

      {showOriginal && orig && (
        <div className="rewrite-compare">
          <div className="rewrite-compare-side">
            <span className="rewrite-compare-label">원문 ({orig.length}자)</span>
            <pre className="rewrite-compare-text rewrite-compare-text-orig">{orig}</pre>
          </div>
          <div className="rewrite-compare-arrow">↓</div>
          <div className="rewrite-compare-side">
            <span className="rewrite-compare-label">수정안 ({displayText.length}자, {displayText.length - orig.length > 0 ? "+" : ""}{displayText.length - orig.length})</span>
            <pre className="rewrite-compare-text rewrite-compare-text-new">{stripMdMarks(displayText)}</pre>
          </div>
        </div>
      )}

      {!showOriginal && (
        <pre className="ref-rewrite-text">{stripMdMarks(displayText)}</pre>
      )}

      <p className="ref-rewrite-note">
        {isUserModified
          ? "사용자가 직접 입력한 수정안입니다. 다운로드 파일에 반영됩니다."
          : "표준약관·관련 법률을 근거로 한 AI 생성 수정안입니다. 실제 적용 전 검토가 필요합니다."}
      </p>
      {error && <p className="rewrite-editor-error">{error}</p>}
      <div className="rewrite-editor-actions">
        <button
          type="button"
          className="rewrite-btn rewrite-btn-primary"
          onClick={() => setDrawerOpen(true)}
        >
          {isUserModified ? "✎ 수정" : (hasSuggestion ? "✎ 권고안 편집" : "✎ 수정안 작성")}
        </button>
        {isUserModified && (
          <button
            type="button"
            className="rewrite-btn rewrite-btn-revert"
            onClick={handleRevert}
            disabled={saving}
          >
            {hasSuggestion ? "권고안으로 되돌리기" : "수정 취소"}
          </button>
        )}
      </div>
      {drawerOpen && (
        <RewriteEditDrawer
          analysisId={analysisId}
          analysis={analysis}
          onClose={() => setDrawerOpen(false)}
          onSaved={handleSaved}
        />
      )}
    </div>
  );
}

function ReferencePanel({ analysisId, analysis, onAnalysisUpdated }) {
  if (!analysis) {
    return (
      <div className="ref-panel ref-panel-empty">
        <div className="ref-panel-empty-inner">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" opacity="0.25">
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
          </svg>
          <p>조항을 선택하면 관련 판례와 법률을 확인할 수 있습니다</p>
        </div>
      </div>
    );
  }

  const hasRisks = analysis.risks.length > 0;
  const hasRefs = analysis.similar_references.length > 0;
  const isRisky = analysis.risk_level === "high" || analysis.risk_level === "medium";

  return (
    <div className="ref-panel">
      <div className="ref-panel-header">
        <div className="ref-panel-header-top">
          <RiskBadge level={analysis.risk_level} />
          <span className="ref-panel-conf">
            신뢰도 {Math.round(analysis.confidence * 100)}%
          </span>
        </div>
        <h2 className="ref-panel-title">{analysis.clause_title}</h2>
      </div>

      <div className="ref-panel-body">
        {/* 본 조항 ↔ KB 사례 시각적 비교 — 판단 근거를 가장 직접적으로 시각화 */}
        <EvidenceComparisonPanel analysis={analysis} />

        {analysis.explanation && (
          <section className="ref-section">
            <h3 className="ref-section-label">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="16" x2="12" y2="12" />
                <line x1="12" y1="8" x2="12.01" y2="8" />
              </svg>
              분석 요약
            </h3>
            <ExplanationWithCitations
              explanation={analysis.explanation}
              references={analysis.references_detail}
            />
          </section>
        )}

        {isRisky && (
          <section className="ref-section">
            <h3 className="ref-section-label ref-label-rewrite">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 20h9" />
                <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
              </svg>
              수정안
            </h3>
            <RewriteEditor
              analysisId={analysisId}
              analysis={analysis}
              onUpdated={onAnalysisUpdated}
            />
          </section>
        )}

        {hasRisks && (
          <section className="ref-section">
            <h3 className="ref-section-label ref-label-risk">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
              위험 요소 ({analysis.risks.length})
            </h3>
            <div className="ref-risks">
              {analysis.risks.map((risk, i) => (
                <div key={i} className="ref-risk-item">
                  <span className="ref-risk-type">{risk.risk_type}</span>
                  <p className="ref-risk-desc">{risk.description}</p>
                  {risk.suggestion && (
                    <div className="ref-risk-suggest">
                      <span className="ref-suggest-tag">개선 제안</span>
                      <p>{risk.suggestion}</p>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {hasRefs && (
          <section className="ref-section">
            <h3 className="ref-section-label ref-label-law">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
              </svg>
              근거 자료 ({(analysis.references_detail || []).length}건, 카테고리별)
            </h3>
            <GroupedReferencesPanel references={analysis.references_detail} />
          </section>
        )}

        {!hasRisks && !hasRefs && analysis.risk_level === "safe" && (
          <div className="ref-safe-msg">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--risk-safe)" strokeWidth="2">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
              <polyline points="22 4 12 14.01 9 11.01" />
            </svg>
            <p>이 조항은 안전한 것으로 분석되었습니다.</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default function ResultPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { analysisId: routeAnalysisId } = useParams();
  const [result, setResult] = useState(location.state?.result || null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [selectedIdx, setSelectedIdx] = useState(null);
  const [refsModalOpen, setRefsModalOpen] = useState(false);
  const clauseRefs = useRef({});
  const splitLayoutRef = useRef(null);

  useEffect(() => {
    if (!routeAnalysisId) return;

    // URL의 id가 현재 로드된 결과와 같으면 재fetch 불필요
    if (result && result.id === routeAnalysisId) return;

    // 업로드 직후처럼 location.state에 매칭 결과가 프리로드되어 있으면 즉시 반영
    const preloaded = location.state?.result;
    if (preloaded?.id === routeAnalysisId) {
      setResult(preloaded);
      setSelectedIdx(null);
      setLoadError(null);
      return;
    }

    // 서로 다른 분석으로 전환 — 이전 상태를 초기화하고 서버에서 새로 가져온다
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setSelectedIdx(null);
    fetchAnalysis(routeAnalysisId)
      .then((data) => {
        if (cancelled) return;
        if (data?.status === "completed" && data.result) {
          setResult(data.result);
        } else {
          setLoadError(data?.error || "분석 결과를 불러올 수 없습니다.");
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(err.response?.data?.detail || err.message || "분석 결과 조회 실패");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
    // routeAnalysisId가 바뀔 때만 재평가 — result/location.state를 deps에 넣으면 루프 위험이 있다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeAnalysisId]);

  const orderedClauses = useMemo(
    () => (result ? [...result.clause_analyses].sort((a, b) => a.clause_index - b.clause_index) : []),
    [result]
  );

  // "위험 조항만 보기" 필터 — UI/UX 개선안 #4 (위험 조항 빠른 탐색)
  const [showRiskyOnly, setShowRiskyOnly] = useState(false);
  const visibleClauses = useMemo(
    () => (showRiskyOnly ? orderedClauses.filter((a) => a.risk_level !== "safe") : orderedClauses),
    [orderedClauses, showRiskyOnly]
  );

  const counts = useMemo(() => {
    const c = { high: 0, medium: 0, low: 0, safe: 0 };
    orderedClauses.forEach((a) => { c[a.risk_level] = (c[a.risk_level] || 0) + 1; });
    return c;
  }, [orderedClauses]);

  const riskyCount = counts.high + counts.medium + counts.low;
  const totalCount = counts.high + counts.medium + counts.low + counts.safe;
  const avgConfidence = useMemo(() => {
    if (orderedClauses.length === 0) return 0;
    const sum = orderedClauses.reduce((s, a) => s + (a.confidence || 0), 0);
    return Math.round((sum / orderedClauses.length) * 100);
  }, [orderedClauses]);

  const aggregated = useMemo(
    () => (result ? aggregateReferences(result.clause_analyses) : { law: [], judgment: [], clause: [] }),
    [result]
  );

  useEffect(() => {
    if (orderedClauses.length > 0 && selectedIdx === null) {
      const firstRisky = orderedClauses.find((a) => a.risk_level !== "safe");
      if (firstRisky) {
        setSelectedIdx(firstRisky.clause_index);
      }
    }
  }, [orderedClauses, selectedIdx]);

  const handleAnalysisUpdated = useCallback((updatedClause) => {
    setResult((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        clause_analyses: prev.clause_analyses.map((c) =>
          c.clause_index === updatedClause.clause_index ? updatedClause : c
        ),
      };
    });
  }, []);

  // 대시보드/참고자료 패널에서 특정 조항으로 이동 — 선택 + 좌측 뷰어 스크롤
  const scrollToClause = useCallback((clauseIndex) => {
    setSelectedIdx(clauseIndex);
    const el = clauseRefs.current[clauseIndex];
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    } else if (splitLayoutRef.current) {
      splitLayoutRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, []);

  if (loading) {
    return (
      <div className="result-page">
        <div className="no-result">
          <div className="loading-bar"><div className="loading-bar-fill" /></div>
          <p>분석 결과를 불러오는 중...</p>
        </div>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="result-page">
        <div className="no-result">
          <div className="no-result-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
          </div>
          <h3>{loadError ? "분석 결과를 불러올 수 없습니다" : "분석 결과가 없습니다"}</h3>
          <p>{loadError || "계약서를 먼저 업로드해주세요."}</p>
          <button onClick={() => navigate("/")}>계약서 분석하기</button>
        </div>
      </div>
    );
  }

  const selectedAnalysis = selectedIdx !== null
    ? result.clause_analyses.find((a) => a.clause_index === selectedIdx)
    : null;

  const handleClauseClick = (clauseIndex) => {
    setSelectedIdx(clauseIndex);
  };

  return (
    <div className="result-page result-page-split">
      {/* UI/UX 개선안 #1 — 상단 헤더 강화: 메타데이터 + 위험도 카운트 + 액션 버튼 */}
      <div className="result-top-bar result-top-bar-v2">
        <div className="result-top-back">
          <button className="back-button" onClick={() => navigate("/")}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="15 18 9 12 15 6" />
            </svg>
            새 분석
          </button>
        </div>
        <div className="result-top-meta">
          <h2 className="result-filename">{result.filename}</h2>
          <div className="result-meta-line">
            <span className="result-meta-item">
              {CONTRACT_TYPE_LABELS[result.contract_type] || "계약서"} ·
            </span>
            <span className="result-meta-item">{totalCount}개 조항 분석 완료 ·</span>
            <span className="result-meta-item">평균 신뢰도 {avgConfidence}%</span>
          </div>
          <div className="result-meta-badges">
            {counts.high > 0 && <span className="result-meta-badge meta-badge-high">법률 위반 {counts.high}건</span>}
            {counts.medium > 0 && <span className="result-meta-badge meta-badge-medium">계약자 불리 {counts.medium}건</span>}
            {counts.low > 0 && <span className="result-meta-badge meta-badge-low">검토 권장 {counts.low}건</span>}
            <span className="result-meta-badge meta-badge-safe">안전 {counts.safe}건</span>
          </div>
        </div>
        <div className="result-top-actions">
          <button
            type="button"
            className={`top-action-btn${showRiskyOnly ? " top-action-btn-active" : ""}`}
            onClick={() => setShowRiskyOnly((v) => !v)}
            title="안전 조항을 숨기고 위험·검토 필요 조항만 표시"
          >
            {showRiskyOnly ? "전체 조항" : `위험 조항만 (${riskyCount})`}
          </button>
        </div>
      </div>

      <OverviewDashboard
        result={result}
        counts={counts}
        aggregated={aggregated}
        onScrollToClause={scrollToClause}
        onOpenRefs={() => setRefsModalOpen(true)}
      />

      {refsModalOpen && (
        <ReferencesModal
          aggregated={aggregated}
          onClose={() => setRefsModalOpen(false)}
          onScrollToClause={scrollToClause}
        />
      )}

      <div className="doc-split-layout" ref={splitLayoutRef}>
        <div className="doc-viewer">
          <div className="doc-viewer-header">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
            <span>계약서 원문</span>
            <span className="doc-viewer-count">
              {showRiskyOnly ? `${visibleClauses.length} / ${orderedClauses.length}개 조항 (필터)` : `${orderedClauses.length}개 조항`}
            </span>
          </div>
          <div className="doc-viewer-body">
            {visibleClauses.map((analysis) => {
              const isSelected = selectedIdx === analysis.clause_index;
              const isRisky = analysis.risk_level !== "safe";
              const isUserEdited = !!analysis.user_override;
              return (
                <div
                  key={analysis.clause_index}
                  ref={(el) => { clauseRefs.current[analysis.clause_index] = el; }}
                  className={[
                    "doc-clause",
                    `doc-clause-${analysis.risk_level}`,
                    isRisky ? "doc-clause-risky" : "",
                    isSelected ? "doc-clause-selected" : "",
                  ].join(" ")}
                  onClick={() => handleClauseClick(analysis.clause_index)}
                >
                  {isRisky && (
                    <div className="doc-clause-marker">
                      <RiskBadge level={analysis.risk_level} />
                      {isUserEdited && (
                        <span className="doc-clause-edited-badge">수정됨</span>
                      )}
                    </div>
                  )}
                  <h4 className="doc-clause-title">{analysis.clause_title}</h4>
                  <ClauseTextHighlighted
                    content={analysis.clause_content}
                    explanation={analysis.explanation}
                    risks={analysis.risks}
                    enabled={isRisky}
                  />
                </div>
              );
            })}
          </div>
        </div>

        <div className="ref-panel-wrap">
          <ReferencePanel
            analysisId={result.id}
            analysis={selectedAnalysis}
            onAnalysisUpdated={handleAnalysisUpdated}
          />
        </div>
      </div>

      <ExportPanel analysisId={result.id} />
    </div>
  );
}
