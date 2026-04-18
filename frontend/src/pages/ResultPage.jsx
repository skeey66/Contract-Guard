import { useState, useRef, useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import RiskBadge from "../components/RiskBadge";
import { buildExportUrl } from "../api/client";

const EXPORT_FORMATS = [
  { key: "docx", label: "DOCX", desc: "MS Word" },
  { key: "pdf", label: "PDF", desc: "인쇄용" },
  { key: "hwpx", label: "HWPX", desc: "한글" },
];

function ExportPanel({ analysisId }) {
  if (!analysisId) return null;
  const handleDownload = (fmt) => {
    const url = buildExportUrl(analysisId, fmt);
    // 새 창 대신 임시 a 요소로 다운로드 트리거
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

function SummaryBar({ result }) {
  const counts = { high: 0, medium: 0, low: 0, safe: 0 };
  result.clause_analyses.forEach((a) => {
    counts[a.risk_level] = (counts[a.risk_level] || 0) + 1;
  });

  const riskyPct =
    result.total_clauses > 0
      ? Math.round((result.risky_clauses / result.total_clauses) * 100)
      : 0;

  let gradeText = "양호";
  let gradeClass = "grade-safe";
  if (riskyPct >= 50) { gradeText = "위험"; gradeClass = "grade-danger"; }
  else if (riskyPct >= 25) { gradeText = "주의"; gradeClass = "grade-caution"; }

  return (
    <div className="summary-bar">
      <div className={`summary-grade ${gradeClass}`}>{gradeText}</div>
      <div className="summary-stats">
        {counts.high > 0 && <span className="sbar-chip sbar-high">고위험 {counts.high}</span>}
        {counts.medium > 0 && <span className="sbar-chip sbar-medium">중위험 {counts.medium}</span>}
        {counts.low > 0 && <span className="sbar-chip sbar-low">저위험 {counts.low}</span>}
        <span className="sbar-chip sbar-safe">안전 {counts.safe}</span>
      </div>
      <div className="summary-score">
        <span className="summary-score-num">{result.risky_clauses}</span>
        <span className="summary-score-sep">/</span>
        <span className="summary-score-total">{result.total_clauses}</span>
        <span className="summary-score-label">위험 조항</span>
      </div>
    </div>
  );
}

function ReferencePanel({ analysis }) {
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
        {/* 분석 요약 */}
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

        {/* 권고 수정안 */}
        {analysis.suggested_rewrite && (
          <section className="ref-section">
            <h3 className="ref-section-label ref-label-rewrite">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 20h9" />
                <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
              </svg>
              권고 수정안
            </h3>
            <div className="ref-rewrite">
              <pre className="ref-rewrite-text">{analysis.suggested_rewrite}</pre>
              <p className="ref-rewrite-note">
                표준약관·관련 법률을 근거로 한 AI 생성 수정안입니다. 실제 적용 전 검토가 필요합니다.
              </p>
            </div>
          </section>
        )}

        {/* 위험 요소 */}
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

        {/* 참고 판례/법률 */}
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
  const result = location.state?.result;
  const [selectedIdx, setSelectedIdx] = useState(null);
  const clauseRefs = useRef({});

  // 조항을 clause_index 순서로 정렬 (문서 원본 순서)
  const orderedClauses = result
    ? [...result.clause_analyses].sort((a, b) => a.clause_index - b.clause_index)
    : [];

  // 첫 위험 조항 자동 선택
  useEffect(() => {
    if (orderedClauses.length > 0 && selectedIdx === null) {
      const firstRisky = orderedClauses.find((a) => a.risk_level !== "safe");
      if (firstRisky) {
        setSelectedIdx(firstRisky.clause_index);
      }
    }
  }, []);

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
          <h3>분석 결과가 없습니다</h3>
          <p>계약서를 먼저 업로드해주세요.</p>
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

      <SummaryBar result={result} />

      {result.summary && <p className="result-summary-text">{result.summary}</p>}

      <ExportPanel analysisId={result.id} />

      <div className="doc-split-layout">
        {/* 왼쪽: 계약서 원본 문서 뷰어 */}
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
                    </div>
                  )}
                  <h4 className="doc-clause-title">{analysis.clause_title}</h4>
                  <p className="doc-clause-text">{analysis.clause_content}</p>
                </div>
              );
            })}
          </div>
        </div>

        {/* 오른쪽: 관련 판례/법률 패널 */}
        <div className="ref-panel-wrap">
          <ReferencePanel analysis={selectedAnalysis} />
        </div>
      </div>
    </div>
  );
}
