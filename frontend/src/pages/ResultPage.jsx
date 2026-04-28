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
          <p className="dash-summary-body">{sec.body}</p>
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

        {/* 위험도 원그래프 */}
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

function RewriteEditor({ analysisId, analysis, onUpdated }) {
  const initial = analysis.user_override ?? analysis.suggested_rewrite ?? "";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setEditing(false);
    setDraft(analysis.user_override ?? analysis.suggested_rewrite ?? "");
    setError(null);
  }, [analysis.clause_index, analysis.user_override, analysis.suggested_rewrite]);

  const isUserModified = !!analysis.user_override;
  const hasSuggestion = !!analysis.suggested_rewrite;

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
      onUpdated(updated);
      setEditing(false);
    } catch (e) {
      setError(e.response?.data?.detail || e.message || "저장 실패");
    } finally {
      setSaving(false);
    }
  };

  const handleRevert = async () => {
    if (!analysisId) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await updateClauseOverride(analysisId, analysis.clause_index, null);
      onUpdated(updated);
      setEditing(false);
    } catch (e) {
      setError(e.response?.data?.detail || e.message || "되돌리기 실패");
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setDraft(analysis.user_override ?? analysis.suggested_rewrite ?? "");
    setEditing(false);
    setError(null);
  };

  const displayText = analysis.user_override ?? analysis.suggested_rewrite ?? "";
  if (!displayText && !editing) {
    return (
      <div className="ref-rewrite-empty">
        <p>AI가 수정안을 생성하지 못했습니다. 직접 작성하실 수 있습니다.</p>
        <button
          type="button"
          className="rewrite-edit-btn"
          onClick={() => { setDraft(""); setEditing(true); }}
        >
          수정안 직접 작성
        </button>
      </div>
    );
  }

  if (editing) {
    return (
      <div className="ref-rewrite ref-rewrite-editing">
        <textarea
          className="rewrite-editor-textarea"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={Math.max(6, draft.split("\n").length + 1)}
          placeholder="수정안을 입력하세요"
          disabled={saving}
        />
        {error && <p className="rewrite-editor-error">{error}</p>}
        <div className="rewrite-editor-actions">
          <button type="button" className="rewrite-btn rewrite-btn-primary" onClick={handleSave} disabled={saving}>
            {saving ? "저장 중..." : "저장"}
          </button>
          <button type="button" className="rewrite-btn" onClick={handleCancel} disabled={saving}>
            취소
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="ref-rewrite">
      {isUserModified && (
        <div className="rewrite-source-badge rewrite-source-user">
          사용자 직접 수정
          {analysis.user_override_at && (
            <span className="rewrite-source-time"> · {new Date(analysis.user_override_at).toLocaleString("ko-KR")}</span>
          )}
        </div>
      )}
      <pre className="ref-rewrite-text">{displayText}</pre>
      <p className="ref-rewrite-note">
        {isUserModified
          ? "사용자가 직접 입력한 수정안입니다. 다운로드 파일에 반영됩니다."
          : "표준약관·관련 법률을 근거로 한 AI 생성 수정안입니다. 실제 적용 전 검토가 필요합니다."}
      </p>
      <div className="rewrite-editor-actions">
        <button
          type="button"
          className="rewrite-btn"
          onClick={() => { setDraft(displayText); setEditing(true); }}
        >
          {isUserModified ? "수정" : (hasSuggestion ? "권고안 편집" : "수정안 작성")}
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
            <p className="ref-explanation">{analysis.explanation}</p>
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
              관련 판례 · 법률 ({analysis.similar_references.length})
            </h3>
            <div className="ref-law-items">
              {analysis.similar_references.map((ref, i) => (
                <div key={i} className="ref-law-item">
                  <span className="ref-law-num">{i + 1}</span>
                  <p>{ref}</p>
                </div>
              ))}
            </div>
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

  const counts = useMemo(() => {
    const c = { high: 0, medium: 0, low: 0, safe: 0 };
    orderedClauses.forEach((a) => { c[a.risk_level] = (c[a.risk_level] || 0) + 1; });
    return c;
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
      <div className="result-top-bar">
        <button className="back-button" onClick={() => navigate("/")}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="15 18 9 12 15 6" />
          </svg>
          새 분석
        </button>
        <h2 className="result-filename">{result.filename}</h2>
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
            <span className="doc-viewer-count">{orderedClauses.length}개 조항</span>
          </div>
          <div className="doc-viewer-body">
            {orderedClauses.map((analysis) => {
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
                  <p className="doc-clause-text">{analysis.clause_content}</p>
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
