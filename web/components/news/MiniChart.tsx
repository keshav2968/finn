"use client";

import { useId } from "react";

// A story's price strip: closes across the window, drawn in on mount, with the filing's
// session marked. Width follows the card (viewBox + non-scaling stroke).
export default function MiniChart({ values, mark, height = 56 }: { values: number[]; mark: number; height?: number }) {
  const id = useId().replace(/:/g, "");
  const W = 300;
  const pad = 4;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x = (i: number) => pad + (i * (W - pad * 2)) / (values.length - 1);
  const y = (v: number) => pad + (height - pad * 2) * (1 - (v - min) / span);
  const line = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join("");
  const area = `${line}L${x(values.length - 1).toFixed(1)} ${height}L${x(0).toFixed(1)} ${height}Z`;
  const up = values[values.length - 1] >= values[0];
  const color = up ? "var(--pos)" : "var(--neg)";
  return (
    <svg viewBox={`0 0 ${W} ${height}`} width="100%" height={height} preserveAspectRatio="none" aria-hidden="true" style={{ display: "block" }}>
      <defs>
        <linearGradient id={`m${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.22" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#m${id})`} className="fadeIn" />
      <path d={line} fill="none" stroke={color} strokeWidth="1.75" vectorEffect="non-scaling-stroke" pathLength={1} className="drawIn" strokeLinejoin="round" />
      <line x1={x(mark)} x2={x(mark)} y1={0} y2={height} stroke="var(--fg-2)" strokeOpacity="0.35" strokeDasharray="2 3" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
