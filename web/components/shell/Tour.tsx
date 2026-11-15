"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, ChartCandlestick, Newspaper, ScanSearch, X } from "lucide-react";
import { isStandalone } from "./install";
import s from "./tour.module.css";

// First run after install: four screens you swipe through (native scroll-snap), skippable,
// shown once (the first launch from the home screen) and replayable from the Alerts tab.
export const TOUR_KEY = "finn.tour.v1";
export const TOUR_EVENT = "finn:tour";

const SLIDES = [
  {
    Icon: Newspaper,
    title: "News: what changed, ranked",
    body: "Every exchange filing from your 15 holdings, ranked. Needs attention comes first and routine paperwork folds into one row. Tap a story for its figures and the filing itself.",
  },
  {
    Icon: ChartCandlestick,
    title: "Markets: prices and charts",
    body: "End-of-day prices for the stocks you pick, with each stock's filings marked on its chart. Tap a dot on the line to open that filing.",
  },
  {
    Icon: ScanSearch,
    title: "Research: promises against delivery",
    body: "What management guided on its earnings calls, checked against the numbers it reported later. Every quote links to its transcript.",
  },
  {
    Icon: Bell,
    title: "Alerts: your rules",
    body: "Decide what counts as unusual: a price move, a volume spike, the filing types you care about. FINN lists what crossed your rules.",
  },
];

// A small drawing of each tab's layout, in the app's own tokens (decorative).
function Sketch({ kind }: { kind: number }) {
  const bar = (x: number, y: number, w: number, h = 8, fill = "var(--track)") => <rect x={x} y={y} width={w} height={h} rx={h / 2} fill={fill} />;
  return (
    <svg className={s.sketch} viewBox="0 0 300 150" aria-hidden="true">
      {kind === 0 &&
        [0, 1, 2].map((r) => (
          <g key={r} transform={`translate(0 ${r * 50})`}>
            <rect x="0" y="4" width="36" height="36" rx="9" fill={r === 0 ? "var(--cat-results-bg)" : "var(--track)"} />
            {bar(48, 6, 54, 10, r === 1 ? "var(--cat-fund-bg)" : "var(--card)")}
            {bar(48, 22, r === 0 ? 220 : 180, 9, "var(--fg-2)")}
            {r < 2 && <line x1="0" x2="300" y1="46" y2="46" stroke="var(--border)" />}
          </g>
        ))}
      {kind === 1 && (
        <>
          <path d="M0 110 L30 96 L60 104 L90 80 L120 88 L150 60 L180 70 L210 44 L240 56 L270 30 L300 38" fill="none" stroke="var(--pos)" strokeWidth="2.5" strokeLinejoin="round" />
          <circle cx="150" cy="60" r="6" fill="var(--accent)" />
          <circle cx="240" cy="56" r="6" fill="none" stroke="var(--accent)" strokeWidth="2.5" />
          {Array.from({ length: 20 }, (_, i) => <rect key={i} x={i * 15 + 2} y={150 - ((i * 37) % 22) - 8} width="9" height={((i * 37) % 22) + 8} fill="var(--fg-2)" opacity="0.3" />)}
        </>
      )}
      {kind === 2 &&
        [0, 1].map((r) => (
          <g key={r} transform={`translate(0 ${r * 70})`}>
            {bar(0, 4, 120, 10, "var(--fg-2)")}
            <rect x="0" y="28" width="300" height="22" rx="4" fill="var(--track)" />
            <rect x={r ? 60 : 120} y="28" width={r ? 140 : 90} height="22" rx="4" fill="var(--fg-2)" opacity="0.35" />
            <circle cx={r ? 230 : 170} cy="39" r="7" fill="var(--fg)" />
          </g>
        ))}
      {kind === 3 && (
        <>
          {[["±4%", 0], ["2×", 80], ["3σ", 148]].map(([t, x], j) => (
            <g key={j} transform={`translate(${x} 10)`}>
              <rect width="64" height="34" rx="17" fill={j === 0 ? "var(--accent)" : "var(--card)"} stroke="var(--border)" />
              <text x="32" y="22" textAnchor="middle" fontSize="13" fontWeight="700" fill={j === 0 ? "var(--on-accent)" : "var(--fg-2)"}>{t}</text>
            </g>
          ))}
          {[0, 1].map((r) => (
            <g key={r} transform={`translate(0 ${64 + r * 42})`}>
              <rect width="30" height="30" rx="8" fill="var(--track)" />
              {bar(42, 4, 70, 9, r ? "var(--neg)" : "var(--pos)")}
              {bar(42, 18, 200, 8, "var(--fg-2)")}
            </g>
          ))}
        </>
      )}
    </svg>
  );
}

export function replayTour() {
  window.dispatchEvent(new Event(TOUR_EVENT));
}

export default function Tour() {
  const [open, setOpen] = useState(false);
  const [i, setI] = useState(0);
  const track = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let seen = true;
    try {
      seen = localStorage.getItem(TOUR_KEY) !== null;
    } catch {
      /* storage blocked: never force the tour */
    }
    if (!seen && isStandalone()) setOpen(true);
    const replay = () => {
      setI(0);
      setOpen(true);
    };
    window.addEventListener(TOUR_EVENT, replay);
    return () => window.removeEventListener(TOUR_EVENT, replay);
  }, []);

  const close = useCallback(() => {
    try {
      localStorage.setItem(TOUR_KEY, new Date().toISOString());
    } catch {
      /* storage blocked */
    }
    setOpen(false);
  }, []);

  const go = useCallback((n: number) => {
    const el = track.current;
    if (!el) return;
    const k = Math.max(0, Math.min(SLIDES.length - 1, n));
    el.scrollTo({ left: k * el.clientWidth, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    setI(k);
  }, []);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      if (e.key === "ArrowRight") go(i + 1);
      if (e.key === "ArrowLeft") go(i - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, i, go, close]);

  if (!open) return null;
  const last = i === SLIDES.length - 1;
  return (
    <div className={s.layer} role="dialog" aria-modal="true" aria-label="Welcome to FINN">
      <div className={s.top}>
        <span className={s.count} aria-live="polite">
          {i + 1} of {SLIDES.length}
        </span>
        <button type="button" className={s.skip} onClick={close}>
          Skip <X size={16} strokeWidth={2} aria-hidden="true" />
        </button>
      </div>
      <div
        ref={track}
        className={s.track}
        onScroll={(e) => {
          const el = e.currentTarget;
          const k = Math.round(el.scrollLeft / el.clientWidth);
          if (k !== i) setI(k);
        }}
      >
        {SLIDES.map(({ Icon, title, body }, k) => (
          <section key={title} className={s.slide} aria-hidden={k !== i} aria-roledescription="slide" aria-label={`${k + 1} of ${SLIDES.length}`}>
            <span className={s.art} aria-hidden="true">
              <Icon size={30} strokeWidth={1.5} />
            </span>
            <Sketch kind={k} />
            <h2 className={s.title}>{title}</h2>
            <p className={s.body}>{body}</p>
          </section>
        ))}
      </div>
      <div className={s.foot}>
        <div className={s.dots} role="tablist" aria-label="Tour screens">
          {SLIDES.map((sl, k) => (
            <button key={sl.title} type="button" role="tab" aria-selected={k === i} aria-label={`Screen ${k + 1}`} className={s.dot} onClick={() => go(k)} />
          ))}
        </div>
        <button type="button" className={`${s.next} press`} onClick={() => (last ? close() : go(i + 1))}>
          {last ? "Start using FINN" : "Next"}
        </button>
      </div>
    </div>
  );
}
