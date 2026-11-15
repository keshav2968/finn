"use client";

import { useMemo, useState } from "react";
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

const TOP = 22; // room for the high's label
const PRICE_H = 188;
const BOTTOM = 18; // room for the low's label
const GAP = 12;
const VOL_H = 36;
const AXIS_H = 20;
const H = TOP + PRICE_H + BOTTOM + GAP + VOL_H + AXIS_H;
const RIGHT = 58; // the last close, labelled at the line's end

const fmt = (v: number) => v.toLocaleString("en-IN", { maximumFractionDigits: v >= 1000 ? 0 : 1 });

// End-of-day closes, drawn as one line with its own labels: the last close at the end, the
// range's high and low at their points, the filings as violet dots you can tap. Volume sits
// underneath in neutral grey. No grid, no fill, no axis column.
export default function PriceChart({ series, markers, onMarker }: { series: StockSeries; markers: Marker[]; onMarker: (id: string) => void }) {
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
    const span = hi - lo || hi * 0.01;
    const vmax = Math.max(...vol, 1);
    const x = (i: number) => (close.length === 1 ? plotW / 2 : (i * plotW) / (close.length - 1));
    const y = (v: number) => TOP + PRICE_H * (1 - (v - lo) / span);
    const line = close.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join("");
    return { lo, hi, iHi: close.indexOf(hi), iLo: close.indexOf(lo), x, y, line, vmax };
  }, [close, vol, plotW]);

  const first = close[0];
  const last = close[close.length - 1];
  const up = last >= first;
  const color = up ? "var(--pos)" : "var(--neg)";
  const barW = Math.max(1, (plotW / close.length) * 0.6);
  const volTop = TOP + PRICE_H + BOTTOM + GAP;

  const visibleMarkers = markers
    .map((m) => ({ ...m, i: dates.findIndex((d) => d >= m.date) }))
    .filter((m) => m.i >= 0 && m.date <= dates[dates.length - 1]);

  const pick = (clientX: number, el: Element) => {
    const r = el.getBoundingClientRect();
    const i = Math.round(((clientX - r.left) / plotW) * (close.length - 1));
    setHover(Math.max(0, Math.min(close.length - 1, i)));
  };

  // A point label sits centred on its point, pulled inside the plot near either edge.
  const anchor = (i: number) => (geo.x(i) < 40 ? "start" : geo.x(i) > plotW - 40 ? "end" : "middle");
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
              over {range}, {day(dates[0])} – {day(dates[dates.length - 1])}
            </span>
          </>
        ) : (
          <>
            <strong className="num">{rupees(close[hi])}</strong>
            <span className="delta" data-tone="price" data-dir={(chg[hi] ?? 0) > 0 ? "up" : (chg[hi] ?? 0) < 0 ? "down" : "flat"}>
              {pct(chg[hi], 2)}
            </span>
            <span>
              {day(dates[hi])} · volume {shares(vol[hi])}
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
            aria-label={`${range} closing prices from ${rupees(first)} to ${rupees(last)}, ${pct(rangeChange, 1)}; high ${fmt(geo.hi)}, low ${fmt(geo.lo)}. ${visibleMarkers.length} filings marked.`}
            onPointerMove={(e) => pick(e.clientX, e.currentTarget)}
            onPointerDown={(e) => pick(e.clientX, e.currentTarget)}
            onPointerLeave={() => setHover(null)}
            style={{ touchAction: "pan-y", display: "block" }}
          >
            {/* where the range started: one faint reference */}
            <line x1={0} x2={plotW} y1={geo.y(first)} y2={geo.y(first)} stroke="var(--muted)" strokeOpacity="0.4" strokeDasharray="1 4" />

            <path d={geo.line} fill="none" stroke={color} strokeWidth="1.75" strokeLinejoin="round" strokeLinecap="round" />

            {/* direct labels: high, low, last */}
            <text x={geo.x(geo.iHi)} y={geo.y(geo.hi) - 8} textAnchor={anchor(geo.iHi)} className={s.pointLabel}>
              {fmt(geo.hi)}
            </text>
            {geo.iLo !== geo.iHi && (
              <text x={geo.x(geo.iLo)} y={geo.y(geo.lo) + 15} textAnchor={anchor(geo.iLo)} className={s.pointLabel}>
                {fmt(geo.lo)}
              </text>
            )}
            <circle cx={geo.x(close.length - 1)} cy={geo.y(last)} r={3} fill={color} />
            <text x={plotW + 8} y={geo.y(last) + 4} className={s.lastLabel}>
              {fmt(last)}
            </text>

            {/* volume */}
            <text x={0} y={volTop - 2} className={s.axis}>
              Volume
            </text>
            <g transform={`translate(0 ${volTop})`}>
              {vol.map((v, i) => (
                <rect
                  key={i}
                  x={geo.x(i) - barW / 2}
                  y={VOL_H - (v / geo.vmax) * VOL_H}
                  width={barW}
                  height={Math.max(0.5, (v / geo.vmax) * VOL_H)}
                  fill="var(--fg-2)"
                  opacity={hover === i ? 0.9 : 0.28}
                />
              ))}
            </g>

            {/* dates */}
            <text x={0} y={H - 4} className={s.axis}>
              {day(dates[0])}
            </text>
            <text x={plotW} y={H - 4} textAnchor="end" className={s.axis}>
              {day(dates[dates.length - 1])}
            </text>

            {hover !== null && (
              <g pointerEvents="none">
                <line x1={geo.x(hover)} x2={geo.x(hover)} y1={TOP - 6} y2={volTop + VOL_H} stroke="var(--fg-2)" strokeOpacity="0.45" />
                <circle cx={geo.x(hover)} cy={geo.y(close[hover])} r={4} fill="var(--canvas)" stroke={color} strokeWidth="2" />
              </g>
            )}

            {/* filings on the price line: violet, because you can tap them */}
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
                <circle cx={geo.x(m.i)} cy={geo.y(close[m.i])} r={9} fill="none" stroke="var(--accent)" strokeWidth="2" className={s.markerRing} />
                <circle
                  cx={geo.x(m.i)}
                  cy={geo.y(close[m.i])}
                  r={4.5}
                  fill={m.tier === "needs_attention" ? "var(--accent)" : "var(--canvas)"}
                  stroke="var(--accent)"
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
            <button
              key={r.key}
              type="button"
              aria-pressed={r.key === range}
              onClick={() => {
                setRange(r.key);
                setHover(null);
              }}
            >
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
