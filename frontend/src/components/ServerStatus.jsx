// Stan serwera aplikacji w pasku: frontend odpytuje GET /api/status co 30 s, po powrocie na kartę i po odzyskaniu
// sieci. Na darmowym hostingu backend usypia – rolnik widzi wtedy wprost, że serwer nie odpowiada, zamiast czekać.
import { useEffect, useState } from "react";
import { getStatus } from "../api/client.js";

const EVERY_MS = 30000;

export default function ServerStatus() {
  const [state, setState] = useState({ s: "checking", at: null, info: null });

  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const info = await getStatus();
        if (alive) setState({ s: "ok", at: new Date(), info });
      } catch {
        if (alive) setState((prev) => ({ s: "down", at: new Date(), info: prev.info }));
      }
    };
    check();
    const timer = setInterval(check, EVERY_MS);
    const onVisible = () => { if (document.visibilityState === "visible") check(); };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", check);
    return () => {
      alive = false;
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", check);
    };
  }, []);

  const at = state.at ? state.at.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "";
  const detail = state.s === "down"
    ? `nie odpowiada (sprawdzono o ${at}, ponawiam co 30 s)`
    : state.s === "ok" ? `działa (sprawdzono o ${at})` : "sprawdzam…";
  // Sama ikonka (zielona/czerwona); opis w dymku po najechaniu albo fokusie klawiatury. Przy awarii obok ikonki
  // zostaje krótki napis, żeby problem nie był sygnalizowany wyłącznie kolorem.
  return (
    <span className={`srv srv-${state.s}`} tabIndex={0} role="status" aria-live="polite"
      aria-label={`Status serwera: ${detail}`}>
      <i aria-hidden="true" />
      {state.s === "down" && <span className="srv-text" aria-hidden="true">Brak połączenia</span>}
      <span className="srv-tip" aria-hidden="true"><b>Status serwera</b>{detail}</span>
    </span>
  );
}
