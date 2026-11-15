"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Bell, ChartCandlestick, Newspaper, ScanSearch } from "lucide-react";
import { UNREAD_ALERTS_EVENT, UNREAD_ALERTS_KEY } from "./badge";
import s from "./shell.module.css";

const TABS = [
  { href: "/", label: "News", Icon: Newspaper, match: (p: string) => p === "/" },
  { href: "/markets", label: "Markets", Icon: ChartCandlestick, match: (p: string) => p.startsWith("/markets") },
  { href: "/research", label: "Research", Icon: ScanSearch, match: (p: string) => p.startsWith("/research") },
  { href: "/alerts", label: "Alerts", Icon: Bell, match: (p: string) => p.startsWith("/alerts") },
];

export default function BottomNav() {
  const path = usePathname() ?? "/";
  const [unread, setUnread] = useState(0);

  // The News and Alerts tabs compute unread alerts with the user's own rules and publish
  // the count; other tabs show the last count published on this device.
  useEffect(() => {
    try {
      setUnread(Number(localStorage.getItem(UNREAD_ALERTS_KEY) ?? 0) || 0);
    } catch {
      /* storage blocked */
    }
    const on = (e: Event) => setUnread((e as CustomEvent<number>).detail);
    window.addEventListener(UNREAD_ALERTS_EVENT, on);
    return () => window.removeEventListener(UNREAD_ALERTS_EVENT, on);
  }, []);

  return (
    <nav className={s.nav} aria-label="Main">
      {TABS.map(({ href, label, Icon, match }) => {
        const active = match(path);
        return (
          <Link key={href} href={href} className={s.tab} aria-current={active ? "page" : undefined} prefetch>
            <span className={s.tabIcon}>
              <Icon size={22} strokeWidth={active ? 2.25 : 1.75} aria-hidden="true" />
              {href === "/alerts" && unread > 0 && (
                <span className={s.tabBadge} aria-label={`${unread} unread`}>
                  {unread > 99 ? "99+" : unread}
                </span>
              )}
            </span>
            <span className={s.tabLabel}>{label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
