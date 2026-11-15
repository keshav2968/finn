"use client";

import { day } from "@/lib/format";
import s from "./news.module.css";

// A story's price strip: one thin line of closes across the window, the filing's session
// marked and labelled on the chart, the two end dates under it. No fill, no grid.
// `mark` is the first session the filing could move the price; `filed` is when it was filed.
export default function MiniChart({ values, mark, dates, filed, height = 44 }: { values: number[]; mark: number; dates: string[]; filed: string; height?: number }) {
  const W = 300;
  const pad = 3;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x = (i: number) => pad + (i * (W - pad * 2)) / (values.length - 1);
  const y = (v: number) => pad + (height - pad * 2) * (1 - (v - min) / span);
  const line = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join("");
  const up = values[values.length - 1] >= values[0];
  const markPct = (x(mark) / W) * 100;
  return (
    <span className={s.mini} role="img" aria-label={`Closing price ${day(dates[0])} to ${day(dates[dates.length - 1])}; filed ${day(filed)}`}>
      <svg viewBox={`0 0 ${W} ${height}`} width="100%" height={height} preserveAspectRatio="none" aria-hidden="true">
        <line x1={x(mark)} x2={x(mark)} y1={0} y2={height} stroke="var(--fg-2)" strokeOpacity="0.45" vectorEffect="non-scaling-stroke" />
        <path d={line} fill="none" stroke={up ? "var(--pos)" : "var(--neg)"} strokeWidth="1.5" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      </svg>
      <span className={s.miniMark} style={{ left: `${markPct}%` }} data-edge={markPct > 78 ? "right" : markPct < 22 ? "left" : undefined} aria-hidden="true">
        Filed {day(filed)}
      </span>
      <span className={s.miniAxis} aria-hidden="true">
        <span>{day(dates[0])}</span>
        <span>{day(dates[dates.length - 1])}</span>
      </span>
    </span>
  );
}
