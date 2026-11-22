import { useEffect, useMemo, useRef, useState } from "react";
import { getCached, getContext, getParcel, recommend } from "./api/client.js";
import Topbar from "./components/Topbar.jsx";
import MapView from "./components/MapView.jsx";
import MapLegend from "./components/MapLegend.jsx";
import ResultView from "./components/ResultView.jsx";
import { ErrorState, Loading, Welcome } from "./components/PanelStates.jsx";
import ScienceSources from "./components/ScienceSources.jsx";
import { defaultRequest, iso, seasonNote, verdict } from "./lib/present.js";

// Styl „Pole z lotu ptaka”: mapa na cały ekran, szklany pasek z wyszukiwarką, panel „najpierw krótko, szczegóły na żądanie”.
// Dwa widoki:
//  - szukanie: numer albo kliknięcie mapy (tylko ULDK, podgląd), panel startowy z działkami przykładowymi;
//  - zablokowanie na działce: „Sprawdź działkę” = dane działki (cache albo źródła) → rady; mapa trzyma się działki,
//    „Zmień działkę” wraca do szukania.

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* okno prywatne */ } },
};

export default function App() {
  const [q, setQ] = useState("");
  const [request, setRequest] = useState(defaultRequest);
  const [preview, setPreview] = useState(null);
  const [parcel, setParcel] = useState(null);
  const [locked, setLocked] = useState(false);       // widok zablokowany na wybranej działce
  const [context, setContext] = useState(null);
  const [result, setResult] = useState(null);
  const [last, setLast] = useState(null);           // ostatni udany wynik (powrót z błędu)
  const [stage, setStage] = useState(null);         // null | "parcel" | "context" | "recommend"
  const [error, setError] = useState(null);
  const [focus, setFocus] = useState(null);
  const [flyVersion, setFlyVersion] = useState(0);
  const [textSize, setTextSize] = useState(() => Math.min(3, Math.max(1, Number(store.get("kowr-text")) || 1)));
  const [contrast, setContrast] = useState(() => store.get("kowr-contrast") === "high");
  const [info, setInfo] = useState(false);
  const seq = useRef(0);
  const contextCache = useRef(new Map());
  const topRef = useRef(null);
  const closeRef = useRef(null);

  // dostępność: rozmiar tekstu (17/19/21 px) i wysoki kontrast na <html>, zapamiętane w przeglądarce
  useEffect(() => {
    document.documentElement.dataset.text = String(textSize);
    store.set("kowr-text", String(textSize));
  }, [textSize]);
  useEffect(() => {
    document.documentElement.dataset.contrast = contrast ? "high" : "";
    store.set("kowr-contrast", contrast ? "high" : "");
  }, [contrast]);
  // wysokość paska → odstęp panelu i kontrolek mapy
  useEffect(() => {
    if (!topRef.current || !window.ResizeObserver) return undefined;
    const ro = new ResizeObserver(() => {
      const h = topRef.current?.getBoundingClientRect().height;
      if (h && window.innerWidth > 900) document.documentElement.style.setProperty("--top-h", `${Math.round(h)}px`);
    });
    ro.observe(topRef.current);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    if (!info) return undefined;
    closeRef.current?.focus();
    const esc = (e) => { if (e.key === "Escape") setInfo(false); };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [info]);

  async function contextFor(p, asOf = null) {
    const key = `${p.id}|${asOf || iso(new Date())}`;
    if (!contextCache.current.has(key)) contextCache.current.set(key, await getContext(p, asOf));
    return contextCache.current.get(key);
  }

  async function analyse(p, ctx, req, my) {
    setStage("recommend");
    try {
      return { ctx, res: await recommend(ctx, req) };
    } catch (e) {
      if (e.code !== "meteo_range") throw e;
      // wybrana data wymaga innych 10 lat pogody: dane działki dla tej daty i jeszcze raz
      setStage("context");
      const ctx2 = await contextFor(p, req.range.from);
      if (my !== seq.current) return null;
      setStage("recommend");
      return { ctx: ctx2, res: await recommend(ctx2, req) };
    }
  }

  async function check(given = null, givenCtx = null) {
    const my = ++seq.current;
    setError(null);
    setFocus(null);
    try {
      let p = given;
      if (!p) {
        setStage("parcel");
        if (q.trim()) p = await getParcel({ q: q.trim() });
        else if (preview) p = preview;
        else throw new Error("Wpisz numer działki albo kliknij swoją działkę na mapie.");
      }
      if (my !== seq.current) return;
      setLocked(true);
      const changed = !parcel || parcel.id !== p.id;
      const req = changed ? { ...request, answers: { ...request.answers, sites: {} } } : request;
      if (changed) setRequest(req);
      setParcel(p);
      setPreview(null);
      setQ(p.id);
      setStage("context");
      const ctx = givenCtx || await contextFor(p);
      if (my !== seq.current) return;
      const out = await analyse(p, ctx, req, my);
      if (!out || my !== seq.current) return;
      setContext(out.ctx);
      setResult(out.res);
      setLast({ parcel: p, context: out.ctx, result: out.res });
      setFlyVersion((v) => v + 1);
    } catch (e) {
      if (my === seq.current) { setError(e.message); setResult(null); }
    } finally {
      if (my === seq.current) setStage(null);
    }
  }

  async function openSaved(id) {
    const my = ++seq.current;
    setError(null);
    setStage("context");
    try {
      const ctx = await getCached(id);
      if (my !== seq.current) return;
      contextCache.current.set(`${ctx.parcel.id}|${ctx.as_of}`, ctx);
      await check(ctx.parcel, ctx);
    } catch (e) {
      if (my === seq.current) { setError(e.message); setStage(null); }
    }
  }

  function unlock() {
    ++seq.current;                       // porzucamy trwające pobieranie
    setLocked(false);
    setStage(null);
    setPreview(parcel);                  // obrys i dymek „Sprawdź tę działkę” zostają na mapie
    setResult(null);
    setError(null);
    setFocus(null);
    setQ("");
  }

  async function recompute(req = request) {
    if (!parcel || !context) return;
    const my = ++seq.current;
    setError(null);
    try {
      const out = await analyse(parcel, context, req, my);
      if (!out || my !== seq.current) return;
      setContext(out.ctx);
      setResult(out.res);
    } catch (e) {
      if (my === seq.current) setError(e.message);
    } finally {
      if (my === seq.current) setStage(null);
    }
  }

  function answerSite(id, value) {
    const next = { ...request, answers: { ...request.answers, sites: { ...request.answers.sites, [id]: value } } };
    setRequest(next);
    recompute(next);                     // przeliczenie reguł < 1 s, bez usług zewnętrznych
  }

  async function pick(lat, lon) {
    try {
      setPreview(await getParcel({ lat, lon }));
    } catch (e) {
      setError(e.message);
    }
  }

  const questions = useMemo(
    () => Object.fromEntries((result?.recommendations || []).filter((r) => r.site_question)
      .map((r) => [r.site_question.id, r.site_question.text])),
    [result],
  );
  const active = useMemo(() => new Set((result?.recommendations || []).map((r) => r.marker?.id).filter(Boolean)), [result]);
  const level = result ? verdict(result).level : null;
  const hint = !result && !stage ? seasonNote(request.range.from) : null;

  let body;
  if (!locked) {
    body = error
      ? <ErrorState message={error} hasLast={false} onOpenSaved={openSaved} onBack={() => {}} />
      : (stage ? <Loading stage={stage} /> : <Welcome onOpenSaved={openSaved} />);
  } else if (stage && stage !== "recommend") body = <Loading stage={stage} />;
  else if (stage === "recommend" && !result) body = <Loading stage={stage} />;
  else if (error && !result) {
    body = <ErrorState message={error} hasLast={!!last} onOpenSaved={openSaved}
      onBack={() => { setParcel(last.parcel); setContext(last.context); setResult(last.result); setError(null); }} />;
  } else if (result && parcel) {
    body = (
      <>
        {error && <p className="err pi-err" role="alert">{error}</p>}
        <ResultView parcel={parcel} request={request} result={result} context={context} answers={request.answers}
          onAnswers={(answers) => setRequest({ ...request, answers })} onRecompute={() => recompute()}
          onSiteAnswer={answerSite} onFocus={(m) => setFocus({ ...m, t: Date.now() })} />
      </>
    );
  } else body = <Welcome onOpenSaved={openSaved} />;

  return (
    <>
      <a className="skip" href="#panel">Przejdź do wyniku</a>
      <div className="app">
        <MapView parcel={parcel} locked={locked} level={level} terrain={result ? context?.terrain : null} preview={preview}
          onPick={pick} onCheckPreview={() => check(preview)} busy={!!stage} flyVersion={flyVersion}
          questions={questions} active={active} sites={request.answers.sites} onSiteAnswer={answerSite} focus={focus} />
        <div className="map-fade" aria-hidden="true" />
        <Topbar ref={topRef} q={q} onQ={setQ} request={request} onRequest={setRequest}
          onSubmit={() => (locked ? check(parcel) : check())} locked={locked ? parcel : null} onUnlock={unlock}
          busy={!!stage} textSize={textSize} onTextSize={setTextSize} contrast={contrast}
          onContrast={() => setContrast((c) => !c)} onInfo={() => setInfo(true)} />
        {hint && <p className="season-hint" role="status">{hint}</p>}
        <aside className="panel" id="panel" tabIndex={-1} aria-live="polite" aria-label="Wynik" aria-busy={!!stage}>
          {body}
        </aside>
        {locked && result && <MapLegend level={level} terrain={context?.terrain} />}
      </div>

      {info && (
        <section className="overlay" role="dialog" aria-modal="true" aria-label="Jak liczymy"
          onClick={(e) => { if (e.target === e.currentTarget) setInfo(false); }}>
          <div className="ov-inner">
            <button type="button" className="ov-close" ref={closeRef} aria-label="Zamknij" onClick={() => setInfo(false)}>×</button>
            <div className="prose">
              <h2>Jak liczymy</h2>
              <p>Każdą liczbę i każdą radę liczy program na podstawie danych o Twojej działce; nic nie jest zgadywane.</p>
              <ol>
                <li><b>Działka</b> z rejestru ULDK (GUGiK): granica i powierzchnia.</li>
                <li><b>Pogoda z 10 lat</b> i prognoza na 16 dni (Open-Meteo, ERA5): opad, parowanie, temperatura.</li>
                <li><b>Gleba</b>: kategoria podatności na suszę (IUNG-PIB) i właściwości wodne (SoilGrids).</li>
                <li><b>Teren</b> z modelu wysokości 1 m (GUGiK): spadki, spływ wody, rowy i zagłębienia.</li>
                <li><b>Woda w glebie</b> liczona dzień po dniu metodą FAO-56; próg suszy z rozporządzenia (Dz.U. 2019 poz. 739).</li>
                <li><b>Wybrany okres</b>: pogoda z prognozy, a dalej z tych samych dni w 10 poprzednich latach („w ilu z 10 lat zabraknie wody”).</li>
                <li><b>Rady</b> w stałej kolejności: najpierw zatrzymanie wody na polu, potem zabiegi w uprawie, na końcu nawadnianie.</li>
              </ol>
              <h3>Źródła naukowe i metody</h3>
              <ScienceSources />
            </div>
          </div>
        </section>
      )}
    </>
  );
}
