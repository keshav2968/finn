import { longDate } from "@/lib/format";
import s from "./shell.module.css";

// On every tab. Data sources are named in words only. Company logos identify the holdings and
// are served from FINN's own domain; nothing implies affiliation with any company or source.
export default function Footer({ snapshotAt, pricesAsOf }: { snapshotAt: string; pricesAsOf: string | null }) {
  return (
    <footer className={s.footer}>
      <p>
        Data: BSE India (filings) · Yahoo Finance (end-of-day prices) · screener.in (fundamentals and call transcripts).
        Snapshot {snapshotAt ? longDate(snapshotAt.slice(0, 10)) : "date unknown"}
        {pricesAsOf ? `, prices to the ${longDate(pricesAsOf)} close` : ""}.
      </p>
      <p>Not investment advice. FINN is a prototype and isn&apos;t affiliated with any of these sources.</p>
      <p>Company logos are trademarks of their respective owners, shown for identification only.</p>
      <p className={s.copy}>© 2026 FINN · built by Keshav</p>
    </footer>
  );
}
