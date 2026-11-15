// Shown while a tab's page is on its way (first visit to a tab, slow connection).
export default function Skeleton() {
  return (
    <div style={{ padding: "calc(env(safe-area-inset-top) + 16px) 16px 0" }} aria-busy="true" aria-label="Loading">
      <span className="skel" style={{ width: 140, height: 32 }} />
      <span className="skel" style={{ width: "70%", height: 14, marginTop: 12 }} />
      <span className="skel" style={{ width: "100%", height: 36, marginTop: 20, borderRadius: 999 }} />
      {[0, 1, 2].map((i) => (
        <span key={i} className="skel" style={{ width: "100%", height: 132, marginTop: 14, borderRadius: 18, opacity: 1 - i * 0.25 }} />
      ))}
    </div>
  );
}
