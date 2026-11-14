"use client";

import { useRef, useState } from "react";
import { Check } from "lucide-react";
import s from "./cards.module.css";

// A row you tap to open and swipe left to clear. Vertical scrolling stays native
// (touch-action: pan-y); a gesture only becomes a swipe once it is clearly horizontal.
const CLEAR_AT = 0.32; // fraction of the row width

export default function SwipeRow({
  label,
  onOpen,
  onDone,
  children,
}: {
  label: string;
  onOpen: () => void;
  onDone: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const g = useRef({ id: -1, x: 0, y: 0, mode: "idle" as "idle" | "swipe" | "scroll", dx: 0, swiped: false });
  const [dx, setDx] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [leaving, setLeaving] = useState(false);

  const width = () => ref.current?.offsetWidth ?? 360;
  const armed = -dx > width() * CLEAR_AT;

  function down(e: React.PointerEvent) {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    g.current = { id: e.pointerId, x: e.clientX, y: e.clientY, mode: "idle", dx: 0, swiped: false };
  }

  function move(e: React.PointerEvent) {
    const st = g.current;
    if (e.pointerId !== st.id || st.mode === "scroll") return;
    const mx = e.clientX - st.x;
    const my = e.clientY - st.y;
    if (st.mode === "idle") {
      if (Math.abs(mx) > 10 && Math.abs(mx) > Math.abs(my) * 1.3) {
        st.mode = "swipe";
        ref.current?.setPointerCapture(e.pointerId);
        setDragging(true);
      } else if (Math.abs(my) > 10) {
        st.mode = "scroll";
        return;
      } else return;
    }
    const next = Math.min(0, mx);
    st.dx = next;
    setDx(next);
  }

  function up(e: React.PointerEvent) {
    const st = g.current;
    if (e.pointerId !== st.id) return;
    if (st.mode === "swipe") {
      st.swiped = true;
      setDragging(false);
      if (-st.dx > width() * CLEAR_AT) {
        setLeaving(true);
        setDx(-width());
        window.setTimeout(onDone, 200);
      } else {
        setDx(0);
      }
    }
    st.mode = "idle";
    st.id = -1;
  }

  function cancel() {
    g.current.mode = "idle";
    g.current.id = -1;
    setDragging(false);
    setDx(0);
  }

  return (
    <div className={s.swipe} data-leaving={leaving || undefined}>
      <div className={s.swipeAction} data-armed={armed || undefined} aria-hidden="true">
        <Check size={18} strokeWidth={2} />
        <span>Done</span>
      </div>
      <div
        ref={ref}
        role="button"
        tabIndex={0}
        aria-label={label}
        className={s.row}
        style={{ transform: dx ? `translate3d(${dx}px,0,0)` : undefined, transition: dragging ? "none" : undefined }}
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={up}
        onPointerCancel={cancel}
        onClick={() => {
          if (g.current.swiped) {
            g.current.swiped = false;
            return;
          }
          onOpen();
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onOpen();
          }
        }}
      >
        {children}
      </div>
    </div>
  );
}
