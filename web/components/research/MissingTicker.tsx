"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import s from "./research.module.css";

// A /research/SYMBOL link for a ticker with no pre-built page: say so and give the command.
export default function MissingTicker() {
  const path = usePathname() ?? "";
  const m = path.match(/^\/research\/([^/?#]+)/);
  const symbol = m ? decodeURIComponent(m[1]).toUpperCase() : null;
  return (
    <section className={s.empty}>
      {symbol ? (
        <>
          <h2>{symbol} hasn&apos;t been researched yet</h2>
          <p>Research pages are built ahead of time. Run this in the repo, then commit and push:</p>
          <p className={s.cmd}>
            <code>python scripts/build_research.py {symbol}</code>
          </p>
        </>
      ) : (
        <>
          <h2>Page not found</h2>
          <p>That link doesn&apos;t lead anywhere in Finn.</p>
        </>
      )}
      <p>
        <Link href="/research" className={s.inlineLink}>
          All research
        </Link>{" "}
        ·{" "}
        <Link href="/" className={s.inlineLink}>
          Inbox
        </Link>
      </p>
    </section>
  );
}
