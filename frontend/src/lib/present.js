// Algorytmy prezentacji (styl „Pole z lotu ptaka”, eksport rozdz. II.4) dopasowane do naszego AnalysisResult.
// Interfejs niczego nie liczy od nowa: tylko przekłada statusy i liczby z silnika na elementy ekranu.

export const fmt = (x, nd = 0) =>
  x == null || Number.isNaN(Number(x)) ? "—" : Number(x).toLocaleString("pl-PL", { minimumFractionDigits: nd, maximumFractionDigits: nd }).replace("-", "−");

function isoParts(isoDate) {
  if (typeof isoDate !== "string") return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  const utc = new Date(Date.UTC(year, month - 1, day));
  if (utc.getUTCFullYear() !== year || utc.getUTCMonth() !== month - 1 || utc.getUTCDate() !== day) return null;
  return { year, month, day };
}

/** „22.11.2026”. Z części napisu RRRR-MM-DD, zero wiodące, kropki, bez spacji.
 *  null, undefined i zły napis → "". */
export function formatDate(isoDate) {
  const p = isoParts(isoDate);
  if (!p) return "";
  return `${String(p.day).padStart(2, "0")}.${String(p.month).padStart(2, "0")}.${p.year}`;
}

/** „21 marca 2024”. Intl.DateTimeFormat("pl-PL", { day: "numeric", month: "long", year: "numeric" })
 *  na new Date(rok, miesiącIndex, dzień) złożonym z części, potem dzień, miesiąc i rok
 *  sklejone jedną spacją (formatToParts), żeby silnik nie wstawił innej spacji.
 *  null i zły napis → "". */
export function formatDateLong(isoDate) {
  const p = isoParts(isoDate);
  if (!p) return "";
  const parts = new Intl.DateTimeFormat("pl-PL", {
    day: "numeric", month: "long", year: "numeric",
  }).formatToParts(new Date(p.year, p.month - 1, p.day));
  const day = parts.find((part) => part.type === "day")?.value;
  const month = parts.find((part) => part.type === "month")?.value;
  const year = parts.find((part) => part.type === "year")?.value;
  if (!day || !month || !year) return "";
  return `${day} ${month} ${year}`;
}

/** Dzień kalendarzowy Europe/Warsaw jako RRRR-MM-DD. */
export function warsawTodayIso(now = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Warsaw",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const get = (type) => parts.find((part) => part.type === type)?.value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}

/** „Dzisiaj”, gdy isoDate jest dniem Europe/Warsaw; inaczej formatDateLong. Zły i pusty napis → "". */
export function dayLabel(isoDate, todayIso = warsawTodayIso()) {
  if (isoDate === todayIso) return "Dzisiaj";
  return formatDateLong(isoDate);
}

/** „22.11.2026” albo „2.1.2026” → "2026-11-22" / "2026-01-02". Inna maska i nieistniejący dzień → null. */
export function parsePlDate(text) {
  if (typeof text !== "string") return null;
  const m = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(text.trim());
  if (!m) return null;
  const iso = `${m[3]}-${m[2].padStart(2, "0")}-${m[1].padStart(2, "0")}`;
  return isoParts(iso) ? iso : null;
}

/** Ta sama reguła co weather.shift_year. 29 lutego w roku bez tego dnia → dzień 28. Reszta dat bez zmian. */
export function shiftIsoYear(isoDate, years) {
  const p = isoParts(isoDate);
  if (!p) return "";
  const year = p.year + years;
  const utc = new Date(Date.UTC(year, p.month - 1, p.day));
  const same = utc.getUTCFullYear() === year && utc.getUTCMonth() === p.month - 1 && utc.getUTCDate() === p.day;
  const day = same ? p.day : 28;
  return `${year}-${String(p.month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

export const CROPS = [
  ["zboza_ozime", "Zboża ozime"],
  ["zboza_jare", "Zboża jare"],
  ["kukurydza_ziarno", "Kukurydza na ziarno"],
  ["kukurydza_kiszonka", "Kukurydza na kiszonkę"],
  ["rzepak", "Rzepak"],
  ["ziemniak", "Ziemniaki"],
  ["burak_cukrowy", "Burak cukrowy"],
  ["uzytki_zielone", "Łąki i pastwiska"],
];
export const CROP_NAME = Object.fromEntries(CROPS);
// uprawy, dla których sezon liczy się od daty siewu (oziminy, rzepak, łąki: od startu wegetacji)
export const SOWN = new Set(["zboza_jare", "kukurydza_ziarno", "kukurydza_kiszonka", "ziemniak", "burak_cukrowy"]);

export const LEVEL = {
  alarm: { label: "Susza", color: "#D8432C" },
  uwaga: { label: "Uwaga", color: "#E3A51C" },
  ok: { label: "Bez suszy", color: "#3FA35A" },
  info: { label: "Poza sezonem", color: "#E8C547" },
};

/** Werdykt: poziom + etykieta + tytuł (jedno zdanie silnika, prostym językiem). */
export function verdict(result) {
  const st = result.state;
  const kbw = st.kbw?.status;
  const sw = st.soil_water;
  const f = result.forecast;
  const stressed = !!sw?.below_raw;
  const severe = stressed && sw?.pct_of_taw?.median != null && sw.safe_level_pct != null
    && sw.pct_of_taw.median < sw.safe_level_pct / 2;
  const fcRisk = f?.status === "ok" && f.stress_chance?.n >= 5;
  let level = "ok";
  if (kbw === "zagrozenie" || severe) level = "alarm";
  else if (stressed || kbw === "na_granicy" || fcRisk) level = "uwaga";
  else if (kbw === "poza_okresem" || f?.status === "poza_sezonem_uprawy") level = "info";
  return { level, label: LEVEL[level].label, title: st.headline_key || st.headline };
}

/** Wskaźnik wody w glebie jak wskaźnik paliwa (mediany przebiegów TAW). */
export function gauge(sw) {
  if (!sw?.taw_mm?.median || sw.dr_mm?.median == null) return null;
  const taw = sw.taw_mm.median;
  const dr = sw.dr_mm.median;
  const raw = sw.safe_level_pct != null ? taw * (1 - sw.safe_level_pct / 100) : null;
  const left = Math.max(0, taw - dr);
  return {
    taw, dr, raw, stressed: !!sw.below_raw,
    fill: Math.round((100 * left) / taw),
    mark: raw != null ? (100 * (taw - raw)) / taw : null,
  };
}

/** Bilans na tle progu: pozycje znacznika i progu na pasku sucho → mokro. */
export function kbwBar(kbw) {
  if (kbw?.kbw_mm == null) return null;
  const v = kbw.kbw_mm;
  const t = kbw.threshold_mm;
  const lo = Math.min(v, t ?? v) - 40;
  const hi = Math.max(0, v, t ?? v) + 40;
  const pos = (x) => Math.min(100, Math.max(0, (100 * (x - lo)) / (hi - lo)));
  return { value: v, threshold: t, pv: pos(v), pt: t != null ? pos(t) : null, period: kbw.period?.label };
}

/** Najbliższe dni: pierwszy pasujący wariant. */
export function nextDays(result) {
  const sw = result.state.soil_water;
  const f = result.forecast;
  if (sw?.below_raw) return "Łatwo dostępna woda już się skończyła.";
  if (f?.status === "poza_sezonem_uprawy") return "Wybrany okres jest poza sezonem wzrostu tej uprawy.";
  if (f?.status === "ok" && f.days_to_raw?.median != null)
    return `Zapas może się skończyć za ok. ${fmt(f.days_to_raw.median)} dni (w ${f.stress_chance.n} z 10 podobnych lat).`;
  if (f?.status === "ok") return "W wybranym okresie zapas wody powinien wystarczyć.";
  return null;
}

/** Poziom 1: pierwsze 3 działania; nawadnianie dopisane jako 4., jeśli nie zmieściło się w 3. */
export function topActions(recs) {
  const shown = recs.slice(0, 3);
  const irr = recs.find((r) => r.group === "nawadnianie");
  if (irr && !shown.includes(irr)) shown.push(irr);
  return shown;
}

export const GROUP = { retencja: "Zatrzymanie wody", agrotechnika: "Zabieg w uprawie", nawadnianie: "Nawadnianie" };
export const CAUSE = {
  C1: { short: "Mało deszczu, duże parowanie", long: "Deficyt opadów i wysokie parowanie" },
  C2: { short: "Lekka gleba nie trzyma wody", long: "Mała pojemność wodna gleby" },
  C3: { short: "Woda spływa z pola", long: "Nadmierny spływ (woda nie zostaje na polu)" },
  C4: { short: "Uprawa jest wrażliwa", long: "Wrażliwość uprawy w okresie niedoboru" },
};
export const KBW_STATUS = {
  zagrozenie: "zagrożenie suszą", brak_zagrozenia: "brak zagrożenia", na_granicy: "na granicy progu",
  poza_okresem: "poza okresem monitoringu", brak_progu: "brak progu", brak_danych: "brak danych",
};
export const CONF = { wysoka: "wysoka", srednia: "średnia", niska: "niska", nie_oceniono: "nie oceniono" };

/** Komunikat sezonu dla wybranej daty (21 III – 30 IX = okres monitoringu suszy). */
export function seasonNote(isoDate) {
  if (!isoDate) return null;
  const [, m, d] = isoDate.split("-").map(Number);
  const inSeason = (m > 3 || (m === 3 && d >= 21)) && m < 10;
  if (inSeason) return null;
  const winter = [11, 12, 1, 2].includes(m) || (m === 3 && d < 21);
  return winter
    ? "Wybrałeś okres zimowy. Suszę rolniczą ocenia się od 21 marca do 30 września, więc zobaczysz głównie podatność działki z ostatnich lat. Wydłuż zakres dat do wiosny, żeby zobaczyć ryzyko na początku sezonu."
    : "Ta data jest już po sezonie monitoringu suszy (21 marca – 30 września). Wynik pokaże głównie zakończony sezon i podatność działki.";
}

export const iso = (d) => d.toISOString().slice(0, 10);
export function defaultRequest() {
  const from = new Date();
  const to = new Date(from);
  to.setDate(to.getDate() + 30);
  return {
    crop: "zboza_ozime", range: { from: iso(from), to: iso(to) }, sowing_date: null,
    answers: { irrigation_water: null, drained: null, ditch_with_weir: null, sites: {} },
  };
}
