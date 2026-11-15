import s from "./splash.module.css";

// A launch screen of about three and a half seconds: FINN's mark and name, with a price line
// drawing itself, dots popping along it and faint dots rising. Pure CSS; it fades out on its
// own, and a tap skips it (the layout's inline script listens). Shown once per visit; under
// reduced motion it holds still.

// A decorative line (not data): a few swings that end higher, like a session that closed up.
const PTS = [
  [0, 70], [40, 62], [80, 74], [120, 52], [160, 58], [200, 40], [240, 50], [280, 30], [320, 36], [360, 18],
] as const;
const LINE = PTS.map(([x, y], i) => `${i ? "L" : "M"}${x} ${y}`).join("");

export default function Splash() {
  return (
    <div className={s.splash} aria-hidden="true" data-splash-el="">
      <div className={s.stage}>
        <svg className={s.mark} viewBox="0 0 64 64" width="76" height="76">
          <rect width="64" height="64" rx="16" fill="#17151d" />
          <path d="M21 46V18h22M21 32h17" fill="none" stroke="#f3f1f7" strokeWidth="6" strokeLinecap="square" className={s.letter} />
          <rect x="40" y="40" width="6" height="6" rx="1" fill="#9a82ff" className={s.dot} />
        </svg>
        <p className={s.name}>FINN</p>
        <p className={s.tag}>What changed in your portfolio, and why it matters.</p>
      </div>

      <svg className={s.chart} viewBox="-10 0 380 90" preserveAspectRatio="none">
        <path d={LINE} pathLength={100} className={s.line} />
        {PTS.filter((_, i) => i % 3 === 0).map(([x, y], i) => (
          <circle key={x} cx={x} cy={y} r="3" className={s.node} style={{ animationDelay: `${300 + i * 520}ms` }} />
        ))}
        <circle cx={PTS[PTS.length - 1][0]} cy={PTS[PTS.length - 1][1]} r="4" className={s.live} />
      </svg>

      <div className={s.drift}>
        {Array.from({ length: 14 }, (_, i) => (
          <span key={i} style={{ left: `${(i * 37) % 100}%`, animationDelay: `${(i % 7) * 260}ms`, animationDuration: `${1800 + (i % 4) * 320}ms` }} />
        ))}
      </div>
    </div>
  );
}
