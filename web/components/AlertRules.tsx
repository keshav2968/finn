"use client";

import type { AlertChoices, AlertRules } from "@/lib/types";
import sh from "./sheet.module.css";
import s from "./rules.module.css";

// The user decides what "unusual" means. Choices come from config/app.yaml, defaults from
// push.yaml (via feed.json); the inbox re-runs the alert rules in the browser on every change.
export default function AlertRulesPanel({
  rules,
  defaults,
  choices,
  alertCount,
  windowLabel,
  needsAt,
  onChange,
}: {
  rules: AlertRules;
  defaults: AlertRules;
  choices: AlertChoices;
  alertCount: number;
  windowLabel: string;
  needsAt: number;
  onChange: (next: AlertRules) => void;
}) {
  const set = (patch: Partial<AlertRules>) => onChange({ ...rules, ...patch });
  const toggleCategory = (key: string) =>
    set({
      filing_categories: rules.filing_categories.includes(key)
        ? rules.filing_categories.filter((k) => k !== key)
        : [...rules.filing_categories, key],
    });
  const isDefault = JSON.stringify(normalise(rules)) === JSON.stringify(normalise(defaults));

  return (
    <>
      <h2 className={s.title}>Alert rules</h2>
      <p className={s.lead}>
        What counts as unusual for you. Saved on this device.{" "}
        <strong className={s.count}>
          {alertCount} alert{alertCount === 1 ? "" : "s"} in the last {windowLabel}
        </strong>{" "}
        with these rules.
      </p>

      <Choice
        title="Price move in a day"
        help="Alert when a stock closes up or down by at least this much."
        options={choices.price_move_pct}
        value={rules.price_move_pct}
        format={(v) => `±${v}%`}
        onPick={(v) => set({ price_move_pct: v })}
      />
      <Choice
        title="Volume spike"
        help="Alert when the day's volume is this many times its 20-day average."
        options={choices.volume_ratio}
        value={rules.volume_ratio}
        format={(v) => `${v}×`}
        onPick={(v) => set({ volume_ratio: v })}
      />
      <Choice
        title="Unusual for this stock"
        help="Alert when the move is this many standard deviations of the stock's own daily moves (a 3% day is routine for a small cap, rare for HUL)."
        options={choices.move_z}
        value={rules.move_z}
        format={(v) => `${v}σ`}
        onPick={(v) => set({ move_z: v })}
      />

      <section className={`${sh.section} ${s.group}`}>
        <h3>Filings that alert</h3>
        <p className={sh.note}>
          {rules.filing_min_score === null
            ? "Any filing in a chosen category."
            : `When a filing in a chosen category scores at least ${rules.filing_min_score} in Finn's ranking (Needs attention starts at ${needsAt}).`}
        </p>
        <div className={s.chips} role="group" aria-label="Filing categories that alert">
          {choices.categories.map((c) => (
            <button
              key={c.key}
              type="button"
              className={s.chip}
              aria-pressed={rules.filing_categories.includes(c.key)}
              onClick={() => toggleCategory(c.key)}
            >
              {c.label}
            </button>
          ))}
        </div>
      </section>

      <div className={s.reset}>
        <button type="button" className={sh.link} disabled={isDefault} onClick={() => onChange(defaults)}>
          {isDefault ? "Using the default rules" : "Reset to defaults"}
        </button>
      </div>
    </>
  );
}

function Choice({
  title,
  help,
  options,
  value,
  format,
  onPick,
}: {
  title: string;
  help: string;
  options: number[];
  value: number | null;
  format: (v: number) => string;
  onPick: (v: number | null) => void;
}) {
  return (
    <section className={`${sh.section} ${s.group}`}>
      <h3>{title}</h3>
      <p className={sh.note}>{help}</p>
      <div className={s.chips} role="radiogroup" aria-label={title}>
        {options.map((v) => (
          <button key={v} type="button" role="radio" aria-checked={value === v} className={s.chip} onClick={() => onPick(v)}>
            <span className="num">{format(v)}</span>
          </button>
        ))}
        <button type="button" role="radio" aria-checked={value === null} className={s.chip} onClick={() => onPick(null)}>
          Off
        </button>
      </div>
    </section>
  );
}

function normalise(r: AlertRules) {
  return { ...r, filing_categories: [...r.filing_categories].sort() };
}

/** A saved rules object from an older version, or a broken one, falls back to the defaults. */
export function validRules(saved: unknown, defaults: AlertRules): AlertRules {
  if (!saved || typeof saved !== "object") return defaults;
  const r = saved as Partial<AlertRules>;
  const num = (v: unknown, d: number | null) => (v === null || typeof v === "number" ? (v as number | null) : d);
  return {
    price_move_pct: num(r.price_move_pct, defaults.price_move_pct),
    volume_ratio: num(r.volume_ratio, defaults.volume_ratio),
    move_z: num(r.move_z, defaults.move_z),
    filing_categories: Array.isArray(r.filing_categories) ? r.filing_categories.filter((k) => typeof k === "string") : defaults.filing_categories,
    filing_min_score: defaults.filing_min_score,
  };
}
