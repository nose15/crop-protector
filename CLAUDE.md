# CLAUDE.md: KOWR „Zatrzymaj wodę, chroń plony” (HackNation 2026)

Ten plik daje pełny kontekst projektu każdemu, kto pracuje w repozytorium (ludziom i Claude Code). Szczegóły silnika są w dokumencie „Projekt silnika obliczeń i rekomendacji” (wersja 2) i w specyfikacji silnika wskaźników (`docs/silnik-wskaznikow.md`, dalej **SPEC**). Gdy ten plik i SPEC się różnią, metody bierzemy ze SPEC, a architekturę i zakres MVP z tego pliku.

## Zasady pracy

- Komunikacja, UI, komentarze dla użytkownika i README po polsku. Nazwy w kodzie po angielsku, kody upraw i statusów po polsku bez znaków (`zboza_ozime`, `poza_okresem`), tak jak w SPEC.
- Główne źródło wymagań to 3 PDF-y zadania: „Pełna treść”, „Podstawy naukowe”, „Regulamin”. Przy wątpliwości wracamy do nich.
- **MVP ma być najprostszy:** bez bazy danych, bez kolejek, bez Dockera jako wymogu. Backend jest bezstanowy poza jednym wyjątkiem: plikowym cache kontekstów działek (`backend/cache/`, decyzja z 21.11 – limity Open-Meteo, wolne SoilGrids/Overpass i prezentacje dla mentorów). Szczegóły w sekcji „Cache”.
- Internet na hackathonie ma ok. 64 kB/s. Nie dodajemy ciężkich zależności (np. scipy, geopandas, rasterio, GDAL). Obliczenia rastrowe robimy w NumPy.
- Wynik i rekomendacje liczy kod. LLM tylko opisuje gotowy wynik. Nigdy nie pokazujemy liczby, której nie policzył silnik.
- Brak danych to „nie oceniono”, nigdy cicha wartość domyślna. Niepewne liczby pokazujemy jako przedziały, częstość jako „3 z 10 lat”, nie procenty.
- Progi heurystyczne trzymamy w YAML z kolumną „źródło / heurystyka” i opisujemy w README.

## Zadanie w skrócie

Aplikacja webowa dla rolnika: podaje numer działki (albo klika na mapie), wybiera uprawę i zakres dat, a dostaje ocenę sytuacji wodnej, przyczyny i konkretne działania. Kolejność działań jest obowiązkowa: **retencja → agrotechnika → nawadnianie (opcjonalnie)**. Sama informacja „jest susza” nie wystarcza (susza jest co roku), liczą się działania i terminy. Mentor podkreślił: prostota obsługi i prognoza na wybrany zakres dat.

Ocena jury: wartość praktyczna 25%, dane i wiarygodność 25%, innowacyjność 20%, prostota obsługi 15%, prototyp i jakość 15%. Test jury: dowolna działka z numeru, dowolna data z ostatnich 10 lat, cała ocena poniżej 30 s. Ocena odbywa się 21–22 listopada, więc data „dziś” wypada poza okresem monitoringu KBW (21 III–30 IX) i aplikacja musi to obsłużyć. README musi zawierać źródła danych z datami pobrania, licencje, koszty (LLM) i ograniczenia.

## Struktura monorepo

```
/
├── CLAUDE.md
├── README.md                # uruchomienie, metody, licencje, koszty, ograniczenia
├── docs/                    # SPEC i notatki metodyczne
├── backend/                 # FastAPI (Python 3.11+)
│   ├── pyproject.toml       # albo requirements.txt
│   ├── app/
│   │   ├── main.py          # FastAPI, CORS dla Vite, routery
│   │   ├── api/             # parcel.py, context.py, recommend.py, summary.py
│   │   ├── models.py        # Pydantic: Parcel, ParcelContext, RecommendRequest, AnalysisResult, Summary
│   │   ├── sources/         # adaptery danych (base.py + jeden plik na źródło)
│   │   ├── engine/          # kbw.py, phases.py, balance.py, forecast.py, susceptibility.py, causes.py, rules.py
│   │   ├── terrain/         # analiza NMT (obecny terrain.py)
│   │   ├── llm/             # base.py, claude.py, bielik.py, template.py
│   │   └── data/            # YAML: kbw_thresholds.yaml, crops.yaml, rules.yaml
│   └── tests/
│       └── fixtures/        # zapisane odpowiedzi źródeł do testów
└── frontend/                # React + Vite (zwykły JavaScript, JSX, bez TypeScript)
    ├── package.json
    ├── vite.config.js       # proxy /api → http://127.0.0.1:8000
    └── src/
        ├── api/             # klient fetch + opis kształtów w JSDoc (lustro modeli Pydantic)
        ├── components/      # Map, ParcelSearch, DataPanel, RequestForm, ActionCards, Sources
        └── App.jsx
```

### Uruchomienie (docelowo)

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# frontend
cd frontend
npm install
npm run dev        # http://localhost:5173, /api przez proxy na :8000
```

Testy: `cd backend && pytest`. Frontend: `npm run build` musi przejść bez błędów.

### Zależności

- Backend: `fastapi`, `uvicorn`, `httpx`, `numpy`, `pydantic` (z FastAPI), `pyyaml`, `anthropic`, `fpdf2` (raport PDF, uzgodnione 22.11; ciągnie Pillow i fontTools); do testów `pytest`. Nic więcej bez uzgodnienia.
- Frontend: `react`, `react-dom`, `leaflet` + `react-leaflet`, `chart.js` + `react-chartjs-2`. Bez bibliotek UI, style w zwykłym CSS.

## Istniejący kod (prototyp do przeniesienia)

W `/mnt/project-files/kowr/app/` jest działający prototyp (FastAPI + jeden `index.html` z Leaflet i Chart.js):

- `app.py`: `GET /api/parcel` (ULDK), `GET /api/data` (Open-Meteo archiwum i prognoza, SoilGrids, Overpass), `POST /api/terrain` (analiza NMT). Każde źródło ma status i czas, awaria jednego nie blokuje reszty.
- `terrain.py`: pobranie NMT z WCS (EPSG:3857, siatka 2 m, działka + bufor 150 m), priority-flood (Barnes 2014), kierunki D8, akumulacja spływu, zagłębienia, punkty odpływu, dopływ z sąsiednich pól, warstwy PNG jako data URL. Progi: zagłębienie ≥ 5 cm i ≥ 50 m², linia spływu od 2000 m² zlewni, odpływ od 1000 m².
- `index.html`: mapa (ortofotomapa, granice działek KIEG, cieniowanie), panel danych, panel terenu.
- Działka testowa: `046101_1.0445.7` (Bydgoszcz, 2,66 ha, gleba IUNG: 83% kat. IV, 17% kat. III). Nie sprawdzono, czy to grunt orny.
- Prototyp leży w `prototype/` (tylko do wglądu; `index.html` był pusty).

Przeniesienie: `app.py` rozbijamy na `backend/app/api/` i `backend/app/sources/`, `terrain.py` do `backend/app/terrain/`, `index.html` przepisujemy na komponenty React.

## Przepływ i API

1. `GET /api/parcel?q=<numer>` albo `?lat=&lon=` → `Parcel` (geometria EPSG:4326, centroid, powierzchnia, TERYT7). Mapa pokazuje działkę.
2. Zaraz potem `POST /api/context` `{parcel, as_of?}` → `ParcelContext`: wszystkie źródła równolegle, każde z limitem czasu, plus `provenance[]`. UI pokazuje glebę, teren i pogodę.
3. Rolnik wybiera uprawę, zakres dat, opcjonalnie 3 odpowiedzi tak/nie/nie wiem i klika „Pokaż działania” → `POST /api/recommend` `{context, request}` → `AnalysisResult` (bez LLM, poniżej 1 s). Frontend odsyła cały `ParcelContext`, bo backend nic nie przechowuje.
4. Zaraz potem `POST /api/summary` z `AnalysisResult` → `Summary` (Claude albo szablon). Tekst doładowuje się pod kartami.

Błędy: 404 `parcel_not_found`, 502 `uldk_unavailable`, 422 `invalid_request`, 409 `meteo_missing` (bez pogody nie ma oceny). Limity: ULDK 3 s, `/api/context` 28 s (potem zwraca co ma, `partial: true`), `/api/recommend` 3 s, `/api/summary` 20 s.

Wejście kroku 4:

```json
{
  "crop": "zboza_ozime",
  "range": {"from": "2027-04-01", "to": "2027-06-30"},
  "sowing_date": null,
  "answers": {"irrigation_water": null, "drained": null, "ditch_with_weir": null}
}
```

Uprawy MVP: `zboza_ozime`, `zboza_jare`, `kukurydza_ziarno`, `kukurydza_kiszonka`, `rzepak`, `ziemniak`, `burak_cukrowy`, `uzytki_zielone` (bez progów KBW, tylko bilans FAO-56). Dzień analizy D = `range.from`, najwyżej 10 lat wstecz; `range.to` najwyżej 2 lata po D (ta sama data kalendarzowa, 29 lutego → 28 lutego). `answers` przyjmuje `true`, `false`, `null`; `null` daje rekomendację warunkową „jeśli…”, a wszystko musi działać na samych `null`.

Pełne przykłady JSON (`ParcelContext`, `AnalysisResult`) są w dokumencie silnika. Kształty obiektów opisane w JSDoc w `frontend/src/api/` trzymamy zgodne z modelami Pydantic (bez TypeScript).

## Cache kontekstów (od 21.11)

- `backend/app/cache.py`: jeden plik `.json.gz` na działkę w `backend/cache/` (w `.gitignore`; inny katalog: `KOWR_CACHE_DIR`).
- `/api/context`: najpierw cache (bez żadnych zapytań); `?refresh=true` pobiera na żywo, a źródła, które wtedy zawiodą, biorą dane z zapisu (`provenance.mode = "cache"`).
- `/api/cache` (lista), `/api/cache/{numer}` (kontekst), `/api/parcel?q=` sprawdza cache przed ULDK, `/api/recommend` przyjmuje `context_ref` zamiast całego kontekstu.
- Pełne pobranie działki (długie limity, 20 lat pogody, Sentinel z NDVI): `cd backend && python -m app.prefetch 046101_1.0445.7`. Zużywa limit Open-Meteo – uruchamiać z sieci, gdzie Open-Meteo odpowiada.
- Testy nigdy nie odpytują usług zewnętrznych i nie piszą do `backend/cache/` (conftest ustawia katalog tymczasowy).

## Źródła danych (adaptery)

Każdy adapter implementuje `SourceAdapter.fetch(parcel, as_of) -> AdapterResult[T]` i nigdy nie rzuca wyjątku: błąd zamienia na `Provenance.status` (`ok | partial | timeout | error | empty`). Jeden współdzielony `httpx.AsyncClient`, bez ponowień.

| Adapter | Usługa | Limit | Uwagi |
| --- | --- | --- | --- |
| ULDK | `https://uldk.gugik.gov.pl/?request=GetParcelById&id=...&result=geom_wkb,teryt,voivodeship,county,commune,region,parcel&srid=4326` (też `GetParcelByXY`, `GetParcelByIdOrNr`) | 3 s | odpowiedź tekstowa: pierwsza linia `0` = OK, pola rozdzielone `\|`; limit ok. 200 zapytań/min |
| Open-Meteo | `/v1/archive` (10 lat od 1 marca + bieżący rok) i `/v1/forecast` (`past_days`, `forecast_days=16`) | 5 s | `precipitation_sum`, `et0_fao_evapotranspiration`, `temperature_2m_max/min`; archiwum ma ok. 5 dni opóźnienia; CC BY 4.0 |
| IUNG gleba | WCS 2.0.1 `sgeo.iung.pl/geoserver/ows`, warstwa `Susza__katgl_landuse2024` (5 m, EPSG:2180) | 3 s | kody 1–4 = kategorie I–IV, 5 organiczne, 11–14 nierolnicze, 19/99 nieklasyfikowane; brak jawnej licencji |
| SoilGrids | ISRIC REST v2.0 | 4 s | `wv0033`, `wv1500` (kwantyle), piasek, ił, SOC; 250 m |
| NMT | WCS GUGiK `https://mapy.geoportal.gov.pl/wss/service/PZGIK/NMT/GRID1/WCS/DigitalTerrainModel`, prototyp używa `DTM_PL-EVRF2007-NH`, `image/x-aaigrid` (SPEC podaje `DTM_PL-KRON86-NH_TIFF`) | 10 s | w testach SPEC GetCoverage nie odpowiadał w 45–90 s; bez NMT reguły terenowe dostają „nie oceniono” |
| Cieki | Overpass OSM `waterway=*` w promieniu 500 m | 4 s | Overpass bywa przeciążony; ODbL |
| Sentinel-2 | Earth Search STAC `sentinel-2-c1-l2a`, COG `nir08`, `swir16`, `scl` (pełne pobranie także `rededge1`, `red`, `nir`) | 15 s | tymczasowo, tylko informacja w panelu: tryb lekki NDMI z 3 scen (ok. 2 MB), szczegóły i koszty w `docs/sentinel.md`; odbicie = DN·10⁻⁴ − 0,1 |
| Mapy w przeglądarce | Geoportal WMS ORTO (`STYLES=default` w WMS 1.3.0), KIEG (granice działek), cieniowanie NMT | — | ładuje frontend, nie backend |

Stałe (progi KBW z Dz.U. 2019 poz. 739, Kc, GDD, Zr, p, reguły) leżą w `backend/app/data/*.yaml`.

## Silnik (krok 4, zakres MVP)

Wzory i progi: SPEC §3. W MVP:

1. **KBW sześciodekadowy** (14 okresów 21 III–30 IX, KBW = ΣP − ΣET0) porównany z progiem [uprawa][kategoria IUNG][okres], ważony udziałem kategorii na działce. Statusy: `zagrozenie`, `na_granicy` (|margines| < 15 mm), `brak_zagrozenia`, `poza_okresem`, `brak_progu`, `brak_danych`. Zawsze z dopiskiem, że to przybliżenie metodyki SMSR (ET0 FAO-PM zamiast ETP IUNG).
2. **Fazy i Kc(t)** z GDD; data siewu z `sowing_date` albo heurystyki FAO-56.
3. **Bilans FAO-56** strefy korzeniowej: `Dr = clip(Dr − P + Kc·ET0, 0, TAW)`, RAW = p·TAW, Ks; start 1 marca.
4. **TAW jako przedział:** granice kategorii IUNG (I < 127,5; II 127,5–169,9; III 170–202,5; IV > 202,5 mm na 1,5 m, przeliczone na Zr) i SoilGrids, × 2 głębokości korzeni.
5. **Prognoza na zakres dat:** od stanu w dniu D do `range.to`; pierwsze ≤ 16 dni z prognozy, dalej 10 scenariuszy z tych samych dni w 10 poprzednich latach. Wynik: szansa stresu „n z 10”, dni do RAW (przedział), niedobór w mm i m³.
6. **Podatność 10 lat:** sezony z przekroczonym progiem KBW, sezony z ≥ 10 dniami stresu w fazie krytycznej, typowe miesiące ryzyka.
7. **Przyczyny C1–C4** (opad/upał, gleba, spływ, okno uprawy), najwyżej 2 dominujące, każda z pewnością.
8. **Reguły** z `rules.yaml`, kody jak w SPEC §5.2. MVP: R2, R3, R6, R8, R11 (warunkowo), R14 (retencja); R1, R7, R15, R16 (agrotechnika); nawadnianie (zapas poniżej RAW w zakresie dat i woda nie jest wykluczona). Bramki G1–G4: reguła tylko z policzonym wskaźnikiem; nawadnianie zawsze ostatnie; brak danych to „nie oceniono”; inwestycje zawsze z dopiskiem o konsultacji z ODR, spółką wodną albo Wodami Polskimi. Raport ma 3–5 działań.

Pewność: `wysoka | srednia | niska | nie_oceniono`. Pewność reguły to minimum pewności jej wejść, a pewność całości ma 2–4 powody.

Stretch (nie robić przed MVP): SCS-CN i efekt „przed/po”, Ky, SPI/SPEI, anomalia S2 względem lat bazowych, GLO-30 jako zapas NMT, walidacja z tabelami SMSR, TWI.

Testy obowiązkowe: KBW dla daty listopadowej (`poza_okresem`), bilans na fixtures daje stały wynik, niezmienniki rekomendacji (każda ma `evidence`, kolejność grup, dopisek G4, przedziały zamiast liczb tam, gdzie wynik jest niepewny).

## Warstwa LLM

- Interfejs `LLMClient.summarize(result) -> Summary`; implementacje `ClaudeClient` (domyślna), `BielikClient` (opcja), `TemplateClient` (zawsze działa). Wybór przez `LLM_PROVIDER`, łańcuch zapasowy `claude → template`. Bez klucza aplikacja działa na szablonie.
- Claude: SDK `anthropic`, klucz w `ANTHROPIC_API_KEY` (tylko backend, nigdy w repo ani we frontendzie), model `claude-opus-5-5`, `output_config={"effort": "low", "format": {"type": "json_schema", "schema": SUMMARY_SCHEMA}}`, limit 20 s, `max_retries=1`. Przy `stop_reason` równym `refusal` albo `max_tokens` → szablon. Tańsza opcja: `claude-haiku-5-5`.
- Wejście to odchudzony `AnalysisResult` (bez PNG, GeoJSON i szeregów dobowych). Wyjście: `summary`, `items[{id, plain_text, first_step}]`, `warnings[]`.
- Kontrola ugruntowania przed pokazaniem: te same `id` co rekomendacje, każda liczba i data z tekstu występuje w wejściu, brak słów z czarnej listy. Pozycja, która nie przejdzie, dostaje tekst z szablonu.
- Koszt: ok. 0,03–0,06 USD za działkę (Opus 5.5), poniżej 0,002 USD (Haiku 5.5). Wpisać do README.

## Wdrożenie (Render.com, od 22.11)

- `render.yaml` (Blueprint): `zatrzymaj-wode-api` (Python, `rootDir: backend`, `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, region Frankfurt) i `zatrzymaj-wode` (statyczny, `npm ci && npm run build`, `dist`). Frontend dostaje host backendu w `VITE_API_URL` (sama nazwa hosta wystarcza, `https://` dopisuje klient).
- CORS w backendzie przepuszcza każdą domenę (`allow_origins=["*"]`, bez ciasteczek) – API jest publiczne, więc frontend z innej domeny nie dostaje błędów CORS.
- Wariant jednej usługi: gdy istnieje `frontend/dist` (albo `FRONTEND_DIST`), backend serwuje frontend pod `/` (bez CORS).
- Dysk na Render jest ulotny: działki przykładowe są w `backend/app/data/seed_cache/` (w repo, tylko do odczytu); własny cache ma pierwszeństwo.

## Frontend

- Jeden ekran: wyszukiwarka działki nad mapą, panel boczny z danymi, formularz kroku 4 (uprawa, zakres dat z domyślnym „od dziś na 30 dni”, 3 pytania tak/nie/nie wiem), karty działań w trzech grupach, opis z LLM pod kartami, sekcja „Źródła danych” z `provenance` (źródło, status, data danych, licencja).
- Markery działań i warstwy terenu na mapie. Karta pokazuje: co, kiedy, dlaczego (liczba z działki), efekt, pewność, czy warunkowa.
- `ParcelContext` trzymamy w stanie Reacta i wysyłamy w całości do `/api/recommend`.
- Prostota obsługi to 15% oceny: bez żargonu na pierwszym planie, nazwy wskaźników w rozwijanych szczegółach.
- **Styl „Pole z lotu ptaka”** (od 22.11, źródło: `styl-pole-z-lotu-ptaka/docs/DESIGN.md`): mapa na cały ekran, szklany pasek z wyszukiwarką i jedynym żółtym przyciskiem „Sprawdź działkę”, pływający panel (werdykt ze wskaźnikiem wody, przyczyny, maks. 3 działania + nawadnianie, najważniejsze liczby, pewność, szczegóły w akordeonie), A−/A+ i wysoki kontrast, krój Atkinson Hyperlegible Next (dołączony do builda). Tokeny i komponenty skopiowane 1:1 do `frontend/src/style/`; dodatki w `app.css`. Algorytmy prezentacji (werdykt, wskaźnik, fakty) w `frontend/src/lib/present.js`. Bez dekoracyjnych animacji.

## Otwarte kwestie

- NMT: czy WCS odpowiada z sieci hackathonu i w jakim czasie (zmierzyć w pierwszej godzinie). Jeśli nie zdąży, zmniejszyć bufor ze 150 do 50 m albo pobrać siatkę 5 m.
- Pytania do mentorów są w SPEC §7 i w triażu: przesunięcie KBW z ET0 FAO-PM względem SMSR, okna krytyczne upraw, daty siewu ozimin, format numeru działki od jury.
- Sprawdzone 21.11 (szczegóły w `docs/pomiary-zrodel.md`): warstwy WMS (ORTO, KIEG, cieniowanie), NMT WCS w EPSG:3857 (4,5–9 s przy buforze 50 m).
- IUNG WCS: w EPSG:2180 oś `x` = northing, `y` = easting; zamiana daje siatkę z innego miejsca bez żadnego błędu.
- ULDK przy przeciążeniu robi 302 na adres zwracający niekończący się gzip: nie śledzimy przekierowań w ULDK.
- Open-Meteo archive: dzienny limit na IP (429) w sieci hackathonu; plan: test z innego IP (hotspot).
- Overpass z sieci hackathonu nie odpowiada; cieki „nie oceniono”, R11 i R14 warunkowo.
