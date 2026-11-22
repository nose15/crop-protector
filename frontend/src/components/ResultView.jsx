// Wynik w panelu (styl 6.5–6.13): poziom 1 krótko (werdykt + wskaźnik, przyczyny, 3 działania, 3 liczby, pewność),
// poziom 2 na żądanie (doprecyzowanie i sekcje szczegółów). Liczby wyłącznie z wyniku silnika.
import { Fragment, useEffect, useRef, useState } from "react";
import { CauseIcon, StatusIcon } from "./Icons.jsx";
import OverlayFrame from "./OverlayFrame.jsx";
import Seg from "./Seg.jsx";
import Sources from "./Sources.jsx";
import ScienceSources from "./ScienceSources.jsx";
import {
  CAUSE, CONF, CROP_NAME, GROUP, fmt, formatDate, gauge, kbwBar, nextDays, seasonNote, topActions, verdict,
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

function warningLabel(n) {
  if (n === 1) return "1 ostrzeżenie";
  const last = n % 10;
  const hundred = n % 100;
  if (last >= 2 && last <= 4 && (hundred < 12 || hundred > 14)) return `${n} ostrzeżenia`;
  return `${n} ostrzeżeń`;
}

function WaterChart({ series, taw }) {
  if (!Array.isArray(series) || series.length === 0 || taw?.high == null) return null;
  const yMax = taw.high;
  const n = series.length;
  const W = 420;
  const H = 170;
  const pad = { l: 44, r: 10, t: 18, b: 24 };
  const X = (i) => pad.l + (n === 1 ? 0.5 : i / (n - 1)) * (W - pad.l - pad.r);
  const Y = (v) => pad.t + (1 - Number(v) / yMax) * (H - pad.t - pad.b);
  const long = n - 1 > 120;
  const label = (iso) => {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString("pl-PL", long
      ? { month: "short", year: "numeric" }
      : { day: "numeric", month: "short" });
  };
  const tickCount = Math.min(n, 5);
  const ticks = [...new Set(Array.from({ length: tickCount }, (_, i) => (
    n === 1 ? 0 : Math.round((i * (n - 1)) / (tickCount - 1))
  )))];
  const yTicks = [0, 1, 2, 3].map((k) => (yMax * k) / 3);
  const line = (pts) => pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
  const solid = [];
  const dashed = [];
  if (n > 1) {
    let sRun = null;
    let dRun = null;
    for (let i = 0; i < n - 1; i++) {
      const a = [X(i), Y(series[i].level_mm.median)];
      const b = [X(i + 1), Y(series[i + 1].level_mm.median)];
      if (series[i].estimated && series[i + 1].estimated) {
        sRun = null;
        if (!dRun) { dRun = [a, b]; dashed.push(dRun); } else dRun.push(b);
      } else {
        dRun = null;
        if (!sRun) { sRun = [a, b]; solid.push(sRun); } else sRun.push(b);
      }
    }
  }
  const raw = series.map((p, i) => [X(i), Y(p.raw_mm.median)]);
  const band = n > 1 ? [
    ...series.map((p, i) => [X(i), Y(p.level_mm.low)]),
    ...series.map((p, i) => [X(n - 1 - i), Y(series[n - 1 - i].level_mm.high)]),
  ] : [];
  return (
    <>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
        aria-label="Poziom wody, estymacja i próg RAW, w milimetrach">
        {yTicks.map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={W - pad.r} y1={Y(v)} y2={Y(v)} stroke="#E3E8E3" />
            <text x={pad.l - 6} y={Y(v) + 4} textAnchor="end">{fmt(v)}</text>
          </g>
        ))}
        <text x="4" y="12">mm</text>
        {band.length > 0 && <path d={line(band)} fill="var(--water)" fillOpacity="0.16" stroke="none" />}
        {n > 1
          ? <path d={line(raw)} fill="none" stroke="var(--amber)" strokeWidth="2.2" vectorEffect="non-scaling-stroke" />
          : <circle cx={raw[0][0]} cy={raw[0][1]} r="3.2" fill="var(--amber)" />}
        {solid.map((pts, i) => (
          <path key={`s${i}`} d={line(pts)} fill="none" stroke="var(--water)" strokeWidth="2.6" vectorEffect="non-scaling-stroke" />
        ))}
        {dashed.map((pts, i) => (
          <path key={`d${i}`} d={line(pts)} fill="none" stroke="var(--water)" strokeWidth="2.6" strokeDasharray="6 4" vectorEffect="non-scaling-stroke" />
        ))}
        {n === 1 && <circle cx={X(0)} cy={Y(series[0].level_mm.median)} r="3.2" fill="var(--water)" />}
        <line x1={X(0)} x2={X(0)} y1={pad.t} y2={H - pad.b} stroke="var(--ink)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
        {ticks.map((i, k) => (
          <text key={series[i].date} x={X(i)} y={H - 6}
            textAnchor={ticks.length === 1 ? "middle" : k === 0 ? "start" : k === ticks.length - 1 ? "end" : "middle"}>
            {label(series[i].date)}
          </text>
        ))}
      </svg>
      <div className="legend">
        <span><i className="line" aria-hidden="true" />poziom wody</span>
        <span><i className="dash" aria-hidden="true" />estymowany poziom</span>
        <span><i className="line raw" aria-hidden="true" />RAW</span>
      </div>
    </>
  );
}

function evidenceLines(evidence) {
  const items = Array.isArray(evidence) ? evidence : [];
  const value = new Map(items.map((item) => [item.field, item.value]));
  const has = (...fields) => fields.every((field) => value.has(field));
  const lines = [];
  if (has("state.kbw.kbw_mm")) lines.push(`Bilans opadu i parowania: ${fmt(value.get("state.kbw.kbw_mm"))} mm`);
  if (has("state.kbw.threshold_mm")) lines.push(`Próg suszy: ${fmt(value.get("state.kbw.threshold_mm"))} mm`);
  if (has("susceptibility.n_kbw", "susceptibility.of_kbw")) {
    lines.push(`Susza z braku deszczu: ${fmt(value.get("susceptibility.n_kbw"))} z ${fmt(value.get("susceptibility.of_kbw"))} lat`);
  }
  if (has("soil.iung.shares.I+II")) lines.push(`Udział gleby lekkiej: ${fmt(value.get("soil.iung.shares.I+II"))} %`);
  if (has("terrain.stats.slope_p90_deg")) lines.push(`Nachylenie: ${fmt(value.get("terrain.stats.slope_p90_deg"), 1)}°`);
  if (has("terrain.outlets[0].catchment_ha")) lines.push(`Zlewnia spływu: ${fmt(value.get("terrain.outlets[0].catchment_ha"), 1)} ha`);
  if (has("susceptibility.n_ks", "susceptibility.of")) {
    lines.push(`Lata ze stresem w pełni wzrostu: ${fmt(value.get("susceptibility.n_ks"))} z ${fmt(value.get("susceptibility.of"))} lat`);
  }
  return lines;
}

function CauseWindow({ cause, onClose, onShowActions }) {
  const lines = evidenceLines(cause.evidence);
  return (
    <OverlayFrame label={CAUSE[cause.code].short} onClose={onClose}>
      <div className="prose">
        <h2>{CAUSE[cause.code].short}</h2>
        <p>{CAUSE[cause.code].long}</p>
        <p><span className={`pill ${cause.dominant ? "dominujaca" : "brak"}`}>{cause.dominant ? "główna" : "mniej ważna"}</span></p>
        <p>{cause.why}</p>
        <p>
          <b>Pewność:</b> <span className={`pill ${cause.confidence}`}>{CONF[cause.confidence]}</span>
          {cause.confidence_reason ? <span className="small"> {cause.confidence_reason}</span> : null}
        </p>
        {lines.length > 0 && <ul>{lines.map((line) => <li key={line}>{line}</li>)}</ul>}
        <p>Działania z tej oceny są na kartach niżej.</p>
        <p><button type="button" className="sbtn" onClick={onShowActions}>Pokaż karty działań</button></p>
      </div>
    </OverlayFrame>
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
  const openerRef = useRef(null);
  const actionsRef = useRef(null);
  const v = verdict(result);
  const g = gauge(result.state.soil_water);
  const kb = kbwBar(result.state.kbw);
  const nd = nextDays(result);
  const s = result.susceptibility;
  const f = result.forecast;
  const sw = result.state.soil_water;
  const showChart = Array.isArray(sw?.series) && sw.series.length > 0 && sw.taw_mm?.high != null;
  const startLevel = showChart ? sw.series[0].level_mm.median : null;
  const startRaw = showChart ? sw.series[0].raw_mm.median : null;
  const startRel = startLevel < startRaw ? "poniżej progu" : startLevel > startRaw ? "powyżej progu" : "na równi z progiem";
  const k = result.state.kbw || {};
  const dominant = result.causes.filter((c) => c.dominant);
  const opened = result.causes.find((c) => c.code === openCause);
  const top = topActions(result.recommendations);
  const sNote = seasonNote(request.range.from);
  const more = result.state.headline_more || [];
  const outOfGrowth = f?.status === "poza_sezonem_uprawy";
  const moreNote = outOfGrowth ? more.slice(1) : more;
  const growthState = outOfGrowth ? result.state.headline_key : null;
  const growthHint = outOfGrowth ? more[0] : null;
  const reasons = result.uncertainty.reasons;
  const skipped = result.not_evaluated;
  const limits = result.limitations;
  const warnCount = [sNote, growthState, growthHint].filter(Boolean).length
    + reasons.length + skipped.length + limits.length;
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
        <span>{formatDate(request.range.from)} – {formatDate(request.range.to)}</span>
      </div>
      {parcel.found_by === "adres" && (
        <p className="note">Działka pod adresem {parcel.address}. Jeśli Twoje pole jest obok, kliknij „Zmień działkę” i wskaż je na mapie.</p>
      )}

      <section className={`verdict ${v.level}`} aria-labelledby="verdict-h">
        <span className="vstatus"><StatusIcon level={v.level} />{v.label}</span>
        <h1 id="verdict-h">{v.title}</h1>
        {showChart ? (
          <div className="timeline inpanel">
            <div className="tl-body">
              <WaterChart series={sw.series} taw={sw.taw_mm} />
              <p className="gauge-cap">
                Na początku zakresu w glebie jest <b>{fmt(startLevel)} mm</b> wody, {startRel} RAW (<b>{fmt(startRaw)} mm</b>).
              </p>
            </div>
          </div>
        ) : g == null ? (
          <p className="gauge-cap">Brak oceny wody w glebie (brak danych o glebie albo pogodzie od 1 marca).</p>
        ) : null}
      </section>
      {moreNote.length > 0 && <p className="note">{moreNote.join(" ")}</p>}

      <details className="det">
        <summary>
          Pewność danych
          <span className={`badge ${result.uncertainty.overall}`}>{CONF[result.uncertainty.overall]}</span>
          {warnCount > 0 && <span className="sub">{warningLabel(warnCount)}</span>}
        </summary>
        <div className="body">
          <ul className="reasons">
            {sNote && <li key="season">{sNote}</li>}
            {growthState && <li key="growth-state">{growthState}</li>}
            {growthHint && <li key="growth-hint">{growthHint}</li>}
            {reasons.map((x) => <li key={x}>{x}</li>)}
          </ul>
          {skipped.length > 0 && (
            <>
              <p><b>Nie sprawdziliśmy:</b></p>
              <ul className="reasons">{skipped.map((x) => <li key={x.rule}>{x.title || "działanie"} – {x.reason}.</li>)}</ul>
            </>
          )}
          <p><b>O czym pamiętać:</b></p>
          <ul className="reasons">{limits.map((x) => <li key={x}>{x}</li>)}</ul>
        </div>
      </details>

      <h2 className="sec-title">Dlaczego</h2>
      {dominant.length === 0 && <p className="small muted">Nie widać jednej głównej przyczyny niedoboru wody.</p>}
      <div className="why">
        {dominant.map((c) => (
          <button key={c.code} type="button" className="cause" aria-expanded={openCause === c.code}
            onClick={(event) => {
              if (openCause === c.code) setOpenCause(null);
              else { openerRef.current = event.currentTarget; setOpenCause(c.code); }
            }}>
            <CauseIcon code={c.code} />{CAUSE[c.code].short}
          </button>
        ))}
      </div>
      {opened && (
        <CauseWindow cause={opened} onClose={() => { setOpenCause(null); openerRef.current?.focus(); }}
          onShowActions={() => {
            setOpenCause(null);
            actionsRef.current?.focus();
            actionsRef.current?.scrollIntoView({ block: "start" });
          }} />
      )}

      <h2 className="sec-title" id="co-zrobic" tabIndex={-1} ref={actionsRef}>Co zrobić <small>w tej kolejności</small></h2>
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
