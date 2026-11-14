"use client";

import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import s from "./sheet.module.css";

// Bottom sheet for a card's details. Locks the page scroll while open so there is only
// ever one scrolling surface; Escape, the scrim and the close button dismiss it.
export default function Sheet({
  open,
  label,
  onClose,
  children,
  footer,
}: {
  open: boolean;
  label: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const opener = document.activeElement as HTMLElement | null;
    closeRef.current?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
      opener?.focus?.({ preventScroll: true });
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className={s.layer}>
      <div className={s.scrim} onClick={onClose} aria-hidden="true" />
      <div className={s.sheet} role="dialog" aria-modal="true" aria-label={label}>
        <div className={s.grab} aria-hidden="true" />
        <button ref={closeRef} type="button" className={s.close} onClick={onClose} aria-label="Close">
          <X size={20} strokeWidth={1.75} />
        </button>
        <div className={s.body}>{children}</div>
        {footer && <div className={s.footer}>{footer}</div>}
      </div>
    </div>
  );
}
