// Budzenie backendu na Renderze: darmowa usługa usypia po ok. 15 min bez ruchu, a pierwsze zapytanie po uśpieniu
// trwa wtedy kilkadziesiąt sekund. Gdy strona działa LOKALNIE (localhost / 127.0.0.1), od razu i potem co 10 min
// wysyłamy lekkie GET /api/health do backendu na Renderze, żeby nie zasypiał, dopóki strona jest otwarta.
// Na innych adresach (np. na samym Renderze) nic nie robimy. Adres: VITE_KEEPALIVE_URL (pusty = wyłączone).
import { useEffect } from "react";

const DEFAULT_URL = "https://zatrzymaj-wode-hacknation.onrender.com";
const EVERY_MS = 10 * 60 * 1000;

function target() {
  const env = import.meta.env.VITE_KEEPALIVE_URL;
  const url = (env === undefined ? DEFAULT_URL : env).trim().replace(/\/+$/, "");
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);
  return local && url ? `${url}/api/health` : null;
}

export function useKeepAwake() {
  useEffect(() => {
    const url = target();
    if (!url) return undefined;
    const ping = () => fetch(url, { cache: "no-store" }).catch(() => { /* uśpiony albo offline – spróbujemy za 10 min */ });
    ping();
    const timer = setInterval(ping, EVERY_MS);
    return () => clearInterval(timer);
  }, []);
}
