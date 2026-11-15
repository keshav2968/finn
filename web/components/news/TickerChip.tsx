import { ArrowDown, ArrowUp } from "lucide-react";
import { day as dayLabel, direction, pct } from "@/lib/format";
import u from "../ui.module.css";

// "INFY ▲ 1.2%": the ticker with the stock's move on the latest session in the snapshot.
export default function TickerChip({ symbol, move, date }: { symbol: string; move: number | null; date: string | null }) {
  const dir = direction(move);
  const Icon = dir === "up" ? ArrowUp : dir === "down" ? ArrowDown : null;
  return (
    <span
      className={u.tick}
      data-dir={dir}
      aria-label={move === null ? symbol : `${symbol}, ${pct(move)} on ${date ? dayLabel(date) : "the last session"}`}
    >
      <span className={u.tickSym}>{symbol}</span>
      {move !== null && (
        <span className={u.tickMove} aria-hidden="true">
          {Icon && <Icon size={11} strokeWidth={2.75} style={{ verticalAlign: "-1px", marginRight: 1 }} />}
          {pct(Math.abs(move), 1).replace("+", "")}
        </span>
      )}
    </span>
  );
}
