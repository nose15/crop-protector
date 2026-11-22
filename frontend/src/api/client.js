// Klient API. Backend jest bezstanowy: ParcelContext trzymamy w stanie Reacta i odsyłamy w całości.

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

// Adres backendu: VITE_API_URL przy budowaniu (np. osobna usługa na Render; sama nazwa hosta też działa),
// pusty = ten sam adres co strona (lokalnie proxy Vite, albo backend serwujący frontend).
// Wartość bez kropki (np. samo „zatrzymaj-wode-hacknation” zamiast pełnego hosta) to błąd konfiguracji:
// ignorujemy ją i wołamy ten sam adres, z którego wczytała się strona.
const ENV_BASE = (import.meta.env.VITE_API_URL || "").trim().replace(/\/+$/, "");
const RAW_BASE = ENV_BASE.includes(".") ? ENV_BASE : "";
export const API_BASE = RAW_BASE && !/^https?:\/\//.test(RAW_BASE) ? `https://${RAW_BASE}` : RAW_BASE;

async function call(path, options = {}) {
  let res;
  try {
    res = await fetch(API_BASE + path, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
  } catch {
    // adres w komunikacie ułatwia diagnozę wdrożenia (np. zły VITE_API_URL albo uśpiony backend)
    throw new ApiError(0, "network", `Brak połączenia z serwerem aplikacji (${API_BASE || window.location.origin}${path.split("?")[0]}). `
      + "Spróbuj ponownie za chwilę – serwer mógł się dopiero uruchamiać.");
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const d = body?.detail;
    const message = typeof d === "object" && d ? d.message : d || `Błąd serwera (${res.status}).`;
    throw new ApiError(res.status, d?.error || "http", message);
  }
  return body;
}

/** @returns {Promise<import("./shapes.js").Parcel>} */
export function getParcel({ q, lat, lon }) {
  const p = new URLSearchParams(q ? { q } : { lat, lon });
  return call(`/api/parcel?${p}`);
}

/** @returns {Promise<import("./shapes.js").ParcelContext>} */
export function getContext(parcel, asOf = null, refresh = false) {
  return call(`/api/context${refresh ? "?refresh=true" : ""}`, { method: "POST", body: JSON.stringify({ parcel, as_of: asOf }) });
}

/** Działki zapisane w cache backendu (prezentacja bez zapytań do usług). */
export function listCached() {
  return call("/api/cache");
}

export function getCached(id) {
  return call(`/api/cache/${encodeURIComponent(id)}`);
}

// Kontekst zapisany w cache wysyłamy jako odwołanie (kilkaset kB mniej w każdą stronę).
export function recommend(context, request) {
  const body = context.cache?.ref ? { context_ref: context.cache.ref, request } : { context, request };
  return call("/api/recommend", { method: "POST", body: JSON.stringify(body) });
}

/** Raport PDF z gotowego wyniku: backend składa plik, przeglądarka go zapisuje. Zwraca nazwę pliku. */
export async function downloadReportPdf(result, parcel) {
  let res;
  try {
    res = await fetch(API_BASE + "/api/report.pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ result, parcel }),
    });
  } catch {
    throw new ApiError(0, "network", "Brak połączenia z serwerem aplikacji. Spróbuj ponownie za chwilę.");
  }
  if (!res.ok) throw new ApiError(res.status, "http", `Nie udało się przygotować PDF (błąd ${res.status}).`);
  const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "")?.[1] || `raport-${parcel?.id || "dzialka"}.pdf`;
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return name;
}

export function summarize(result) {
  return call("/api/summary", { method: "POST", body: JSON.stringify(result) });
}
