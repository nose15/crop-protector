// Szklany pasek nad mapą (styl 6.1–6.3): marka, wyszukiwarka z polami „etykieta nad wartością”, przycisk główny,
// dostępność (A−, A+, wysoki kontrast) i link do opisu metody.
import { forwardRef } from "react";
import { BrandMark, ContrastIcon } from "./Icons.jsx";
import DateField from "./DateField.jsx";
import { CROPS, SOWN, iso, shiftIsoYear } from "../lib/present.js";

const Topbar = forwardRef(function Topbar(
  { q, onQ, request, onRequest, onSubmit, busy, textSize, onTextSize, contrast, onContrast, onInfo, locked, onUnlock }, ref,
) {
  const set = (patch) => onRequest({ ...request, ...patch });
  const today = iso(new Date());
  const minFrom = iso(new Date(Date.now() - 3660 * 864e5));
  const maxTo = shiftIsoYear(request.range.from, 2);
  const showSow = SOWN.has(request.crop) || request.sowing_date;

  return (
    <header className="topbar" ref={ref}>
      <a className="brand" href="./" aria-label="Zatrzymaj wodę – strona startowa">
        <span className="brand-mark"><BrandMark /></span>
        <span className="brand-text"><b>Zatrzymaj wodę</b><small>woda na Twojej działce</small></span>
      </a>

      <form className="search" autoComplete="off" aria-label="Sprawdzenie działki"
        onSubmit={(e) => { e.preventDefault(); onSubmit(); }}>
        {locked ? (
          <div className="field grow locked">
            <span>Twoja działka</span>
            <span className="lockrow">
              <svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"><rect x="3" y="7" width="10" height="7.5" rx="1.6" fill="currentColor" /><path d="M5.2 7V5.2a2.8 2.8 0 0 1 5.6 0V7" stroke="currentColor" strokeWidth="1.6" fill="none" /></svg>
              <b>Działka {locked.number}, obręb {locked.obreb}</b>
              <button type="button" className="linkbtn" onClick={onUnlock}>Zmień działkę</button>
            </span>
          </div>
        ) : (
          <label className="field grow">
            <span>Działka lub adres</span>
            <input value={q} onChange={(e) => onQ(e.target.value)} spellCheck="false"
              placeholder="np. 046101_1.0445.7, Krzywiń 134/2 albo Krzywiń, Rynek 1"
              aria-describedby="search-help" />
            <span id="search-help" className="sr-only">Wpisz numer działki albo adres. Możesz też kliknąć działkę na mapie.</span>
          </label>
        )}
        <label className="field">
          <span>Uprawa</span>
          <select value={request.crop} onChange={(e) => set({ crop: e.target.value, sowing_date: null })}>
            {CROPS.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
          </select>
        </label>
        <label className="field">
          <span>Od</span>
          <DateField value={request.range.from} min={minFrom} max={today}
            onChange={(from) => {
              let to = request.range.to;
              if (/^\d{4}-\d{2}-\d{2}$/.test(from)) {
                const limit = shiftIsoYear(from, 2);
                if (to < from) to = from;
                else if (to > limit) to = limit;
              }
              set({ range: { from, to } });
            }} />
        </label>
        <label className="field">
          <span>Do</span>
          <DateField value={request.range.to} min={request.range.from} max={maxTo}
            onChange={(to) => set({ range: { ...request.range, to } })} />
        </label>
        <label className="field" hidden={!showSow}>
          <span>Siew <em>(jeśli znasz)</em></span>
          <DateField value={request.sowing_date || ""} allowEmpty
            onChange={(isoDate) => set({ sowing_date: isoDate })} />
        </label>
        <button type="submit" className="btn-go" disabled={busy}>{busy ? "Sprawdzam…" : "Sprawdź działkę"}</button>
      </form>

      <div className="tools">
        <div className="a11y" role="group" aria-label="Wygląd tekstu">
          <button type="button" className="tbtn" aria-label="Mniejszy tekst" disabled={textSize <= 1}
            onClick={() => onTextSize(textSize - 1)}>A−</button>
          <button type="button" className="tbtn" aria-label="Większy tekst" disabled={textSize >= 3}
            onClick={() => onTextSize(textSize + 1)}>A+</button>
          <button type="button" className="tbtn" aria-pressed={contrast} aria-label="Wysoki kontrast" onClick={onContrast}>
            <ContrastIcon />
          </button>
        </div>
        <nav className="nav" aria-label="Informacje">
          <button type="button" className="navlink" onClick={onInfo}>Jak liczymy</button>
        </nav>
      </div>
    </header>
  );
});

export default Topbar;
