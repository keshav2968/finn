"use client";

import { useId, useMemo, useState } from "react";
import { day, pct, rupees, shares, signed } from "@/lib/format";
import type { StockSeries } from "@/lib/data";
import { useWidth } from "../motion";
import u from "../ui.module.css";
import s from "./markets.module.css";

export interface Marker {
  id: string;
  date: string; // the session the filing could first move the price
  tier: "needs_attention" | "worth_knowing" | "routine";
  label: string;
}

const RANGES = [
  { key: "1M", sessions: 21 },
  { key: "3M", sessions: 63 },
  { key: "6M", sessions: 126 },
  { key: "1Y", sessions: 260 },
] as const;
type RangeKey = (typeof RANGES)[number]["key"];

const PRICE_H = 200;
const GAP = 14;
const VOL_H = 44;
const AXIS_H = 18;
const H = PRICE_H + GAP + VOL_H + AXIS_H;
const RIGHT = 52; // price labels

// End-of-day closes with volume underneath and the snapshot's filings marked on the line.
// Drag across to read any session; tap a marker to open that filing.
export default function PriceChart({ series, markers, onMarker }: { series: StockSeries; markers: Marker[]; onMarker: (id: string) => void }) {
  const id = useId().replace(/:/g, "");
  const [ref, width] = useWidth<HTMLDivElement>();
  const [range, setRange] = useState<RangeKey>("3M");
  const [hover, setHover] = useState<number | null>(null);

  const n = RANGES.find((r) => r.key === range)!.sessions;
  const from = Math.max(0, series.date.length - n);
  const dates = series.date.slice(from);
  const close = series.close.slice(from);
  const vol = series.volume.slice(from);
  const chg = series.pct_change.slice(from);
  const W = Math.max(0, width);
  const plotW = Math.max(10, W - RIGHT);

  const geo = useMemo(() => {
    const lo = Math.min(...close);
    const hi = Math.max(...close);
    const padY = (hi - lo) * 0.08 || hi * 0.01;
    const min = lo - padY;
    const max = hi + padY;
    const vmax = Math.max(...vol, 1);
    const x = (i: number) => (close.length === 1 ? plotW / 2 : (i * plotW) / (close.length - 1));
    const y = (v: number) => 6 + (PRICE_H - 12) * (1 - (v - min) / (max - min));
    const line = close.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join("");
    const area = `${line}L${x(close.length - 1).toFixed(1)} ${PRICE_H}L0 ${PRICE_H}Z`;
    return { lo, hi, x, y, line, area, vmax };
  }, [close, vol, plotW]);

  const first = close[0];
  const last = close[close.length - 1];
  const up = last >= first;
  const color = up ? "var(--pos)" : "var(--neg)";
  const barW = Math.max(1, (plotW / close.length) * 0.62);

  const visibleMarkers = markers
    .map((m) => ({ ...m, i: dates.findIndex((d) => d >= m.date) }))
    .filter((m) => m.i >= 0 && m.date <= dates[dates.length - 1]);

  const pick = (clientX: number, el: Element) => {
    const r = el.getBoundingClientRect();
    const i = Math.round(((clientX - r.left) / plotW) * (close.length - 1));
    setHover(Math.max(0, Math.min(close.length - 1, i)));
  };

  const hi = hover ?? close.length - 1;
  const rangeChange = ((last - first) / first) * 100;

  return (
    <div className={s.chartBox}>
      <p className={s.readout} aria-live="polite">
        {hover === null ? (
          <>
            <span className="delta" data-tone="price" data-dir={up ? "up" : "down"}>
              {pct(rangeChange, 2)}
            </span>
            <span className="num">{signed(last - first, 2)}</span>
            <span>
              over {range} · {day(dates[0])} – {day(dates[dates.length - 1])}
            </span>
          </>
        ) : (
          <>
            <strong className="num">{rupees(close[hi])}</strong>
            <span className="delta" data-tone="price" data-dir={(chg[hi] ?? 0) > 0 ? "up" : (chg[hi] ?? 0) < 0 ? "down" : "flat"}>
              {pct(chg[hi], 2)}
            </span>
            <span>
              {day(dates[hi])} · vol {shares(vol[hi])}
            </span>
          </>
        )}
      </p>

      <div ref={ref} className={s.chartArea} style={{ height: H }}>
        {W === 0 ? (
          <span className="skel" style={{ height: H, width: "100%" }} aria-hidden="true" />
        ) : (
          <svg
            width={W}
            height={H}
            viewBox={`0 0 ${W} ${H}`}
            role="img"
            aria-label={`${range} closing prices from ${rupees(first)} to ${rupees(last)}, ${pct(rangeChange, 1)}. ${visibleMarkers.length} filings marked.`}
            onPointerMove={(e) => pick(e.clientX, e.currentTarget)}
            onPointerDown={(e) => pick(e.clientX, e.currentTarget)}
            onPointerLeave={() => setHover(null)}
            style={{ touchAction: "pan-y", display: "block" }}
          >
            <defs>
              <linearGradient id={`a${id}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity="0.26" />
                <stop offset="100%" stopColor={color} stopOpacity="0" />
              </linearGradient>
            </defs>

            {/* price scale: high, low */}
            {[geo.hi, geo.lo].map((v) => (
              <g key={v}>
                <line x1={0} x2={plotW} y1={geo.y(v)} y2={geo.y(v)} stroke="var(--border)" strokeDasharray="2 4" />
                <text x={W - 2} y={geo.y(v) + 4} textAnchor="end" className={s.axis}>
                  {Math.round(v).toLocaleString("en-IN")}
                </text>
              </g>
            ))}
            {/* where the range started */}
            <line x1={0} x2={plotW} y1={geo.y(first)} y2={geo.y(first)} stroke="var(--muted)" strokeOpacity="0.5" strokeDasharray="1 3" />

            <g key={range}>
              <path d={geo.area} fill={`url(#a${id})`} className="fadeIn" />
              <path d={geo.line} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" pathLength={1} className="drawIn" />
              <g transform={`translate(0 ${PRICE_H + GAP})`} className={s.bars}>
                {vol.map((v, i) => (
                  <rect
                    key={i}
                    x={geo.x(i) - barW / 2}
                    y={VOL_H - (v / geo.vmax) * VOL_H}
                    width={barW}
                    height={(v / geo.vmax) * VOL_H}
                    rx={Math.min(1.5, barW / 2)}
                    fill={(chg[i] ?? 0) >= 0 ? "var(--pos)" : "var(--neg)"}
                    opacity={hover === i ? 0.95 : 0.42}
                  />
                ))}
              </g>
            </g>

            {/* dates */}
            <text x={0} y={H - 4} className={s.axis}>
              {day(dates[0])}
            </text>
            <text x={plotW} y={H - 4} textAnchor="end" className={s.axis}>
              {day(dates[dates.length - 1])}
            </text>
            <text x={W - 2} y={PRICE_H + GAP + 10} textAnchor="end" className={s.axis}>
              vol
            </text>

            {hover !== null && (
              <g pointerEvents="none">
                <line x1={geo.x(hover)} x2={geo.x(hover)} y1={0} y2={PRICE_H + GAP + VOL_H} stroke="var(--fg-2)" strokeOpacity="0.5" />
                <circle cx={geo.x(hover)} cy={geo.y(close[hover])} r={4.5} fill={color} stroke="var(--canvas)" strokeWidth="2" />
              </g>
            )}

            {/* filings on the price line */}
            {visibleMarkers.map((m) => (
              <g
                key={m.id}
                role="button"
                tabIndex={0}
                aria-label={`Filing on ${day(m.date)}: ${m.label}`}
                className={s.marker}
                onPointerDown={(e) => e.stopPropagation()}
                onClick={() => onMarker(m.id)}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onMarker(m.id))}
              >
                <circle cx={geo.x(m.i)} cy={geo.y(close[m.i])} r={14} fill="transparent" />
                <circle
                  cx={geo.x(m.i)}
                  cy={geo.y(close[m.i])}
                  r={m.tier === "needs_attention" ? 6 : 4.5}
                  fill={m.tier === "needs_attention" ? "var(--teal)" : "var(--fg-2)"}
                  stroke="var(--canvas)"
                  strokeWidth="2"
                  className={s.markerDot}
                />
              </g>
            ))}
          </svg>
        )}
      </div>

      <div className={s.chartFoot}>
        <div className={u.segment} role="group" aria-label="Chart range">
          {RANGES.map((r) => (
            <button key={r.key} type="button" aria-pressed={r.key === range} onClick={() => { setRange(r.key); setHover(null); }}>
              {r.key}
            </button>
          ))}
        </div>
        <span className={s.legend}>
          <span className={s.legendDot} data-tier="needs_attention" /> needs attention
          <span className={s.legendDot} data-tier="worth_knowing" /> worth knowing
        </span>
      </div>
    </div>
  );
}
