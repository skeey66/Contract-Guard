// 4단계 액션 중심 라벨:
//   high   = 법률 위반 — 약관규제법·민법·주임법 명백 위반, 즉시 수정 권고
//   medium = 계약자 불리 — 위법은 아니나 일방적 부담, 협상 권장
//   low    = 검토 권장 — 회색지대·정보 부족, 전문가 검토 필요
//   safe   = 안전 — 표준 정형 표현
const RISK_CONFIG = {
  high: { label: "법률 위반", className: "risk-high" },
  medium: { label: "계약자 불리", className: "risk-medium" },
  low: { label: "검토 권장", className: "risk-low" },
  safe: { label: "안전", className: "risk-safe" },
};

export default function RiskBadge({ level }) {
  const config = RISK_CONFIG[level] || RISK_CONFIG.safe;
  return <span className={`risk-badge ${config.className}`}>{config.label}</span>;
}
