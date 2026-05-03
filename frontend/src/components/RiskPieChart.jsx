// 위험도 분포 도넛 차트 — 외부 차트 라이브러리 없이 SVG로 직접 그린다 (폐쇄망 대응).
// stroke-dasharray로 원호 길이를 조절하고 stroke-dashoffset으로 시작 위치를 회전.

// 도넛 차트는 단순 2분류 — 위험(빨강) vs 안전(초록).
// 세부 분류(법률 위반/계약자 불리/검토 권장)는 헤더 배지·범례에서 별도 표시.
const SEGMENTS = [
  { key: "risky", label: "위험 조항", color: "var(--risk-high, #c0392b)",
    sourceKeys: ["high", "medium", "low"] },
  { key: "safe", label: "안전", color: "var(--risk-safe, #2e7d32)",
    sourceKeys: ["safe"] },
];

export default function RiskPieChart({ counts = {}, size = 180, strokeWidth = 28 }) {
  // 원본 counts({high, medium, low, safe})를 2분류로 합산
  const aggCounts = SEGMENTS.reduce((acc, seg) => {
    acc[seg.key] = seg.sourceKeys.reduce((s, k) => s + (counts[k] || 0), 0);
    return acc;
  }, {});
  const total = SEGMENTS.reduce((sum, s) => sum + (aggCounts[s.key] || 0), 0);
  const radius = (size - strokeWidth) / 2;
  const center = size / 2;
  const circumference = 2 * Math.PI * radius;

  // 누적 오프셋으로 각 세그먼트 시작 위치 계산.
  // midAngle은 segment 중앙(라디안) — 도넛 위에 %를 표시할 좌표 계산에 사용.
  // 12시 방향 시작이라 -π/2부터 시계방향으로 진행.
  let cumulative = 0;
  const arcs = SEGMENTS.map((seg) => {
    const value = aggCounts[seg.key] || 0;
    if (value === 0 || total === 0) return null;
    const fraction = value / total;
    const dash = fraction * circumference;
    const offset = -cumulative * circumference;
    // 세그먼트 중앙 각도 (라디안). 12시(-π/2)에서 시계방향.
    const startAngle = -Math.PI / 2 + cumulative * 2 * Math.PI;
    const midAngle = startAngle + (fraction * 2 * Math.PI) / 2;
    const labelX = center + radius * Math.cos(midAngle);
    const labelY = center + radius * Math.sin(midAngle);
    cumulative += fraction;
    return {
      ...seg, value, fraction, dash, gap: circumference - dash, offset,
      labelX, labelY,
      pct: Math.round(fraction * 100),
    };
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
          {arcs.map((arc, i) => (
            <circle
              key={arc.key}
              cx={center}
              cy={center}
              r={radius}
              fill="none"
              stroke={arc.color}
              strokeWidth={strokeWidth}
              strokeDashoffset={arc.offset}
              strokeLinecap="butt"
              className="pie-arc"
              style={{
                // CSS keyframe pie-grow가 0 → 최종 dash 값으로 시계방향 채움
                "--pie-dash": `${arc.dash}px`,
                "--pie-gap": `${arc.gap}px`,
                "--pie-circ": `${circumference}px`,
                "--pie-delay": `${i * 0.18}s`,
              }}
            />
          ))}
        </g>
        {/* 각 세그먼트 위에 % 라벨 — 너무 작은 segment(<5%)는 표시 생략(겹침 방지) */}
        {arcs.map((arc) => arc.pct >= 5 && (
          <text
            key={`pct-${arc.key}`}
            x={arc.labelX}
            y={arc.labelY}
            textAnchor="middle"
            dominantBaseline="central"
            className="pie-arc-pct"
          >
            {arc.pct}%
          </text>
        ))}
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
          const value = aggCounts[seg.key] || 0;
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
