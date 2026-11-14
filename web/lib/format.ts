// Number and date formatting. Indian digit grouping, IST everywhere, and a real minus
// sign (U+2212) so signed figures line up with tabular digits.

const TZ = "Asia/Kolkata";
const MINUS = "−";

const dayFmt = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", timeZone: TZ });
const timeFmt = new Intl.DateTimeFormat("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: TZ });

function grouped(value: number, digits: number): string {
  return new Intl.NumberFormat("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(
    Math.abs(value),
  );
}

export function signed(value: number, digits = 2): string {
  const sign = value > 0 ? "+" : value < 0 ? MINUS : "";
  return `${sign}${grouped(value, digits)}`;
}

export function pct(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined ? "–" : `${signed(value, digits)}%`;
}

export function price(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : `${value < 0 ? MINUS : ""}${grouped(value, 2)}`;
}

/** ₹ crore: no decimals from 100 up, two below. */
export function crore(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  const digits = Math.abs(value) >= 100 ? 0 : 2;
  return `${value < 0 ? MINUS : ""}₹${grouped(value, digits)} cr`;
}

export function times(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : `${value.toFixed(1)}×`;
}

/** "2026-11-12" or an ISO timestamp -> "12 Nov" (IST). */
export function day(value: string): string {
  const d = value.length === 10 ? new Date(`${value}T12:00:00+05:30`) : new Date(value);
  return dayFmt.format(d);
}

/** ISO timestamp -> "13 Nov, 16:30" (IST). */
export function dayTime(value: string): string {
  const d = new Date(value);
  return `${dayFmt.format(d)}, ${timeFmt.format(d)}`;
}

export function direction(value: number | null | undefined): "up" | "down" | "flat" {
  if (value === null || value === undefined || value === 0) return "flat";
  return value > 0 ? "up" : "down";
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** Plain grouped figure for tables whose unit is stated once: no decimals from 100 up. */
export function amount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  const digits = Math.abs(value) >= 100 ? 0 : 2;
  return `${value < 0 ? MINUS : ""}${grouped(value, digits)}`;
}

/** Percentage-point change, e.g. "+0.1 pp". */
export function pp(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : `${signed(value, 1)} pp`;
}

/** "2026-11-23" -> "23 Nov 2026"; anything else is shown as given. */
export function longDate(value: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: TZ }).format(
    new Date(`${value}T12:00:00+05:30`),
  );
}
