import { ArrowDown, ArrowUp } from "lucide-react";
import { direction, pct } from "@/lib/format";

// A change, as a soft tinted badge with an arrow and a sign, so colour is never the
// only signal. `suffix` adds context such as "YoY".
export default function Delta({
  value,
  digits = 2,
  suffix,
  className,
}: {
  value: number | null;
  digits?: number;
  suffix?: string;
  className?: string;
}) {
  const dir = direction(value);
  const Icon = dir === "up" ? ArrowUp : dir === "down" ? ArrowDown : null;
  return (
    <span className={`delta ${className ?? ""}`} data-dir={dir}>
      {Icon && <Icon size={12} strokeWidth={2.5} aria-hidden="true" />}
      {pct(value, digits)}
      {suffix && <span style={{ fontWeight: 500, opacity: 0.85 }}>&nbsp;{suffix}</span>}
    </span>
  );
}
