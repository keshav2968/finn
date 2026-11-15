import MissingTicker from "@/components/research/MissingTicker";
import s from "@/components/research/research.module.css";

export default function NotFound() {
  return (
    <div className={s.page}>
      <header className={s.head}>
        <p className={s.kicker}>Research</p>
      </header>
      <MissingTicker />
    </div>
  );
}
