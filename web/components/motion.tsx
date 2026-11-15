"use client";

import { useEffect, useRef, useState } from "react";

export function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

const ease = (t: number) => 1 - Math.pow(1 - t, 3);

// Set once the first page has hydrated. The server HTML and that first render always show
// the true figure (never a starting value); count-ups play on numbers that appear after
// that, i.e. when you move between tabs and pages.
let hydrated = false;
export function markHydrated() {
  hydrated = true;
}

/**
 * A number that counts from `from` to `value` when it appears after the first page load
 * (and again whenever it changes). Screen readers get the final figure. With reduced
 * motion it jumps straight to the value.
 */
export function CountUp({
  value,
  from = 0,
  format,
  duration = 700,
  className,
}: {
  value: number;
  from?: number;
  format: (v: number) => string;
  duration?: number;
  className?: string;
}) {
  const [initial] = useState(() => (hydrated ? from : value));
  const [shown, setShown] = useState(initial);
  const last = useRef(initial);
  useEffect(() => {
    const start = last.current;
    if (prefersReducedMotion() || start === value) {
      setShown(value);
      last.current = value;
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - t0) / duration);
      const v = start + (value - start) * ease(t);
      setShown(v);
      if (t < 1) raf = requestAnimationFrame(step);
      else last.current = value;
    };
    raf = requestAnimationFrame(step);
    return () => {
      cancelAnimationFrame(raf);
      last.current = value;
    };
  }, [value, duration]);
  return (
    <span className={className}>
      <span aria-hidden="true">{format(shown)}</span>
      <span className="srOnly">{format(value)}</span>
    </span>
  );
}

/** True once the component has mounted in the browser (for measured charts). */
export function useMounted(): boolean {
  const [m, setM] = useState(false);
  useEffect(() => setM(true), []);
  return m;
}

/** Width of an element, tracked with ResizeObserver. */
export function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(el.clientWidth);
    const ro = new ResizeObserver(([e]) => setW(Math.round(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}
