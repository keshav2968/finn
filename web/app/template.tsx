// Re-mounts on every navigation, so each tab and stock page fades up as it opens.
export default function Template({ children }: { children: React.ReactNode }) {
  return <div className="pageEnter">{children}</div>;
}
