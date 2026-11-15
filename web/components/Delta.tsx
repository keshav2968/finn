import { ArrowDown, ArrowUp } from "lucide-react";
import { direction, pct } from "@/lib/format";

// A change with an arrow and a sign, so colour is never the only signal. `tone="price"`
// (the default) colours it green or red: only price moves get those colours. Reported
// figures (results, research) pass tone="neutral". `suffix` adds context such as "YoY".
export default function Delta({
  value,
  digits = 2,
  suffix,
  className,
  tone = "price",
}: {
  value: number | null;
  digits?: number;
  suffix?: string;
  className?: string;
  tone?: "price" | "neutral";
}) {
  const dir = direction(value);
  const Icon = dir === "up" ? ArrowUp : dir === "down" ? ArrowDown : null;
  return (
    <span className={`delta ${className ?? ""}`} data-dir={dir} data-tone={tone}>
      {Icon && <Icon size={12} strokeWidth={2.5} aria-hidden="true" />}
      {pct(value, digits)}
      {suffix && <span style={{ fontWeight: 500, opacity: 0.85 }}>&nbsp;{suffix}</span>}
    </span>
  );
}
