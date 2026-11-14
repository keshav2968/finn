// Line icons drawn on a 20px grid with a 1.5px stroke, so they sit with 1px borders.

type P = { size?: number; className?: string };

const base = (size: number) => ({
  width: size,
  height: size,
  viewBox: "0 0 20 20",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
});

export function BellIcon({ size = 20, className }: P) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M5 8.5a5 5 0 0 1 10 0v3.2l1.5 2.3h-13L5 11.7z" />
      <path d="M8.2 16.5a1.9 1.9 0 0 0 3.6 0" />
    </svg>
  );
}

export function CheckIcon({ size = 14, className }: P) {
  return (
    <svg {...base(size)} className={className} strokeWidth={2}>
      <path d="M4.5 10.5l3.5 3.5 7.5-8" />
    </svg>
  );
}

export function ChevronIcon({ size = 16, className }: P) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M7 4.5l5.5 5.5L7 15.5" />
    </svg>
  );
}

export function ExternalIcon({ size = 12, className }: P) {
  return (
    <svg {...base(size)} className={className} strokeWidth={1.75}>
      <path d="M8 4H4.5v11.5H16V12" />
      <path d="M11 3.5h5.5V9M16.5 3.5L9 11" />
    </svg>
  );
}

export function SunIcon({ size = 18, className }: P) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="10" cy="10" r="3.5" />
      <path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.3 4.3l1.4 1.4M14.3 14.3l1.4 1.4M4.3 15.7l1.4-1.4M14.3 5.7l1.4-1.4" />
    </svg>
  );
}

export function MoonIcon({ size = 18, className }: P) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M16 12.2A6.5 6.5 0 0 1 7.8 4a6.5 6.5 0 1 0 8.2 8.2z" />
    </svg>
  );
}

/** Filled triangle for price direction; always shown next to a signed number. */
export function Tri({ dir }: { dir: "up" | "down" | "flat" }) {
  if (dir === "flat") return null;
  return (
    <svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true" style={{ flex: "none" }}>
      <path d={dir === "up" ? "M4 1l3.5 6h-7z" : "M4 7L.5 1h7z"} fill="currentColor" />
    </svg>
  );
}
