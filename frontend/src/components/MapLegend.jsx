// Legenda mapy (styl 6.15): biała karta nad mapą po prawej. Znaczniki mają różne kształty, nie tylko kolory.
import { LEVEL } from "../lib/present.js";

export const KINDS = {
  ditch: "rów (miejsce na zastawkę)",
  pond: "zagłębienie: miejsce na oczko",
  wet_spot: "płytkie zastoisko wody",
  outlet: "tędy woda odpływa z działki",
  low: "najniższy punkt działki",
};

export default function MapLegend({ level, terrain }) {
  if (!level) return null;
  const present = new Set((terrain?.markers || []).map((m) => m.kind));
  return (
    <div className="maplegend" role="group" aria-label="Legenda mapy">
      <div><i style={{ borderColor: LEVEL[level].color }} />działka: {LEVEL[level].label.toLowerCase()}</div>
      {terrain?.layers && <div><i style={{ borderColor: "#5FD3FF" }} />tędy spływa woda</div>}
      {Object.entries(KINDS).filter(([k]) => present.has(k)).map(([k, label]) => (
        <div key={k}><span className={`mk mk-${k} lg`} aria-hidden="true" />{label}</div>
      ))}
    </div>
  );
}
