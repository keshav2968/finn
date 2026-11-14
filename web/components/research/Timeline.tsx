import type { LedgerEntry } from "@/lib/research";

// One promise over time: each call's guided range as a band, the actual as a dot.
// Every value is from the research file (quotes and screener); nothing is computed here
// beyond placing points on the chart.

const W = 340;
const H = 168;
const PAD = { l: 38, r: 14, t: 26, b: 34 };

function short(call: string): string {
  const m = call.match(/^([A-Z][a-z]{2}) \d{2}(\d{2})$/);
  return m ? `${m[1]} ’${m[2]}` : call;
}

function niceStep(span: number): number {
  const raw = span / 3;
  const pow = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 2.5, 5, 10].map((k) => k * pow).find((s) => s >= raw) ?? raw;
}

export default function Timeline({ chart, label }: { chart: NonNullable<LedgerEntry["chart"]>; label: string }) {
  const { guides, actual } = chart;
  const values = guides.flatMap((g) => [g.low, g.high]).concat(actual ? [actual.value] : []);
  const lo0 = Math.min(...values);
  const hi0 = Math.max(...values);
  const step = niceStep(Math.max(hi0 - lo0, 1));
  const lo = Math.floor((lo0 - step / 2) / step) * step;
  const hi = Math.ceil((hi0 + step / 2) / step) * step;
  const ticks: number[] = [];
  for (let v = lo; v <= hi + 1e-9; v += step) ticks.push(Number(v.toFixed(4)));

  const cols = guides.length + (actual ? 1 : 0);
  const innerW = W - PAD.l - PAD.r;
  const x = (i: number) => PAD.l + (innerW * (i + 0.5)) / cols;
  const y = (v: number) => PAD.t + (H - PAD.t - PAD.b) * (1 - (v - lo) / (hi - lo));
  const fmt = (v: number) => `${Number(v.toFixed(2))}%`;
  const bandW = Math.min(26, innerW / cols - 14);

  const summary = `${label}: ${guides.map((g) => `${g.call} ${fmt(g.low)} to ${fmt(g.high)}`).join("; ")}${actual ? `; actual ${fmt(actual.value)}` : ""}`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={summary} style={{ display: "block", overflow: "visible" }}>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="var(--track)" strokeWidth="1" />
          <text x={PAD.l - 8} y={y(t) + 4} textAnchor="end" fontSize="10.5" fill="var(--muted)" fontFamily="var(--font-num)">
            {fmt(t)}
          </text>
        </g>
      ))}

      {actual && (
        <line x1={PAD.l} x2={W - PAD.r} y1={y(actual.value)} y2={y(actual.value)} stroke="var(--fg-2)" strokeWidth="1" strokeDasharray="3 4" opacity="0.7" />
      )}

      {guides.map((g, i) => {
        const latest = i === guides.length - 1;
        const top = y(g.high);
        const height = Math.max(4, y(g.low) - y(g.high));
        return (
          <g key={`${g.call}-${i}`}>
            <rect x={x(i) - bandW / 2} y={top} width={bandW} height={height} rx="6" fill="var(--fg-2)" fillOpacity={latest ? 0.34 : 0.16} stroke="var(--fg-2)" strokeOpacity={latest ? 0.7 : 0.3} />
            <text x={x(i)} y={top - 7} textAnchor="middle" fontSize="10" fill={latest ? "var(--fg)" : "var(--muted)"} fontFamily="var(--font-num)">
              {g.low === g.high ? fmt(g.low) : `${Number(g.low.toFixed(2))}–${fmt(g.high)}`}
            </text>
            <text x={x(i)} y={H - 12} textAnchor="middle" fontSize="11" fill="var(--muted)">
              {short(g.call)}
            </text>
          </g>
        );
      })}

      {actual && (
        <g>
          <circle cx={x(cols - 1)} cy={y(actual.value)} r="6.5" fill={actual.complete ? "var(--fg)" : "var(--card)"} stroke="var(--fg)" strokeWidth="2" />
          <text x={x(cols - 1)} y={y(actual.value) - 12} textAnchor="middle" fontSize="11" fontWeight="700" fill="var(--fg)" fontFamily="var(--font-num)">
            {fmt(actual.value)}
          </text>
          <text x={x(cols - 1)} y={H - 12} textAnchor="middle" fontSize="11" fontWeight="600" fill="var(--fg)">
            {actual.kind === "stated" ? "Stated" : actual.complete ? "Actual" : "So far"}
          </text>
        </g>
      )}
    </svg>
  );
}
