// Stany panelu bez wyniku (styl 6.4): start, ładowanie z krokami, błąd.
import { useEffect, useState } from "react";
import { listCached } from "../api/client.js";
import { fmt } from "../lib/present.js";

export function Welcome({ onOpenSaved }) {
  const [items, setItems] = useState([]);
  useEffect(() => { listCached().then(setItems).catch(() => setItems([])); }, []);
  return (
    <div className="pi welcome">
      <h1>Czy Twojemu polu brakuje wody?</h1>
      <p>Wpisz u góry numer działki, obręb i numer albo adres – albo kliknij swoją działkę na mapie. Wybierz uprawę i daty, a potem „Sprawdź działkę”.</p>
      <ul className="howto">
        <li><span aria-hidden="true"><svg viewBox="0 0 20 20" width="20" height="20"><path d="M10 2c3 3.6 5.4 6.6 5.4 9.4a5.4 5.4 0 0 1-10.8 0C4.6 8.6 7 5.6 10 2Z" fill="currentColor" /></svg></span>ile wody zostało w glebie</li>
        <li><span aria-hidden="true"><svg viewBox="0 0 20 20" width="20" height="20"><circle cx="10" cy="10" r="7.5" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M8 7.6a2.2 2.2 0 1 1 3.2 2c-.8.4-1.2.9-1.2 1.8M10 14v.3" stroke="currentColor" strokeWidth="2" fill="none" strokeLinecap="round" /></svg></span>dlaczego jej brakuje</li>
        <li><span aria-hidden="true"><svg viewBox="0 0 20 20" width="20" height="20"><path d="M4 10.5 8 14.5 16 5.5" stroke="currentColor" strokeWidth="2.4" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg></span>co możesz zrobić – najpierw zatrzymać wodę na polu</li>
      </ul>
      {items.length > 0 && (
        <>
          <h2 className="sec-title">Działki przykładowe <small>bez czekania, z zapisanych danych</small></h2>
          <div className="demo">
            {items.map((it) => (
              <button key={it.id} type="button" onClick={() => onOpenSaved(it.id)}>
                <span><b>Działka {it.number}, obręb {it.obreb}</b><br /><small>{it.gmina}, {fmt(it.area_ha, 2)} ha</small></span>
                <small>{it.id}</small>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

const STEPS = ["Działka", "Pogoda z 10 lat", "Gleba", "Teren i wody", "Zdjęcia satelitarne", "Wynik i działania"];

/** Kroki ładowania: sygnał postępu (przełączane co 2,6 s), nie pomiar. Ostatni krok czeka na wynik. */
export function Loading({ stage }) {
  const [tick, setTick] = useState(0);
  const [secs, setSecs] = useState(0);
  useEffect(() => {
    const a = setInterval(() => setTick((x) => x + 1), 2600);
    const b = setInterval(() => setSecs((x) => x + 1), 1000);
    return () => { clearInterval(a); clearInterval(b); };
  }, []);
  // etap z aplikacji ma pierwszeństwo: działka znaleziona → co najmniej krok 2; liczenie rad → ostatni krok
  const base = stage === "recommend" ? STEPS.length - 1 : stage === "context" ? 1 : 0;
  const now = stage === "recommend" ? base : Math.min(STEPS.length - 2, Math.max(base, tick));
  return (
    <div className="pi">
      <h1 className="load-h">Sprawdzam działkę…</h1>
      <p className="small muted">{secs} s – zwykle 5–20 s, z zapisanych danych natychmiast.</p>
      <ul className="loading-list">
        {STEPS.map((s, i) => (
          <li key={s} className={i < now ? "done" : i === now ? "now" : ""}><span className="dot" aria-hidden="true" />{s}</li>
        ))}
      </ul>
    </div>
  );
}

export function ErrorState({ message, hasLast, onBack, onOpenSaved }) {
  return (
    <div className="pi">
      <h1 className="load-h">Nie udało się sprawdzić działki</h1>
      <p className="err" role="alert">{message}</p>
      <p className="small muted">Sprawdź numer (wzór: 046101_1.0445.7) albo kliknij działkę na mapie.</p>
      {hasLast && <button type="button" className="sbtn" onClick={onBack}>Wróć do ostatniego wyniku</button>}
      <Welcome onOpenSaved={onOpenSaved} />
    </div>
  );
}
