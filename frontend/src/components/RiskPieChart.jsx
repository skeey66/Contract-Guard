// 위험도 분포 도넛 차트 — 외부 차트 라이브러리 없이 SVG로 직접 그린다 (폐쇄망 대응).
// stroke-dasharray로 원호 길이를 조절하고 stroke-dashoffset으로 시작 위치를 회전.

const SEGMENTS = [
  { key: "high", label: "고위험", color: "var(--risk-high, #c0392b)" },
  { key: "medium", label: "중위험", color: "var(--risk-medium, #e67e22)" },
  { key: "low", label: "저위험", color: "var(--risk-low, #888888)" },
  { key: "safe", label: "안전", color: "var(--risk-safe, #2e7d32)" },
];

export default function RiskPieChart({ counts = {}, size = 180, strokeWidth = 28 }) {
  const total = SEGMENTS.reduce((sum, s) => sum + (counts[s.key] || 0), 0);
  const radius = (size - strokeWidth) / 2;
  const center = size / 2;
  const circumference = 2 * Math.PI * radius;

  // 누적 오프셋으로 각 세그먼트 시작 위치 계산
  let cumulative = 0;
  const arcs = SEGMENTS.map((seg) => {
    const value = counts[seg.key] || 0;
    if (value === 0 || total === 0) return null;
    const fraction = value / total;
    const dash = fraction * circumference;
    const offset = -cumulative * circumference;
    cumulative += fraction;
    return { ...seg, value, fraction, dash, gap: circumference - dash, offset };
  }).filter(Boolean);

  return (
    <div className="pie-chart">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="pie-chart-svg">
        {/* 배경 트랙 */}
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke="rgba(0,0,0,0.05)"
          strokeWidth={strokeWidth}
        />
        {/* 12시 방향에서 시작하도록 -90도 회전 */}
        <g transform={`rotate(-90 ${center} ${center})`}>
          {arcs.map((arc) => (
            <circle
              key={arc.key}
              cx={center}
              cy={center}
              r={radius}
              fill="none"
              stroke={arc.color}
              strokeWidth={strokeWidth}
              strokeDasharray={`${arc.dash} ${arc.gap}`}
              strokeDashoffset={arc.offset}
              strokeLinecap="butt"
            />
          ))}
        </g>
        {/* 중앙 텍스트 */}
        <text
          x={center}
          y={center - 6}
          textAnchor="middle"
          className="pie-chart-center-num"
        >
          {total}
        </text>
        <text
          x={center}
          y={center + 14}
          textAnchor="middle"
          className="pie-chart-center-label"
        >
          전체 조항
        </text>
      </svg>

      <ul className="pie-chart-legend">
        {SEGMENTS.map((seg) => {
          const value = counts[seg.key] || 0;
          const pct = total > 0 ? Math.round((value / total) * 100) : 0;
          return (
            <li key={seg.key} className="pie-legend-item">
              <span className="pie-legend-dot" style={{ background: seg.color }} />
              <span className="pie-legend-label">{seg.label}</span>
              <span className="pie-legend-value">
                {value}건 <span className="pie-legend-pct">({pct}%)</span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
