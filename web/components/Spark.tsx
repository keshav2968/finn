"use client";

import { useId } from "react";

// A sparkline from real closing prices with a soft fill underneath. The tint follows
// the session's direction; the figure beside it always carries an arrow and a sign.
export default function Spark({
  values,
  width = 88,
  height = 36,
  dir,
  fluid = false,
}: {
  values: number[];
  width?: number;
  height?: number;
  dir: "up" | "down" | "flat";
  fluid?: boolean; // stretch to the container's width
}) {
  const id = useId().replace(/:/g, "");
  if (values.length < 2) return null;
  const pad = 3;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = (width - pad * 2) / (values.length - 1);
  const pts = values.map((v, i) => [pad + i * step, pad + (height - pad * 2) * (1 - (v - min) / span)] as const);
  const line = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join("");
  const area = `${line}L${pts[pts.length - 1][0].toFixed(1)} ${height}L${pts[0][0].toFixed(1)} ${height}Z`;
  const color = dir === "down" ? "var(--neg)" : dir === "up" ? "var(--pos)" : "var(--muted)";
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
      <defs>
        <linearGradient id={`g${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#g${id})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      {!fluid && <circle cx={lx} cy={ly} r="2.5" fill={color} />}
    </svg>
  );
}
