import s from "./splash.module.css";

// A one-second launch screen: FINN's mark and name while the first screen settles, with a
// price line drawing itself and a few dots travelling along it. Pure CSS, no JavaScript and
// nothing to tap: it fades out on its own and never blocks the app. Shown once per visit
// (the inline script in the layout marks the session); under reduced motion it holds still
// and fades sooner.

// A decorative line (not data): a few swings that end higher, like a session that closed up.
const PTS = [
  [0, 70], [40, 62], [80, 74], [120, 52], [160, 58], [200, 40], [240, 50], [280, 30], [320, 36], [360, 18],
] as const;
const LINE = PTS.map(([x, y], i) => `${i ? "L" : "M"}${x} ${y}`).join("");

export default function Splash() {
  return (
    <div className={s.splash} aria-hidden="true">
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
          <circle key={x} cx={x} cy={y} r="3" className={s.node} style={{ animationDelay: `${240 + i * 150}ms` }} />
        ))}
        <circle cx={PTS[PTS.length - 1][0]} cy={PTS[PTS.length - 1][1]} r="4" className={s.live} />
      </svg>

      <div className={s.drift}>
        {Array.from({ length: 14 }, (_, i) => (
          <span key={i} style={{ left: `${(i * 37) % 100}%`, animationDelay: `${(i % 5) * 90}ms`, animationDuration: `${900 + (i % 4) * 180}ms` }} />
        ))}
      </div>
    </div>
  );
}
