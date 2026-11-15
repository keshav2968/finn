"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";
import s from "./research.module.css";

type Known = { symbol: string; name: string };

// Research pages are built ahead of time, one per known ticker. A ticker that has not been
// run gets the command to run it instead of a broken page.
export default function TickerSearch({ known }: { known: Known[] }) {
  const router = useRouter();
  const [value, setValue] = useState("");
  const [missing, setMissing] = useState<string | null>(null);

  function go(e: React.FormEvent) {
    e.preventDefault();
    const q = value.trim();
    if (!q) return;
    const up = q.toUpperCase().replace(/^NSE:/, "").replace(/\s+/g, "");
    const hit =
      known.find((k) => k.symbol === up) ??
      (q.length >= 3 ? known.filter((k) => k.name.toLowerCase().includes(q.toLowerCase())) : []).at(0);
    if (hit) {
      setMissing(null);
      router.push(`/research/${encodeURIComponent(hit.symbol)}`);
      return;
    }
    setMissing(/^[A-Z0-9&-]{1,20}$/.test(up) ? up : "?");
  }

  return (
    <div className={s.search}>
      <form onSubmit={go} className={s.searchForm} role="search">
        <label htmlFor="ticker" className={s.srOnly}>
          NSE ticker or company name
        </label>
        <Search size={18} strokeWidth={1.75} aria-hidden="true" className={s.searchIcon} />
        <input
          id="ticker"
          className={s.searchInput}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setMissing(null);
          }}
          placeholder="Any NSE ticker, e.g. TCS"
          autoCapitalize="characters"
          autoComplete="off"
          spellCheck={false}
          enterKeyHint="go"
        />
        <button type="submit" className={s.searchGo}>
          Search
        </button>
      </form>
      {missing && (
        <div className={s.searchMiss} role="status">
          {missing === "?" ? (
            <p>That doesn&apos;t look like an NSE ticker. Try the symbol, e.g. TCS or HDFCBANK.</p>
          ) : (
            <>
              <p>
                <strong>{missing}</strong> hasn&apos;t been researched yet. Research is built ahead of time from screener.in and the
                company&apos;s call transcripts. Run this in the repo, then commit and push:
              </p>
              <p className={s.cmd}>
                <code>python scripts/build_research.py {missing}</code>
              </p>
              <p>The page appears here after the next deploy.</p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
