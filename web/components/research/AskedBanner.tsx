"use client";

import { useSearchParams } from "next/navigation";
import { MessageCircleQuestion } from "lucide-react";
import s from "./research.module.css";

// The question an "Ask Finn" button carried here. Open-ended answers come later; for now
// the page shows what the company's own filings and calls say.
export default function AskedBanner() {
  const q = useSearchParams().get("q");
  if (!q) return null;
  return (
    <section className={s.asked} role="status">
      <MessageCircleQuestion size={18} strokeWidth={1.75} aria-hidden="true" className={s.askedIcon} />
      <div>
        <p className={s.askedQ}>&ldquo;{q.slice(0, 300)}&rdquo;</p>
        <p className={s.askedNote}>
          Written answers to open questions come next. Below is what the company said on its calls and what its reported
          numbers show, with every quote linked to its source.
        </p>
      </div>
    </section>
  );
}
