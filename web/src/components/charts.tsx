// Dependency-free SVG micro-charts. Everything draws in currentColor so the
// theme tokens (text-accent, text-ink-muted, ...) style them for free.

export function Sparkline({
  values,
  width = 120,
  height = 28,
}: {
  values: number[];
  width?: number;
  height?: number;
}) {
  if (values.length === 0) return null;
  const pad = 2;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = values.length > 1 ? (width - pad * 2) / (values.length - 1) : 0;
  const points = values.map((v, i) => {
    const x = pad + i * step;
    const y = height - pad - ((v - min) / span) * (height - pad * 2);
    return [x, y] as const;
  });
  const last = points[points.length - 1];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden>
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        points={points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ")}
      />
      <circle cx={last[0]} cy={last[1]} r={2.5} fill="currentColor" />
    </svg>
  );
}

export function Bars({
  values,
  width = 120,
  height = 28,
  mirror = false,
}: {
  values: number[];
  width?: number;
  height?: number;
  // mirror=true draws bars symmetric around the vertical centre — the
  // waveform look for audio peaks strips.
  mirror?: boolean;
}) {
  if (values.length === 0) return null;
  const max = Math.max(...values, 1e-9);
  const barWidth = width / values.length;
  return (
    <svg
      width="100%"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      aria-hidden
    >
      {values.map((v, i) => {
        const h = Math.max(1, (v / max) * (mirror ? height : height - 2));
        const y = mirror ? (height - h) / 2 : height - h;
        return (
          <rect
            key={i}
            x={i * barWidth + barWidth * 0.15}
            y={y}
            width={barWidth * 0.7}
            height={h}
            fill="currentColor"
            rx={0.5}
          />
        );
      })}
    </svg>
  );
}
