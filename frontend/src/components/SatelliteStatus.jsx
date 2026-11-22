// Pasek nad wynikiem: widać, że porównanie ze zdjęciami satelitarnymi z lat ubiegłych (openEO) właśnie się liczy
// i że wynik uzupełni się sam (App.jsx odpytuje GET /api/baseline co 15 s). Po zakończeniu krótko: „gotowe”.
import { useEffect, useState } from "react";

function elapsed(since) {
  const m = Math.floor((Date.now() - since) / 60000);
  return m < 1 ? "Zaczęliśmy przed chwilą" : m === 1 ? "Trwa od 1 minuty" : `Trwa od ${m} min`;
}

export default function SatelliteStatus({ since, done }) {
  const [, tick] = useState(0);
  useEffect(() => {
    if (!since) return undefined;
    const t = setInterval(() => tick((n) => n + 1), 15000);
    return () => clearInterval(t);
  }, [since]);

  if (since) {
    return (
      <div className="satstat" role="status" aria-live="polite">
        <span className="satspin" aria-hidden="true" />
        <span>
          <b>Liczymy porównanie ze zdjęciami satelitarnymi z lat ubiegłych</b>
          <small>{elapsed(since)}, zwykle 3–6 minut. Wynik uzupełni się sam – nie trzeba nic klikać.</small>
        </span>
      </div>
    );
  }
  if (done) {
    return (
      <div className="satstat done" role="status" aria-live="polite">
        <span className="satok" aria-hidden="true">✓</span>
        <span><b>Porównanie satelitarne gotowe</b><small>Wynik i pewność zostały zaktualizowane.</small></span>
      </div>
    );
  }
  return null;
}
