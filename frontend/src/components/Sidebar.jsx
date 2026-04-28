import { useNavigate, useParams } from "react-router-dom";
import { useAnalyses } from "../context/AnalysesContext";

const CONTRACT_LABELS = {
  lease: "임대차",
  sales: "매매",
  employment: "근로",
  service: "용역",
  loan: "금전소비대차",
};

function contractLabel(code) {
  if (!code) return "기타";
  return CONTRACT_LABELS[code] || code;
}

// 간단한 상대시간 포맷 — 외부 의존성 도입을 피하기 위해 직접 구현.
function formatRelativeTime(iso) {
  if (!iso) return "";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  const diffSec = Math.round((Date.now() - then.getTime()) / 1000);
  const abs = Math.abs(diffSec);
  if (abs < 60) return "방금";
  if (abs < 3600) return `${Math.round(abs / 60)}분 전`;
  if (abs < 86400) return `${Math.round(abs / 3600)}시간 전`;
  if (abs < 604800) return `${Math.round(abs / 86400)}일 전`;
  return then.toLocaleDateString("ko-KR", {
    year: "2-digit",
    month: "2-digit",
    day: "2-digit",
  });
}

function stripExtension(filename) {
  if (!filename) return "";
  const idx = filename.lastIndexOf(".");
  return idx > 0 ? filename.slice(0, idx) : filename;
}

export default function Sidebar({ isOpen = true }) {
  const navigate = useNavigate();
  const { analysisId: currentId } = useParams();
  const { items, loading, error, refresh, remove } = useAnalyses();

  const handleOpen = (id) => {
    navigate(`/result/${encodeURIComponent(id)}`);
  };

  const handleDelete = async (e, item) => {
    e.stopPropagation();
    const label = stripExtension(item.filename) || "이 분석";
    if (!window.confirm(`"${label}" 분석을 삭제하시겠습니까?`)) return;
    try {
      await remove(item.id);
      if (currentId === item.id) {
        navigate("/");
      }
    } catch (err) {
      window.alert(err?.message || "삭제에 실패했습니다.");
    }
  };

  return (
    <aside
      className={`sidebar${isOpen ? "" : " sidebar--collapsed"}`}
      aria-hidden={!isOpen}
    >
      <div className="sidebar-header">
        <span className="sidebar-title">분석 이력</span>
        <button
          type="button"
          className="sidebar-refresh"
          onClick={refresh}
          title="목록 새로고침"
          aria-label="새로고침"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="23 4 23 10 17 10" />
            <polyline points="1 20 1 14 7 14" />
            <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
          </svg>
        </button>
      </div>

      <button
        type="button"
        className="sidebar-new"
        onClick={() => navigate("/")}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="12" y1="5" x2="12" y2="19" />
          <line x1="5" y1="12" x2="19" y2="12" />
        </svg>
        새 분석
      </button>

      <div className="sidebar-list">
        {loading && items.length === 0 && (
          <div className="sidebar-empty">불러오는 중...</div>
        )}
        {!loading && items.length === 0 && !error && (
          <div className="sidebar-empty">분석된 계약서가 없습니다.</div>
        )}
        {error && <div className="sidebar-empty sidebar-error">{error}</div>}

        {items.map((item) => {
          const isActive = currentId === item.id;
          return (
            <div
              key={item.id}
              className={`sidebar-item${isActive ? " active" : ""}`}
              onClick={() => handleOpen(item.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  handleOpen(item.id);
                }
              }}
            >
              <div className="sidebar-item__main">
                <div className="sidebar-item__filename" title={item.filename}>
                  {stripExtension(item.filename) || item.id.slice(0, 8)}
                </div>
                <div className="sidebar-item__meta">
                  <span className="sidebar-badge">{contractLabel(item.contract_type)}</span>
                  <span className="sidebar-dot">·</span>
                  <span className="sidebar-time">{formatRelativeTime(item.created_at)}</span>
                </div>
              </div>
              <button
                type="button"
                className="sidebar-item__delete"
                onClick={(e) => handleDelete(e, item)}
                aria-label="삭제"
                title="삭제"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
