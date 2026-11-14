// A sparkline from real closing prices. The line is quiet; only the last point carries
// the price-move colour, and the figure beside it always has an arrow and a sign.

export default function Spark({
  values,
  width = 64,
  height = 24,
  dir,
  fluid = false,
}: {
  values: number[];
  width?: number;
  height?: number;
  dir: "up" | "down" | "flat";
  fluid?: boolean; // stretch to the container's width
}) {
  if (values.length < 2) return null;
  const pad = 2.5;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = (width - pad * 2) / (values.length - 1);
  const pts = values.map((v, i) => [pad + i * step, pad + (height - pad * 2) * (1 - (v - min) / span)] as const);
  const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join("");
  const [lx, ly] = pts[pts.length - 1];
  return (
    <svg
      width={fluid ? "100%" : width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      aria-hidden="true"
      style={{ display: "block", flex: "none", overflow: "visible" }}
    >
      <path
        d={d}
        fill="none"
        stroke="var(--muted)"
        strokeWidth="1.25"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
      <circle cx={lx} cy={ly} r="2.5" fill={dir === "down" ? "var(--down)" : dir === "up" ? "var(--up)" : "var(--muted)"} />
    </svg>
  );
}
