// Wynik w panelu (styl 6.5–6.13): poziom 1 krótko (werdykt + wskaźnik, przyczyny, 3 działania, 3 liczby, pewność),
// poziom 2 na żądanie (doprecyzowanie i sekcje szczegółów). Liczby wyłącznie z wyniku silnika.
import { Fragment, useEffect, useRef, useState } from "react";
import { CauseIcon, StatusIcon } from "./Icons.jsx";
import Seg from "./Seg.jsx";
import Sources from "./Sources.jsx";
import ScienceSources from "./ScienceSources.jsx";
import {
  CAUSE, CONF, CROP_NAME, GROUP, fmt, gauge, kbwBar, nextDays, seasonNote, topActions, verdict,
} from "../lib/present.js";

const SOIL = { I: "bardzo lekka (piaszczysta)", II: "lekka", III: "średnia", IV: "ciężka", organic: "organiczna" };
const satTrend = (obs) => {
  const d = obs[obs.length - 1].ndmi - obs[0].ndmi;
  return d > 0.05 ? "rośnie" : d < -0.05 ? "spada" : "bez wyraźnej zmiany";
};
const QUESTIONS = [
  ["ditch_with_weir", "Przy działce jest rów z zastawką?"],
  ["drained", "Działka jest drenowana?"],
  ["irrigation_water", "Masz wodę do nawadniania (studnia, zbiornik, ciek)?"],
];

function Gauge({ g }) {
  const label = `Zostało ${fmt(g.taw - g.dr)} z ${fmt(g.taw)} mm wody dostępnej dla roślin. Brakuje ${fmt(g.dr)} mm`
    + (g.raw != null ? `, rośliny cierpią przy braku powyżej ${fmt(g.raw)} mm.` : ".");
  return (
    <div className="gauge" role="img" aria-label={label}>
      <div className="gauge-bar">
        <div className="gauge-fill" style={{ width: `${g.fill}%` }} />
        {g.mark != null && <div className="gauge-mark" style={{ left: `calc(${g.mark}% - 1px)` }} />}
      </div>
      <div className="gauge-scale">
        <span>pusto</span>
        {g.mark != null && <span className="gm" style={{ left: `${Math.min(80, Math.max(20, g.mark))}%` }}>granica stresu</span>}
        <span>pełno</span>
      </div>
      <p className="gauge-cap">
        W glebie brakuje <b>{fmt(g.dr)} mm</b> wody.
        {g.raw != null && <> Rośliny cierpią, gdy brakuje więcej niż <b>{fmt(g.raw)} mm</b>{g.stressed ? " – i to już się dzieje." : "."}</>}
      </p>
    </div>
  );
}

function Action({ r, no, sites, onSiteAnswer, onFocus }) {
  return (
    <li>
      <details className={r.group}>
        <summary>
          <span className="n">{no}</span>
          <span>
            <div className="t">{r.title || r.message}</div>
            <div className="g">{GROUP[r.group]}{r.conditional ? ", jeśli dotyczy" : ""}</div>
          </span>
          {r.when_short && <span className="when">{r.when_short}</span>}
        </summary>
        <div className="more">
          <p>{r.message}</p>
          {r.when_text && <p><b>Kiedy:</b> {r.when_text}</p>}
          <p><b>Dlaczego tutaj:</b> {r.why}</p>
          {r.effect?.text && <p><b>Efekt:</b> {r.effect.text}</p>}
          {r.site_question && (
            <div className="qa"><div className="q">
              <span>{r.site_question.text}</span>
              <Seg label={r.site_question.text} value={sites[r.site_question.id] ?? null}
                onChange={(v) => onSiteAnswer(r.site_question.id, v)} />
            </div></div>
          )}
          <p>
            <b>Pewność:</b> <span className={`pill ${r.confidence}`}>{CONF[r.confidence]}</span>
            {r.confidence_reason && <span className="small"> {r.confidence_reason}</span>}
          </p>
          {r.marker && <p><button type="button" className="linkbtn" onClick={() => onFocus(r.marker)}>Pokaż na mapie</button></p>}
          {r.consult_note && <p className="small">{r.consult_note}</p>}
        </div>
      </details>
    </li>
  );
}

export default function ResultView({ parcel, request, result, context, answers, onAnswers, onRecompute, onSiteAnswer, onFocus }) {
  const [openCause, setOpenCause] = useState(null);
  const certRef = useRef(null);
  const v = verdict(result);
  const g = gauge(result.state.soil_water);
  const kb = kbwBar(result.state.kbw);
  const nd = nextDays(result);
  const s = result.susceptibility;
  const f = result.forecast;
  const sw = result.state.soil_water;
  const k = result.state.kbw || {};
  const dominant = result.causes.filter((c) => c.dominant);
  const top = topActions(result.recommendations);
  const sNote = seasonNote(request.range.from);
  const t = context?.terrain?.stats;
  const iung = context?.soil?.iung;
  const sat = context?.satellite;

  // raport do druku: przed drukiem rozwijamy wszystkie sekcje i działania, po druku przywracamy poprzedni stan
  const rootRef = useRef(null);
  useEffect(() => {
    let closed = [];
    const before = () => {
      closed = [...(rootRef.current?.querySelectorAll("details:not([open])") || [])];
      closed.forEach((d) => { d.open = true; });
    };
    const after = () => { closed.forEach((d) => { d.open = false; }); closed = []; };
    window.addEventListener("beforeprint", before);
    window.addEventListener("afterprint", after);
    return () => { window.removeEventListener("beforeprint", before); window.removeEventListener("afterprint", after); };
  }, []);

  const openCert = () => {
    if (certRef.current) {
      certRef.current.open = true;
      certRef.current.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    }
  };
  const downloadJson = () => {
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `ocena-${parcel.id}.json` });
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div className="pi" ref={rootRef}>
      <div className="meta">
        <span className="id">{parcel.id}</span>
        <span>{fmt(parcel.area_ha, 2)} ha</span>
        <span>{CROP_NAME[request.crop]}</span>
        <span>{request.range.from} – {request.range.to}</span>
      </div>
      {parcel.found_by === "adres" && (
        <p className="note">Działka pod adresem {parcel.address}. Jeśli Twoje pole jest obok, kliknij „Zmień działkę” i wskaż je na mapie.</p>
      )}
      {sNote && <p className="note warn" role="status">{sNote}</p>}

      <section className={`verdict ${v.level}`} aria-labelledby="verdict-h">
        <span className="vstatus"><StatusIcon level={v.level} />{v.label}</span>
        <h1 id="verdict-h">{v.title}</h1>
        {g ? <Gauge g={g} /> : <p className="gauge-cap">Brak oceny wody w glebie (brak danych o glebie albo pogodzie od 1 marca).</p>}
      </section>
      {result.state.headline_more?.length > 0 && <p className="note">{result.state.headline_more.join(" ")}</p>}

      <h2 className="sec-title">Dlaczego</h2>
      {dominant.length === 0 && <p className="small muted">Nie widać jednej głównej przyczyny niedoboru wody.</p>}
      <div className="why">
        {dominant.map((c) => (
          <button key={c.code} type="button" className="cause" aria-expanded={openCause === c.code}
            onClick={() => setOpenCause(openCause === c.code ? null : c.code)}>
            <CauseIcon code={c.code} />{CAUSE[c.code].short}
          </button>
        ))}
        {openCause && (
          <p className="cause-note">{result.causes.find((c) => c.code === openCause)?.why} (pewność: {CONF[result.causes.find((c) => c.code === openCause)?.confidence]})</p>
        )}
      </div>

      <h2 className="sec-title">Co zrobić <small>w tej kolejności</small></h2>
      {top.length === 0 && <p className="small muted">Na tej działce nie znaleźliśmy działań do polecenia.</p>}
      <ol className="todo">
        {top.map((r, i) => <Action key={r.id} r={r} no={i + 1} sites={answers.sites} onSiteAnswer={onSiteAnswer} onFocus={onFocus} />)}
      </ol>

      <h2 className="sec-title">Najważniejsze liczby</h2>
      <div className="facts">
        {kb && (
          <div className="fact">
            <div className="fl">Bilans opadu i parowania{kb.period ? ` (${kb.period})` : ""}</div>
            <div className="fv">{fmt(kb.value)} mm <small>{kb.threshold != null ? `próg suszy ${fmt(kb.threshold)} mm` : "w tym okresie bez progu dla tej uprawy"}</small></div>
            <div className="kbwbar" aria-hidden="true">
              {kb.pt != null && <i className="thr" style={{ left: `${kb.pt}%` }} />}
              <i style={{ left: `calc(${kb.pv}% - 2px)` }} />
            </div>
            <div className="kbwscale"><span>sucho</span><span>mokro</span></div>
          </div>
        )}
        {s?.n_ks != null && (
          <div className="fact">
            <div className="fl">Jak często w ostatnich latach</div>
            <div className="fv">{s.n_ks} z {s.of} lat <small>ze stresem w kluczowym okresie</small></div>
            <div className="dots" aria-hidden="true">
              {Array.from({ length: s.of }, (_, i) => <span key={i} className={i < s.n_ks ? "on" : ""} />)}
            </div>
          </div>
        )}
        {nd && (
          <div className="fact">
            <div className="fl">W wybranym okresie</div>
            <div className="fv" style={{ fontSize: "1rem" }}>{nd}</div>
          </div>
        )}
      </div>

      <div className="confline">
        <span>Pewność wyniku <span className={`badge ${result.uncertainty.overall}`}>{CONF[result.uncertainty.overall]}</span></span>
        <button type="button" className="linkbtn" onClick={openCert}>dlaczego?</button>
      </div>

      <details className="det refine">
        <summary>Doprecyzuj wynik<span className="sub">{QUESTIONS.filter(([key]) => answers[key] !== null).length} z 3 odpowiedzi</span></summary>
        <div className="body qa">
          {QUESTIONS.map(([key, text]) => (
            <div className="q" key={key}>
              <span>{text}</span>
              <Seg label={text} value={answers[key]} onChange={(val) => onAnswers({ ...answers, [key]: val })} />
            </div>
          ))}
          <p className="small muted">Brak odpowiedzi to „nie wiem”: rady zostają, ale jako warunkowe.</p>
          <button type="button" className="sbtn primary" onClick={onRecompute}>Przelicz z odpowiedziami</button>
        </div>
      </details>

      <div className="det-head">
        <h2>Szczegóły</h2>
        <div className="tools-row">
          <button type="button" className="sbtn" onClick={() => window.print()}>Drukuj / PDF</button>
          <button type="button" className="sbtn" onClick={downloadJson}>Dane</button>
        </div>
      </div>

      <details className="det"><summary>Woda na polu<span className="sub">{g ? (g.stressed ? "brakuje" : "zapas jest") : "—"}</span></summary>
        <div className="body">
          <dl className="kv">
            {g && <><dt>Woda w glebie teraz</dt><dd>{g.stressed ? "poniżej granicy stresu" : "powyżej granicy stresu"}</dd></>}
            {sw && <><dt>Etap uprawy</dt><dd>{sw.phase_label}</dd></>}
            {k.kbw_mm != null && <><dt>Opady minus parowanie</dt><dd>{fmt(k.kbw_mm)} mm{k.threshold_mm != null ? ` (próg suszy ${fmt(k.threshold_mm)} mm)` : ""}</dd></>}
            {f?.status === "ok" && <><dt>Brak wody w wybranym okresie</dt><dd>w {f.stress_chance.n} z 10 lat</dd></>}
            {f?.status === "ok" && f.days_to_raw?.n > 0 && <><dt>Zapas może się skończyć</dt><dd>za ok. {fmt(f.days_to_raw.median)} dni</dd></>}
            {f?.status === "ok" && f.deficit_m3?.high >= 1 && <><dt>Ile wody może zabraknąć</dt><dd>do ok. {fmt(f.deficit_m3.high)} m³ na działkę</dd></>}
          </dl>
          {s?.per_year && (
            <p className="small">Lata z niedoborem wody w kluczowym okresie: {s.per_year.filter((y) => (y.stress_days_critical ?? 0) >= 10).map((y) => y.year).join(", ") || "brak"}.</p>
          )}
        </div>
      </details>

      <details className="det"><summary>Przyczyny<span className="sub">{dominant.length} {dominant.length === 1 ? "główna" : "główne"}</span></summary>
        <div className="body">
          {result.causes.filter((c) => c.confidence !== "nie_oceniono").map((c) => (
            <div className="sub-card" key={c.code}>
              <h4>{CAUSE[c.code].short} <span className={`pill ${c.dominant ? "dominujaca" : "brak"}`}>{c.dominant ? "główna" : "mniej ważna"}</span></h4>
              <p className="small">{c.why}</p>
            </div>
          ))}
        </div>
      </details>

      {result.recommendations.length > top.length && (
        <details className="det"><summary>Wszystkie działania<span className="sub">{result.recommendations.length}</span></summary>
          <div className="body"><ol className="todo">
            {result.recommendations.map((r, i) => <Action key={r.id} r={r} no={i + 1} sites={answers.sites} onSiteAnswer={onSiteAnswer} onFocus={onFocus} />)}
          </ol></div>
        </details>
      )}

      <details className="det"><summary>Gleba i teren<span className="sub">{iung?.dominant ? SOIL[iung.dominant] : "—"}</span></summary>
        <div className="body">
          <dl className="kv">
            {iung && <><dt>Gleba</dt><dd>{SOIL[iung.dominant] || "nierolnicza"}</dd></>}
            {t && <><dt>Teren</dt><dd>{t.slope_p90_deg < 2 ? "płaski" : t.slope_p90_deg < 5 ? "lekko nachylony" : "nachylony"}</dd></>}
            {t && <><dt>Rów przy działce</dt><dd>{t.n_ditches > 0 ? "prawdopodobnie tak" : "nie widać"}</dd></>}
            {t && <><dt>Woda spływa z sąsiednich pól</dt><dd>z co najmniej {fmt(t.inflow_from_outside_ha, 1)} ha</dd></>}
            {sat?.obs?.length > 1 && <><dt>Rośliny na zdjęciach satelitarnych</dt><dd>wilgotność {satTrend(sat.obs)}</dd></>}
          </dl>
        </div>
      </details>

      <details className="det" ref={certRef}><summary>Pewność i ograniczenia<span className="sub">pewność {CONF[result.uncertainty.overall]}</span></summary>
        <div className="body">
          <ul className="reasons">{result.uncertainty.reasons.map((x) => <li key={x}>{x}</li>)}</ul>
          {result.not_evaluated.length > 0 && (
            <>
              <p><b>Nie sprawdziliśmy:</b></p>
              <ul className="reasons">{result.not_evaluated.map((x) => <li key={x.rule}>{x.title || "działanie"} – {x.reason}.</li>)}</ul>
            </>
          )}
          <p><b>O czym pamiętać:</b></p>
          <ul className="reasons">{result.limitations.map((x) => <li key={x}>{x}</li>)}</ul>
        </div>
      </details>

      <details className="det"><summary>Źródła danych i metody</summary>
        <div className="body">
          <Sources provenance={result.provenance} />
          <h4 className="refs-h">Źródła naukowe i metody</h4>
          <ScienceSources />
        </div>
      </details>
    </div>
  );
}
