# Silnik oceny wody i rekomendacji dla działki rolnej – opis, reguły i ewaluacja

Dokument do przeniesienia do innego projektu. Stan na 21.11.2026 (HackNation 2026, zadanie KOWR „Zatrzymaj wodę, chroń plony”).
Opisuje, **co liczy silnik, z jakich danych, jakie rady generuje i na jakich warunkach**, oraz **jak wypadła ewaluacja**.
Tabele reguł i progów są wygenerowane z plików konfiguracyjnych silnika (`backend/app/data/*.yaml`), przykładowe wyniki
z uruchomień silnika na działce testowej (dane zapisane w cache, bez zapytań do usług).

Zasady nadrzędne silnika:

- **Liczby liczy kod, nie LLM.** Każda liczba i każda rada pochodzi z deterministycznych obliczeń i reguł; LLM (planowany) tylko opisuje wynik.
- **Brak danych = „nie oceniono”**, nigdy cicha wartość domyślna. Reguła działa tylko na policzonym wskaźniku.
- **Kolejność działań jest wiążąca:** retencja (zatrzymanie wody) → agrotechnika → nawadnianie (zawsze ostatnie).
- **Niepewność jawnie:** przedziały zamiast pojedynczych liczb, częstość „n z 10”, pewność każdej rady z uzasadnieniem.
- **Inwestycje** (zastawka, oczko, nawadnianie) zawsze z dopiskiem o konsultacji z ODR / spółką wodną / Wodami Polskimi.

## Spis treści

1. Przepływ i kontrakty
2. Źródła danych (stan, problemy, licencje)
3. Silnik krok po kroku (teren, KBW, fazy uprawy, bilans FAO-56, prognoza, podatność, przyczyny)
4. Wszystkie rady (reguły) – warunki, pewność, teksty
5. Składanie wyniku: bramki, kolejność, pewność całości, język dla rolnika
6. Ewaluacja wyników
7. Znane problemy i rzeczy do walidacji
8. Sugestie rozwoju (zebrane w trakcie prac)
9. Mapa plików

## 1. Przepływ i kontrakty

| Krok | Endpoint | Wejście | Wyjście | Czas |
| --- | --- | --- | --- | --- |
| Wybór działki | `GET /api/parcel?q=<numer>` lub `?lat=&lon=` | numer ewidencyjny (TERYT) albo punkt | `Parcel` (geometria WGS84, centroid, pole, TERYT7) | 0,2–0,6 s (ULDK) |
| Dane działki | `POST /api/context` `{parcel, as_of?}` | geometria, dzień D | `ParcelContext`: pogoda, gleba, teren, cieki, satelita + `provenance[]` | 5–15 s na żywo, ~20 ms z cache |
| Ocena i rady | `POST /api/recommend` `{context | context_ref, request}` | uprawa, zakres dat, odpowiedzi rolnika | `AnalysisResult` | 40–180 ms |
| Cache | `GET /api/cache`, `GET /api/cache/{numer}` | – | lista zapisanych działek / kontekst | ms |

`request`:

```json
{"crop": "zboza_ozime", "range": {"from": "2026-11-21", "to": "2027-05-21"}, "sowing_date": null,
 "answers": {"irrigation_water": null, "drained": null, "ditch_with_weir": null, "sites": {"ditch0": true}}}
```

- Uprawy: `zboza_ozime`, `zboza_jare`, `kukurydza_ziarno`, `kukurydza_kiszonka`, `rzepak`, `ziemniak`, `burak_cukrowy`, `uzytki_zielone`.
- Dzień analizy D = `range.from` (≤ dziś, ≤ 10 lat wstecz); `range.to` ≤ D + 2 lata (ta sama data kalendarzowa, 29 lutego → 28 lutego).
- Odpowiedzi: `true` / `false` / `null` („nie wiem”). Wszystko działa na samych `null`; `null` daje radę warunkową.
- `answers.sites`: potwierdzenia rolnika przy znacznikach terenu (np. „Czy w tym miejscu jest rów?”).

Błędy: 404 `parcel_not_found`, 502 `uldk_unavailable`, 422 `invalid_request`, 409 `meteo_missing` (bez pogody nie ma oceny),
409 `meteo_range` (kontekst nie obejmuje 10 lat przed D – frontend pobiera kontekst dla D).

## 2. Źródła danych

| Źródło | Co daje | Zmierzony stan | Problemy i obejścia | Licencja |
| --- | --- | --- | --- | --- |
| ULDK GUGiK | geometria działki z numeru lub punktu | 0,2–0,6 s | przy przeciążeniu 302 na adres z niekończącym się strumieniem gzip → bez śledzenia przekierowań, limit 1 MB, 1 powtórka | GUGiK, bezpłatnie |
| Open-Meteo (ERA5/ERA5-Land) | dobowy opad, ET0 FAO-PM, Tmax, Tmin; 10–20 lat + prognoza 16 dni | ~1 s | **dzienny limit na IP** (10 lat ≈ 280 z 10 000 „wywołań”); w sieci hackathonu 429 → cache | CC BY 4.0 |
| IUNG-PIB (SMSR) WCS | kategorie podatności gleb na suszę I–IV, siatka 5 m | 0,4–0,7 s | **w EPSG:2180 oś x = northing, y = easting**; odwrotna kolejność zwraca siatkę z innego miejsca bez błędu (zweryfikowane z WMS) | brak jawnej licencji |
| ISRIC SoilGrids 2.0 | wv0033, wv1500 (kwantyle), piasek, ił, SOC; 250 m | 2,7–27 s, zwykle timeout | wolne, niestabilne; pełne pobranie z limitem 60 s | CC BY 4.0 |
| NMT GUGiK WCS | model terenu 1 m (próbkowany co 2 m), bufor 50 m | 4,5–10 s | wolny serwer; bufor zmniejszony z 150 do 50 m | GUGiK, bezpłatnie |
| Overpass (OSM) | rowy i cieki w promieniu 500 m | timeout (3 serwery, obie sieci) | przeciążone instancje; pełne pobranie z limitem 90 s; bez danych R14 = „nie oceniono” | ODbL |
| Sentinel-2 L2A (Earth Search) | NDMI (woda w roślinach), NDRE, NDVI; maska chmur SCL | ~3–6 s | kafel 20 m ≈ 0,35 MB, 10 m ≈ 1,1 MB; tryb lekki 2 MB (3 sceny NDMI), pełny 15–25 MB; tylko informacja | Copernicus |
| Rozporządzenie Dz.U. 2019 poz. 739 | progi KBW [uprawa × kategoria × okres] | stała | sparsowane automatycznie z tekstu ISAP | akt prawny |

**Cache** (`backend/cache/*.json.gz`, jeden plik na działkę): trafienie zwraca zapis bez zapytań; odświeżenie bierze źródła,
które teraz zawiodły, z zapisu (`provenance.mode = "cache"`). Pełne pobranie: `python -m app.prefetch <numer>` (20 lat pogody,
długie limity). Każde źródło ma w wyniku `provenance`: status (`ok|partial|timeout|error|empty`), tryb, czas, licencja, „dane do”, notatka.

## 3. Silnik krok po kroku

### 3.1 Teren (NMT)

1. Wypełnienie zagłębień **priority-flood** (Barnes i in. 2014); głębokość = teren wypełniony − teren (bez epsilonu).
2. Kierunki spływu **D8** (O'Callaghan i Mark 1984) na terenie wypełnionym z epsilonem; **akumulacja** = powierzchnia zlewni komórki.
3. Zagłębienia (spójne obszary o głębokości ≥ progu) **klasyfikowane po kształcie**:
   - **rów**: wąski i wydłużony (szerokość efektywna = pole / (obwód/2), wydłużenie = P²/(4πA)) i głęboki. W NMT nie widać przepustów pod drogami, więc odcinek rowu wygląda jak zamknięta niecka. Znacznik w punkcie przelewu (zwykle przy przepuście);
   - **miejsce na oczko**: zwarte, głębokie, w większości na działce;
   - **zastoisko**: płytkie, na działce.
4. **Odpływy**: komórki na brzegu działki, z których woda wypływa na zewnątrz, ze zlewnią ≥ progu (do 3, co najmniej 30 m od siebie).
   Od każdego odpływu silnik idzie w dół spływu (do 150 m) i sprawdza, do którego zagłębienia/rowu trafia woda; rowy są sortowane wg dopływu z działki.
5. Statystyki: nachylenie średnie i P90 (stopnie), różnica wysokości, dopływ z sąsiednich pól (**dolna granica** – zlewnia ucięta do bufora 50 m).

Progi terenu (`terrain.yaml`):

| Próg | Wartość | Źródło / status |
| --- | --- | --- |
| depression.min_depth_m | 0.1 | heurystyka: rząd dokładności wysokościowej NMT z LiDAR (ok. 0,1–0,2 m); płytsze zagłębienia to raczej szum i mikrorzeźba |
| depression.min_area_m2 | 50 | heurystyka z prototypu |
| depression.near_parcel_m | 20 | heurystyka: zagłębienia i rowy do 20 m od granicy działki uznajemy za związane z działką |
| ditch.max_effective_width_m | 6 | heurystyka: typowy rów melioracyjny ma szerokość w koronie ok. 2–5 m |
| ditch.min_elongation | 3 | heurystyka: wydłużenie P²/(4πA); koło = 1, pas 3×100 m ≈ 11 |
| ditch.min_depth_m | 0.25 | heurystyka: rowy mają zwykle głębokość 0,5–1,5 m |
| pond.min_depth_m | 0.3 | heurystyka: płytsze zagłębienia to okresowe zastoiska, nie miejsce na oczko |
| pond.min_area_m2 | 200 | heurystyka |
| pond.min_inside_parcel_share | 0.5 | heurystyka: proponujemy oczko tylko tam, gdzie większość zagłębienia leży na działce |
| wet_spot.min_inside_parcel_share | 0.5 | heurystyka |
| flow.path_min_catchment_m2 | 2000 | heurystyka z prototypu |
| flow.outlet_min_catchment_m2 | 1000 | heurystyka z prototypu |
| flow.flat_terrain_p90_deg | 2.0 | heurystyka: przy mniejszym nachyleniu kierunki spływu D8 wyznacza głównie mikrorzeźba (koleiny, redliny) |

### 3.2 KBW – klimatyczny bilans wodny (próg suszy z rozporządzenia)

- KBW = ΣP − ΣET0 w każdym z 14 okresów 60-dniowych (21 III–20 V, 1 IV–31 V, …, 1 VIII–30 IX).
- Próg działki = średnia progów kategorii I–IV ważona udziałem kategorii IUNG na działce; „x” w tabeli = brak obniżenia plonów (status `brak_progu`), „-” = uprawa niewskazana na tej kategorii (pomijamy jej udział).
- Status w dniu D (ostatni pełny okres ≤ D): `zagrozenie` (margines ≤ −15 mm), `na_granicy` (|margines| < 15 mm), `brak_zagrozenia`, `poza_okresem` (D poza 21 III–30 IX – pokazujemy ostatni okres sezonu), `brak_progu`, `brak_danych`.
- **Przybliżenie metodyki SMSR**: zamiast parowania liczonego przez IUNG używamy ET0 FAO Penman-Monteith z Open-Meteo (zawsze z dopiskiem).

Przykład progów (mm) – zboża ozime, okres 21 III–20 V: kat. I: -129, kat. II: -150, kat. III: -188, kat. IV: -215.
Pełna tabela: 14 upraw × 4 kategorie × 14 okresów w `kbw_thresholds.yaml` (źródło: załącznik do Dz.U. 2019 poz. 739).

### 3.3 Fazy uprawy i współczynnik Kc (FAO-56)

Krzywa Kc w 4 fazach (początkowa, rozwój, środkowa, końcowa), poza sezonem Kc = 0.3 (gleba bez okrywy), w spoczynku zimowym 0.4.
Start sezonu: uprawy jare – data siewu od rolnika albo typowa (heurystyka); oziminy, rzepak, łąki – **początek wegetacji** = pierwszy dzień od 1 III, od którego 5-dniowa średnia temperatury ≥ 5°C.

| Uprawa | Kc ini / mid / end | Zr [m] | p | Fazy [dni] | Start | Źródło faz |
| --- | --- | --- | --- | --- | --- | --- |
| Zboża ozime | 0.4 / 1.15 / 0.3 | 1.5–1.8 | 0.55 | 20/25/60/30 | vegetation | FAO-56 tab. 11 nie ma wiersza dla ozimin w Europie; po starcie wegetacji fazy jak zboża jare 35–45°N (20/25/60/30) – heurystyka |
| Zboża jare | 0.3 / 1.15 / 0.3 | 1.0–1.5 | 0.55 | 20/25/60/30 | siew 04-01 | FAO-56 tab. 11: Barley/Oats/Wheat, 35–45°N, siew marzec/kwiecień |
| Kukurydza na ziarno | 0.3 / 1.2 / 0.35 | 1.0–1.7 | 0.55 | 30/40/50/50 | siew 05-01 | FAO-56 tab. 11: Maize (grain), Idaho USA, siew kwiecień |
| Kukurydza na kiszonkę | 0.3 / 1.2 / 0.6 | 1.0–1.7 | 0.55 | 30/40/50/30 | siew 05-01 | FAO-56 tab. 11: Maize (grain), Hiszpania/Kalifornia (krótsza faza końcowa, zbiór wcześniej) |
| Rzepak | 0.35 / 1.07 / 0.35 | 1.0–1.5 | 0.6 | 20/30/45/30 | vegetation | FAO-56 tab. 11 nie zawiera rzepaku; fazy po starcie wegetacji – heurystyka (zbiór ok. połowy lipca) |
| Ziemniaki | 0.5 / 1.15 / 0.75 | 0.4–0.6 | 0.35 | 30/35/50/30 | siew 04-20 | FAO-56 tab. 11: Potato, Europe, sadzenie kwiecień |
| Burak cukrowy | 0.35 / 1.2 / 0.7 | 0.7–1.2 | 0.55 | 50/40/50/40 | siew 04-05 | FAO-56 tab. 11: Sugarbeet, Idaho USA, siew kwiecień |
| Użytki zielone | 0.4 / 0.95 / 0.85 | 0.5–1.5 | 0.6 | 10/20/150/30 | vegetation | FAO-56 tab. 11: Grass Pasture 10/20 dni; faza środkowa do końca września i końcowa w październiku – heurystyka |

Kc, Zr, p: FAO-56 tab. 12 i 22 (pobrane ze strony FAO). Bez korekty Kc na klimat (brak RHmin i wiatru).

### 3.4 Bilans wody w strefie korzeniowej (FAO-56 rozdz. 8)

```
ETc = Kc · ET0
p   = clip(p_tab + 0,04 · (5 − ETc), 0,1, 0,8)
RAW = p · TAW                         # łatwo dostępna woda
Ks  = 1                 gdy Dr ≤ RAW
Ks  = (TAW − Dr) / ((1 − p) · TAW)    gdy Dr > RAW
Dr_i = clip(Dr_{i−1} − P_i + Ks · ETc_i, 0, TAW)   # nadmiar opadu odpływa w głąb
```

Start 1 marca z Dr = 0 (gleba przy polowej pojemności po zimie). Brak spływu powierzchniowego, podsiąku i nawadniania.
**TAW jako przedział**: do 3 oszacowań zapasu wody na 1,5 m (dolna i górna granica kategorii IUNG ważone udziałem; SoilGrids (FC − WP)·1,5 m) × 2 głębokości korzeni (Zr min/max) = do 6 przebiegów; wynik = mediana i zakres.

| Kategoria IUNG | TAW na 1,5 m [mm] | Źródło |
| --- | --- | --- |
| I | 90.0–127.5 | rozporządzenie: < 127,5 mm; dolna granica 90 mm – heurystyka |
| II | 127.5–169.9 | rozporządzenie |
| III | 170.0–202.5 | rozporządzenie |
| IV | 202.5–250.0 | rozporządzenie: > 202,5 mm; górna granica 250 mm – heurystyka |
| organic | 202.5–300.0 | heurystyka: gleby organiczne mają dużą pojemność wodną |

### 3.5 Prognoza na wybrany zakres dat

Od stanu w dniu D do `range.to`: pierwsze ≤ 16 dni z prognozy pogody (gdy D = dzień pobrania danych), dalej **10 scenariuszy**:
pogoda z tych samych dni kalendarzowych w 10 poprzednich latach. Liczymy tylko dni w sezonie wzrostu uprawy.
Wynik: szansa niedoboru „n z 10” (środkowy przebieg TAW), dni do przekroczenia RAW (przedział z scenariuszy), niedobór Σ(ETc − ETc,adj)
w mm i m³ na działkę (przedział z przebiegów TAW). Status `poza_sezonem_uprawy`, gdy zakres nie obejmuje sezonu.

### 3.6 Podatność z 10 lat

10 ostatnich pełnych sezonów przed D: w ilu KBW spadł poniżej progu (`n_kbw`), w ilu było ≥ 10 dni stresu (Ks < 1) w fazie pełni wzrostu
(`n_ks`), typowe miesiące ryzyka (≥ 5 dni stresu w miesiącu w ≥ 3 sezonach).

### 3.7 Przyczyny C1–C4

| Kod | Przyczyna | Dominująca, gdy | Pewność |
| --- | --- | --- | --- |
| C1 | brak opadu, upał | KBW w okresie odniesienia poniżej progu albo próg przekroczony w ≥ 3 z 10 sezonów | średnia |
| C2 | słaba retencja gleby | kategorie IUNG I–II ≥ 50% działki | średnia (nie oceniono bez IUNG) |
| C3 | spływ z pola | nachylenie P90 > 7° (11° na glebach lekkich) albo odpływ zbierający ≥ 1 ha na niepłaskim terenie | średnia / niska na płaskim |
| C4 | uprawa w ryzykownym okresie | ≥ 5 z 10 sezonów ze stresem w pełni wzrostu | niska (okna krytyczne niezweryfikowane) |

## 4. Wszystkie rady (reguły)

Kolejność w wyniku: grupa (retencja → agrotechnika → nawadnianie), w grupie wg priorytetu. Pokazujemy najwyżej 5 rad (nawadnianie,
jeśli występuje, zawsze zostaje jako ostatnie). Każda rada ma: krótki tytuł (lista bez szczegółów), pełny komunikat, „kiedy” (zdanie i
skrót), „dlaczego” (z liczbami z działki), efekt, pewność + uzasadnienie, dowody (`evidence`: pola wyniku), źródła, opcjonalnie pytanie
przy znaczniku mapy i dopisek o konsultacji (inwestycje).

| Kod | Krótka rada | Grupa / priorytet | Warunek | Pewność | Inwestycja |
| --- | --- | --- | --- | --- | --- |
| R11 | Postaw zastawkę na rowie | retencja / 1 | NMT wykrył rów przy działce (nie odrzucony przez rolnika); albo rów z OSM ≤ 100 m; albo rolnik: „jest rów z zastawką”. Wybierany rów, do którego spływa najwięcej wody z działki. | średnia (rów rozpoznany po kształcie); wysoka po potwierdzeniu przez rolnika | tak |
| R6 | Zrób oczko wodne w naturalnym zagłębieniu | retencja / 2 | Zagłębienie sklasyfikowane jako miejsce na oczko (≥ 0,3 m, ≥ 200 m², ≥ 50% na działce), nieodrzucone przez rolnika. | średnia; wysoka po potwierdzeniu, że woda tam stoi | tak |
| R3 | Załóż pas trawy tam, gdzie woda odpływa z pola | retencja / 3 | Odpływ z działki zbiera ≥ 1 ha i teren nie jest płaski (P90 ≥ 2°), a stok nie jest stromy (wtedy R2). | niska przy P90 < 3° (kierunek spływu wyznacza mikrorzeźba); średnia przy wyraźnym nachyleniu | nie |
| R2 | Wprowadź pasy trawy w poprzek stoku | retencja / 4 | Nachylenie P90 > 7° (gleby średnie/ciężkie) albo > 11° (lekkie). | średnia; niska bez kategorii gleby (nieznany próg) | nie |
| R14 | Zostaw pas zieleni przy cieku | retencja / 5 | Ciek (OSM) ≤ 50 m od działki. Bez danych OSM: „nie oceniono”. | średnia (mapa OSM) | nie |
| R1 | Orz i siej w poprzek stoku | agrotechnika / 1 | Nachylenie P90 > 3° i uprawa rzędowa (kukurydza, ziemniak, burak). | średnia | nie |
| R8 | Zwiększ ilość próchnicy w glebie | retencja / 6 | C2 dominująca i węgiel organiczny (SoilGrids) < 10 g/kg. | niska (SoilGrids 250 m) | nie |
| R15 | Oszczędzaj wodę w glebie przed suchym okresem | agrotechnika / 0 | W zakresie dat szansa niedoboru ≥ 5 z 10 (wersja z terminem z prognozy) albo C4 dominująca (wersja z typowymi miesiącami ryzyka). | min(średnia, pewność TAW) z prognozy; niska z historii (heurystyczne fazy) | nie |
| R7 | Orz rzadziej i zostaw resztki roślin na polu | agrotechnika / 2 | C2 dominująca (gleba lekka) i policzony zapas wody w glebie. | min(średnia, pewność TAW) | nie |
| R16 | Postaw na terminy zabiegów, nie na drogą retencję | agrotechnika / 3 | C1 dominująca, a C2 i C3 nie – uczciwy komunikat, że retencja niewiele tu zmieni. | średnia (KBW to przybliżenie SMSR) | nie |
| IRR | Zaplanuj nawadnianie | nawadnianie / 1 | Zapas poniżej RAW w dniu D albo szansa niedoboru ≥ 5 z 10, policzony niedobór ≥ 1 mm, a rolnik nie odpowiedział „nie mam wody”. Zawsze ostatnia. | min(średnia, pewność TAW); warunkowa przy `irrigation_water = null` | tak |

### Teksty rad (z `rules.yaml`)

**R11 – Postaw zastawkę na rowie**

- `message`: Zatrzymaj wodę w rowie zastawką. Przy działce jest rów, do którego spływa woda z pola.
- `message_confirmed_weir`: Przy działce jest rów z zastawką. Steruj nią: zamykaj po roztopach, otwieraj przy podtopieniu.
- `when_text`: Zamknij zastawkę po roztopach (luty–marzec), żeby zatrzymać wodę wiosenną w rowie i w glebie. Otwórz ją, gdy pole jest podtopione.
- `when_short`: luty–marzec
- `why`: Na mapie wysokości terenu widać wąskie obniżenie ok. {length_m} m długości i do {max_depth_m} m głębokości ({distance}), najpewniej rów.
- `why_outlets`:  Woda z pola trafia do niego w {n_outlets} miejscach.
- `why_osm`: Rów z mapy OpenStreetMap ok. {distance_m} m od działki.
- `why_farmer`: Rolnik potwierdził, że przy działce jest rów z zastawką.
- `effect`: Wyższy poziom wody w rowie spowalnia odpływ i podnosi wilgotność gleby przy rowie wiosną.
- `question`: Czy w tym miejscu jest rów?
- źródła: Katalog działań NWRM (nwrm.eu): sterowanie odpływem z drenażu i rowów; Wody Polskie: program przeciwdziałania niedoborowi wody

**R6 – Zrób oczko wodne w naturalnym zagłębieniu**

- `message`: Zachowaj naturalne zagłębienie i rozważ oczko wodne. Woda sama tu spływa.
- `when_text`: Prace ziemne najlepiej po zbiorze, przy suchej glebie (sierpień–październik).
- `when_short`: sierpień–październik
- `why`: Zagłębienie ok. {area_m2} m², do {max_depth_m} m głębokości, pojemność terenu ok. {volume_m3} m³; {inside_parcel_pct}% leży na działce.
- `effect`: Zatrzymuje wodę z roztopów i ulew na działce zamiast odpływu; poprawia wilgotność w otoczeniu.
- `question`: Czy wiosną albo po ulewie stoi tu woda?
- źródła: Katalog działań NWRM (nwrm.eu): stawy i oczka śródpolne

**R3 – Załóż pas trawy tam, gdzie woda odpływa z pola**

- `message`: Załóż pas trawy na linii spływu przy miejscu, gdzie woda opuszcza pole.
- `when_text`: Wysiej trawę w pasie pod koniec lata lub wczesną jesienią (sierpień–wrzesień) albo wiosną.
- `when_short`: sierpień–wrzesień
- `why`: Woda z ok. {catchment_ha} ha pola zbiera się w jeden strumień i w tym miejscu odpływa z działki ({terrain_word}).
- `effect`: Pas zadarniony spowalnia spływ, zatrzymuje glebę i daje wodzie czas na wsiąknięcie.
- źródła: Katalog działań NWRM (nwrm.eu): pasy buforowe i zadarnienie

**R2 – Wprowadź pasy trawy w poprzek stoku**

- `message`: Stok jest stromy: wprowadź pasy trawy w poprzek stoku albo uprawę pasową.
- `when_text`: Zaplanuj przy najbliższej zmianie układu upraw (po zbiorze).
- `when_short`: po zbiorze
- `why`: Nachylenie na 10% działki przekracza {slope_p90_deg}° (próg {threshold_deg}° dla tej gleby).
- `effect`: Przerywa spływ po stoku, ogranicza erozję i zwiększa wsiąkanie.
- źródła: Katalog działań NWRM (nwrm.eu): uprawa pasowa i pasy buforowe na stokach

**R14 – Zostaw pas zieleni przy cieku**

- `message`: Zostaw pas zieleni wzdłuż cieku przy działce.
- `when_text`: Pas zakładaj wiosną lub pod koniec lata.
- `when_short`: wiosna lub koniec lata
- `why`: Ciek płynie ok. {distance_m} m od działki.
- `effect`: Pas buforowy zatrzymuje spływ i glebę zanim trafią do cieku.
- źródła: Katalog działań NWRM (nwrm.eu): strefy buforowe wzdłuż cieków

**R1 – Orz i siej w poprzek stoku**

- `message`: Uprawiaj i siej w poprzek stoku, nie wzdłuż.
- `when_text`: Przy najbliższej uprawie i siewie.
- `when_short`: przy siewie
- `why`: Nachylenie na 10% działki przekracza {slope_p90_deg}°, a {crop_name} to uprawa rzędowa, przy której woda łatwo spływa międzyrzędziami.
- `effect`: Bruzdy w poprzek stoku zatrzymują wodę i ograniczają spływ.
- źródła: Katalog działań NWRM (nwrm.eu): uprawa konturowa

**R8 – Zwiększ ilość próchnicy w glebie**

- `message`: Zwiększaj ilość próchnicy w glebie: lekka gleba z małą ilością materii organicznej słabo trzyma wodę.
- `when_text`: Po zbiorze: międzyplon, obornik lub kompost; efekt narasta przez kilka sezonów.
- `when_short`: po zbiorze
- `why`: Większość działki to gleba lekka, a w wierzchniej warstwie jest mało materii organicznej.
- `effect`: Więcej próchnicy zwiększa zdolność gleby do zatrzymywania wody; efekt jest stopniowy.
- źródła: Katalog działań NWRM (nwrm.eu): zwiększanie materii organicznej w glebie

**R15 – Oszczędzaj wodę w glebie przed suchym okresem**

- `message_forecast`: W wybranym okresie grozi niedobór wody: oszczędzaj wodę w glebie przed tym terminem.
- `message_history`: Przygotuj się na niedobór wody w okresie największego ryzyka dla tej uprawy.
- `action`: Ogranicz straty wody z gleby: płytka uprawa zamiast głębokiej przed siewem, resztki pożniwne jako mulcz, terminowy siew.
- `when_forecast`: Zanim zacznie brakować wody w glebie, najpewniej {when_text}.
- `when_history`: Najczęściej w {months}.
- `why_forecast`: W wybranym okresie {chance_text}.
- `why_history`: Na tym polu niedobory wody w czasie wzrostu {frequency_text}.
- `effect`: Mniej parowania z gleby i lepsze wykorzystanie wody zgromadzonej po zimie.
- źródła: FAO-56: bilans wody w strefie korzeniowej; Kodeks Dobrej Praktyki Rolniczej (MRiRW)

**R7 – Orz rzadziej i zostaw resztki roślin na polu**

- `message`: Gleba lekka szybko traci wodę: zostaw resztki roślin jako mulcz i ogranicz orkę.
- `when_text`: Po zbiorze i przed siewem: zostaw resztki na polu, ogranicz orkę wiosenną.
- `when_short`: po zbiorze i przed siewem
- `why`: Większość działki to gleba lekka (piaszczysta), która słabo zatrzymuje wodę.
- `effect`: Mulcz ogranicza parowanie z powierzchni gleby.
- źródła: Katalog działań NWRM (nwrm.eu): uprawa konserwująca i mulczowanie

**R16 – Postaw na terminy zabiegów, nie na drogą retencję**

- `message`: Zatrzymanie wody na tej działce niewiele zmieni: główną przyczyną jest brak opadu.
- `why`: Susze wynikają tu głównie z małej ilości deszczu; gleba i ukształtowanie terenu nie powodują dużych strat wody.
- `effect`: Lepiej skupić się na terminach zabiegów i doborze odmian niż na kosztownej retencji.
- źródła: SPEC §5.2 (R16)

**IRR – Zaplanuj nawadnianie**

- `message`: Jeśli masz źródło wody, nawadnianie uzupełni niedobór w wybranym okresie.
- `message_confirmed`: Zaplanuj nawadnianie: w wybranym okresie zabraknie wody w glebie.
- `when_text`: Gdy zacznie brakować wody, najpewniej {when_text}; podlewaj, zanim rośliny zaczną więdnąć.
- `why`: W wybranym okresie roślinom może zabraknąć {amount} wody na całą działkę ({area} ha).
- `effect`: Uzupełnienie wody w okresie niedoboru ogranicza straty plonu.
- `consult_extra`: Pobór wody do nawadniania (studnia, ciek) może wymagać zgody wodnoprawnej – sprawdź w Wodach Polskich.
- źródła: FAO-56: bilans wody i współczynnik stresu Ks

Wspólny dopisek przy inwestycjach (bramka G4): Przed budową lub przebudową skonsultuj się z doradcą ODR, spółką wodną albo Wodami Polskimi: urządzenia wodne (zastawki, stawy) mogą wymagać zgłoszenia wodnoprawnego.

Progi reguł (`rules.yaml`):

| Próg | Wartość | Źródło / status |
| --- | --- | --- |
| steep_p90_deg_light_soil | 11 | silnik.md, tabela przyczyn C3 (gleby lekkie) |
| steep_p90_deg_other_soil | 7 | silnik.md, tabela przyczyn C3 (gleby średnie) |
| contour_sowing_p90_deg | 3 | silnik.md, R1: P90 > 2–3°; przyjęto górną granicę (heurystyka) |
| low_soc_gkg | 10 | heurystyka: mało węgla organicznego w wierzchniej warstwie gleby lekkiej |
| stress_chance_r15 | 5 | silnik.md, R15: szansa stresu ≥ 5 z 10 |
| stress_chance_irrigation | 5 | heurystyka: nawadnianie, gdy niedobór w co najmniej połowie scenariuszy |
| concentrated_flow_min_ha | 1.0 | heurystyka: odpływ zbierający wodę z ≥ 1 ha uznajemy za wyraźną linię spływu |
| flow_medium_conf_p90_deg | 3 | heurystyka: poniżej 3° kierunek spływu jest niepewny (mikrorzeźba) |
| ditch_osm_max_m | 100 | silnik.md, R11: rów ≤ 100 m |
| watercourse_buffer_max_m | 50 | heurystyka: ciek do 50 m od granicy działki |

Uprawy rzędowe (R1): kukurydza_ziarno, kukurydza_kiszonka, ziemniak, burak_cukrowy

## 5. Składanie wyniku

- **Bramki**: G1 reguła tylko na policzonym wskaźniku; G2 nawadnianie zawsze ostatnie; G3 brak danych → lista `not_evaluated` z powodem; G4 inwestycje z dopiskiem o konsultacji.
- **Pewność rady** = minimum pewności jej wejść (`wysoka > srednia > niska > nie_oceniono`), z polem `confidence_reason` (po polsku, dla rolnika).
- **Pewność całości** = min(średnia, pewność TAW, niska gdy ≥ 2 źródła zawiodły). KBW to przybliżenie SMSR, więc całość nigdy nie jest „wysoka”.
- **Pewność TAW**: średnia, gdy max/min przebiegów ≤ 2,5; niska przy większym rozrzucie albo < 3 oszacowaniach.
- **Język dla rolnika** (`plain.py`): bez „scenariuszy”, KBW, mm i procentów w nagłówku; liczby zostają w `headline_technical` i w szczegółach.

| Wynik | Tekst |
| --- | --- |
| szansa niedoboru 0 z 10 | „wody w glebie powinno wystarczyć” |
| 1–3 z 10 | „wody raczej wystarczy, chyba że rok będzie wyjątkowo suchy” |
| 4–6 z 10 | „wody może zabraknąć” (+ „najpewniej od początku/połowy/końca <miesiąca>”) |
| 7–9 z 10 | „wody prawdopodobnie zabraknie” |
| 10 z 10 | „wody niemal na pewno zabraknie” |
| niedobory w ≤ 20% sezonów | „zdarzają się rzadko” |
| ≤ 50% | „zdarzają się co kilka lat” |
| ≤ 80% | „zdarzają się w większości lat” |
| > 80% | „zdarzają się prawie co roku” |
| KBW: zagrożenie / na granicy / brak / poza okresem | „padało za mało…” / „padało niewiele, na granicy suszy” / „padało wystarczająco” / „poza sezonem wzrostu, susza rolnicza nie grozi” |

Pola `AnalysisResult`: `state` (`kbw`, `soil_water` z `taw_mm`, `dr_mm`, `pct_of_taw`, `safe_level_pct`, `below_raw`, faza, Kc;
`headline`, `headline_key`, `headline_more`, `headline_technical`), `forecast`, `susceptibility`, `causes[C1..C4]`,
`recommendations[]`, `not_evaluated[]`, `uncertainty{overall, reasons}`, `provenance[]`, `limitations[]`.

## 6. Ewaluacja wyników

### 6.1 Testy automatyczne (45, wszystkie przechodzą, bez sieci)

| Obszar | Co sprawdzają |
| --- | --- |
| Źródła | przeliczenie WGS84 → EPSG:2180 zgodne z ULDK co do 0,01 m; parsowanie ULDK i IUNG; odrzucenie siatki IUNG z zamienionymi osiami; adapter nigdy nie rzuca wyjątku; odrzucenie przekierowania i zbyt dużej odpowiedzi |
| Teren | płaszczyzna (akumulacja = liczba komórek w kolumnie), misa o znanej objętości (dokładnie bez epsilonu), rów vs oczko vs zastoisko na sztucznym terenie, regresja na prawdziwym NMT działki testowej |
| KBW | sumy okresu liczone ręcznie, próg ważony, „x” i „-” z tabeli, **listopad → `poza_okresem`** |
| Bilans | krok FAO-56 zgodny z wzorami (Ks, RAW, odpływ nadmiaru), start wegetacji, krzywa Kc, regresja na stałych danych, regresja na prawdziwych danych |
| Reguły | zastawka zamiast oczka na działce testowej, potwierdzenia rolnika, brak źródeł → `not_evaluated`, stromy teren → R2+R1, niezmienniki (każda rada ma dowody, uzasadnienie pewności i tytuł; G4 przy inwestycjach; kolejność grup; nawadnianie ostatnie) |
| API i cache | walidacja dat i uprawy (422), 409 bez pogody i przy złym zakresie, trafienie w cache bez zapytań, rada przez `context_ref`, scalanie źródeł z zapisem |

### 6.2 Weryfikacja terenu z ortofotomapą (działka 046101_1.0445.7, Bydgoszcz)

- Pierwsza wersja (bez klasyfikacji kształtu) pokazywała 2 z 3 „miejsc na oczko” w **rowach przy drogach** (236 m², 1,18 m głębokości, 0% na działce;
  524 m², 0,98 m, 22% na działce). Przyczyna: brak przepustów w NMT. Po klasyfikacji kształtu oba to rowy (szerokość 1,9 i 2,3 m, długość 108 i 184 m),
  zgodnie z ortofotomapą; odpływy z pola trafiają do rowu przy SW krawędzi (2,26 ha zlewni z działki).
- Algorytmy hydrologiczne zgodne z wynikami analitycznymi na sztucznym terenie (misa: objętość dokładna; płaski teren: brak fałszywych zagłębień).

### 6.3 Błąd wykryty testem: osie IUNG

Zapytanie WCS z zamienionymi osiami zwracało poprawną siatkę z miejsca oddalonego o ok. 140 km (liczba komórek przypadkiem się zgadzała).
Po poprawce wynik zweryfikowano obrazem WMS IUNG (liczebności klas zgodne co do komórki). Działka testowa: 83% kat. IV, 17% kat. III
(wcześniej błędnie 100% kat. III). Wniosek: przy WCS w EPSG:2180 zawsze sprawdzać kolejność osi i porównywać z WMS.

### 6.4 Sensowność na prawdziwych danych (pogoda 2016–2026)

Dni stresu w pełni wzrostu (zboża ozime): najwięcej w latach znanych jako suche w Polsce (2018, 2019, 2022, 2023: 13–29 dni), mokry 2017: 0 dni.
Kukurydza: 2019 – 40, 2022 – 38, 2023 – 36, 2017 – 0, 2025 – 1.

### 6.5 Weryfikacja prognozy wstecz (sezon 2026)

Dla dni D w sezonie 2026 silnik widzi tylko dane do D (ocena „tak jak w dniu D”), prognoza na 60 dni. „Faktycznie” = ten sam bilans FAO-56
policzony na **rzeczywistej** pogodzie po D (środkowy przebieg TAW).

| Uprawa | D | Prognoza: niedobór w n z 10 | Prognoza: dni do niedoboru (mediana) | Faktycznie niedobór? | Faktycznie od dnia | Faktycznie dni stresu | Niedobór prognoza / faktycznie [mm] |
| --- | --- | --- | --- | --- | --- | --- | --- |
| zboza_ozime | 2026-05-01 | 10 | 15.0 | tak | 2 | 41 | 67.9 / 60.6 |
| zboza_ozime | 2026-06-01 | 10 | 1.0 | tak | 1 | 43 | 70.7 / 51.7 |
| zboza_ozime | 2026-07-01 | 10 | 1.0 | tak | 1 | 13 | 5.9 / 6.3 |
| zboza_jare | 2026-05-01 | 8 | 26.5 | tak | 28 | 19 | 51.8 / 34.2 |
| zboza_jare | 2026-06-01 | 10 | 2.5 | tak | 2 | 50 | 109.1 / 92.2 |
| zboza_jare | 2026-07-01 | 10 | 1.0 | tak | 1 | 44 | 42.3 / 62.2 |
| kukurydza_ziarno | 2026-05-01 | 0 | None | nie | – | 0 | 0.0 / 0.0 |
| kukurydza_ziarno | 2026-06-01 | 3 | 48 | tak | 59 | 2 | 1.4 / 1.9 |
| kukurydza_ziarno | 2026-07-01 | 8 | 32.0 | tak | 29 | 25 | 44.3 / 25.6 |
| ziemniak | 2026-05-01 | 10 | 21.0 | tak | 1 | 39 | 68.4 / 52.3 |
| ziemniak | 2026-06-01 | 10 | 1.0 | tak | 1 | 55 | 123.0 / 124.7 |
| ziemniak | 2026-07-01 | 10 | 1.0 | tak | 1 | 52 | 127.6 / 125.7 |
| burak_cukrowy | 2026-05-01 | 6 | 58.0 | nie | – | 0 | 3.6 / 0.0 |
| burak_cukrowy | 2026-06-01 | 9 | 32 | tak | 39 | 20 | 33.3 / 28.2 |
| burak_cukrowy | 2026-07-01 | 10 | 6.5 | tak | 9 | 45 | 94.1 / 78.0 |
| rzepak | 2026-05-01 | 10 | 21.0 | tak | 21 | 34 | 56.8 / 38.9 |
| rzepak | 2026-06-01 | 10 | 1.0 | tak | 1 | 28 | 45.3 / 25.6 |
| rzepak | 2026-07-01 | 9 | 1 | tak | 1 | 3 | 0.8 / 0.9 |

- **Brier score = 0.053** (n = 18); odniesienie „zawsze stała częstość 0.89” = 0.099. Niższy = lepiej.
- Moment startu niedoboru: w 8 z 18 przypadków zapas był już na granicy w dniu D (prognoza „od razu”, trafiona). W pozostałych z niedoborem: zboza_ozime od 05-01: prognoza 15 dni, faktycznie 2; zboza_jare od 05-01: prognoza 26.5 dni, faktycznie 28; kukurydza_ziarno od 06-01: prognoza 48 dni, faktycznie 59; kukurydza_ziarno od 07-01: prognoza 32 dni, faktycznie 29; ziemniak od 05-01: prognoza 21 dni, faktycznie 1; burak_cukrowy od 06-01: prognoza 32 dni, faktycznie 39; burak_cukrowy od 07-01: prognoza 6.5 dni, faktycznie 9; rzepak od 05-01: prognoza 21 dni, faktycznie 21.
- Niedobór w mm: prognoza zwykle w tym samym rzędzie wielkości co faktyczny, raczej go zawyża (mediana różnicy +6.2 mm).
- Wyraźna pomyłka: burak cukrowy od 1 V (prognoza 6/10, faktycznie bez niedoboru).

**Ograniczenia tej ewaluacji (ważne):** jeden sezon, jedna działka; „prawda” to ten sam model na prawdziwej pogodzie, a nie obserwacja z pola
(sprawdza jakość scenariuszy pogodowych, nie poprawność modelu gleby i uprawy); w wielu przypadkach zapas był już na granicy w dniu D,
więc prognoza była łatwa (persystencja). Do prawdziwej walidacji potrzebne: tabele SMSR IUNG dla gmin, dane plonów, obserwacje wilgotności gleby.

### 6.6 Wyniki silnika dla działki testowej (D = 21.11.2026)

Działka 046101_1.0445.7 (Bydgoszcz, 2,66 ha, gleba 83% kat. IV / 17% kat. III, teren płaski, rów przy SW krawędzi). Źródła w zapisie:
pogoda, IUNG, NMT, Sentinel-2 (SoilGrids i Overpass niedostępne). Bez odpowiedzi rolnika (jak juror):

| Uprawa | Zakres | Zdanie główne | Rady (kod, pewność) |
| --- | --- | --- | --- |
| zboza_ozime | 30 dni | Wybrany okres wypada poza sezonem wzrostu tej uprawy. Wydłuż zakres dat do wiosny, żeby zobaczyć, czy na początku sezonu zabraknie wody. | R11 (srednia), R3 (niska), R15 (niska) |
| zboza_ozime | 182 dni | W wybranym okresie wody raczej wystarczy, chyba że rok będzie wyjątkowo suchy. | R11 (srednia), R3 (niska), R15 (niska) |
| zboza_jare | 30 dni | Wybrany okres wypada poza sezonem wzrostu tej uprawy. Wydłuż zakres dat do wiosny, żeby zobaczyć, czy na początku sezonu zabraknie wody. | R11 (srednia), R3 (niska), R15 (niska) |
| zboza_jare | 182 dni | W wybranym okresie wody w glebie powinno wystarczyć. | R11 (srednia), R3 (niska), R15 (niska) |
| kukurydza_ziarno | 30 dni | Wybrany okres wypada poza sezonem wzrostu tej uprawy. Wydłuż zakres dat do wiosny, żeby zobaczyć, czy na początku sezonu zabraknie wody. | R11 (srednia), R3 (niska), R15 (niska) |
| kukurydza_ziarno | 182 dni | W wybranym okresie wody w glebie powinno wystarczyć. | R11 (srednia), R3 (niska), R15 (niska) |
| kukurydza_kiszonka | 30 dni | Wybrany okres wypada poza sezonem wzrostu tej uprawy. Wydłuż zakres dat do wiosny, żeby zobaczyć, czy na początku sezonu zabraknie wody. | R11 (srednia), R3 (niska), R15 (niska) |
| kukurydza_kiszonka | 182 dni | W wybranym okresie wody w glebie powinno wystarczyć. | R11 (srednia), R3 (niska), R15 (niska) |
| rzepak | 30 dni | Wybrany okres wypada poza sezonem wzrostu tej uprawy. Wydłuż zakres dat do wiosny, żeby zobaczyć, czy na początku sezonu zabraknie wody. | R11 (srednia), R3 (niska) |
| rzepak | 182 dni | W wybranym okresie wody raczej wystarczy, chyba że rok będzie wyjątkowo suchy. | R11 (srednia), R3 (niska) |
| ziemniak | 30 dni | Wybrany okres wypada poza sezonem wzrostu tej uprawy. Wydłuż zakres dat do wiosny, żeby zobaczyć, czy na początku sezonu zabraknie wody. | R11 (srednia), R3 (niska), R15 (niska) |
| ziemniak | 182 dni | W wybranym okresie wody może zabraknąć, najpewniej od początku maja. | R11 (srednia), R3 (niska), R15 (srednia), IRR (srednia) |
| burak_cukrowy | 30 dni | Wybrany okres wypada poza sezonem wzrostu tej uprawy. Wydłuż zakres dat do wiosny, żeby zobaczyć, czy na początku sezonu zabraknie wody. | R11 (srednia), R3 (niska), R15 (niska) |
| burak_cukrowy | 182 dni | W wybranym okresie wody w glebie powinno wystarczyć. | R11 (srednia), R3 (niska), R15 (niska) |
| uzytki_zielone | 30 dni | Wybrany okres wypada poza sezonem wzrostu tej uprawy. Wydłuż zakres dat do wiosny, żeby zobaczyć, czy na początku sezonu zabraknie wody. | R11 (srednia), R3 (niska), R15 (niska) |
| uzytki_zielone | 182 dni | W wybranym okresie wody raczej wystarczy, chyba że rok będzie wyjątkowo suchy. | R11 (srednia), R3 (niska), R15 (niska) |

Pełny przykład (ziemniaki, 6 miesięcy, bez odpowiedzi rolnika):

- Nagłówek: W wybranym okresie wody może zabraknąć, najpewniej od początku maja. Teraz jest poza sezonem wzrostu, susza rolnicza nie grozi. Na tym polu niedobory wody w czasie wzrostu zdarzają się prawie co roku, najczęściej w czerwcu, lipcu, sierpniu i wrześniu.
- Wersja techniczna: Teraz jest poza sezonem monitoringu suszy (21 III–30 IX). W wybranym okresie zapas wody w glebie spadnie poniżej bezpiecznego poziomu w 5 z 10 scenariuszy pogody. W ostatnich latach niedobór wody w pełni wzrostu wystąpił w 9 z 10 sezonów.
- **Postaw zastawkę na rowie** (R11, retencja, pewność srednia, warunkowa; luty–marzec)
  - Zatrzymaj wodę w rowie zastawką. Przy działce jest rów, do którego spływa woda z pola.
  - Kiedy: Zamknij zastawkę po roztopach (luty–marzec), żeby zatrzymać wodę wiosenną w rowie i w glebie. Otwórz ją, gdy pole jest podtopione.
  - Dlaczego: Na mapie wysokości terenu widać wąskie obniżenie ok. 184 m długości i do 0,98 m głębokości (częściowo na działce), najpewniej rów. Woda z pola trafia do niego w 2 miejscach.
  - Skąd ta pewność: Rów rozpoznany po kształcie obniżenia w modelu terenu (heurystyka). Potwierdź na mapie, żeby podnieść pewność.
- **Załóż pas trawy tam, gdzie woda odpływa z pola** (R3, retencja, pewność niska; sierpień–wrzesień)
  - Załóż pas trawy na linii spływu przy miejscu, gdzie woda opuszcza pole.
  - Kiedy: Wysiej trawę w pasie pod koniec lata lub wczesną jesienią (sierpień–wrzesień) albo wiosną.
  - Dlaczego: Woda z ok. 2,1 ha pola zbiera się w jeden strumień i w tym miejscu odpływa z działki (teren prawie płaski).
  - Skąd ta pewność: Teren prawie płaski (nachylenie do 2,64°): kierunek spływu wyznacza głównie mikrorzeźba, np. koleiny.
- **Oszczędzaj wodę w glebie przed suchym okresem** (R15, agrotechnika, pewność srednia; przed końcem kwietnia)
  - W wybranym okresie grozi niedobór wody: oszczędzaj wodę w glebie przed tym terminem. Ogranicz straty wody z gleby: płytka uprawa zamiast głębokiej przed siewem, resztki pożniwne jako mulcz, terminowy siew.
  - Kiedy: Zanim zacznie brakować wody w glebie, najpewniej pod koniec kwietnia.
  - Dlaczego: W wybranym okresie wody może zabraknąć: w podobnych latach zdarzało się to mniej więcej co drugi raz.
  - Skąd ta pewność: Scenariusze z pogody 10 poprzednich lat, nie prognoza na miesiące. Zapas wody w glebie z map o zbliżonych wartościach.
- **Zaplanuj nawadnianie** (IRR, nawadnianie, pewność srednia, warunkowa; na początku maja)
  - Jeśli masz źródło wody, nawadnianie uzupełni niedobór w wybranym okresie.
  - Kiedy: Gdy zacznie brakować wody, najpewniej na początku maja; podlewaj, zanim rośliny zaczną więdnąć.
  - Dlaczego: W wybranym okresie roślinom może zabraknąć do ok. 66 m³ wody na całą działkę (2,66 ha).
  - Skąd ta pewność: Niedobór z bilansu wody FAO-56; zakres zależy od zapasu wody w glebie. Zapas wody w glebie z map o zbliżonych wartościach.
- Nie oceniono: R14 (brak danych o ciekach (OpenStreetMap nie odpowiedział))

Te same dane z odpowiedziami „to rów” i „mam wodę”: R11 (wysoka), R3 (niska), R15 (srednia), IRR (srednia)

Częstość rad we wszystkich 32 uruchomieniach (8 upraw × 2 zakresy × z/bez odpowiedzi): R11: 32, R3: 32, R15: 28, IRR: 2.

## 7. Znane problemy i rzeczy do walidacji

1. **KBW z ET0 FAO-PM ani razu nie przekroczył progu przez 10 lat** dla działki z glebą kat. IV, choć bilans pokazuje niedobory w latach suchych. Porównać z tabelami SMSR (inna metoda parowania IUNG, bardzo niskie progi dla kat. IV).
2. **„≥ 10 dni z Ks < 1 w pełni wzrostu” może zawyżać** liczbę sezonów z niedoborem (Ks < 1 to już łagodny stres) – ustalić z doradcą próg i fazy krytyczne.
3. **Heurystyki do potwierdzenia**: daty siewu upraw jarych, długości faz ozimin i rzepaku (brak w FAO-56 tab. 11 dla Europy), granice TAW dla kat. I i IV, progi kształtu rowu i oczka, próg SOC, próg 1 ha dla skupionego spływu.
4. **Teren**: NMT nie zna przepustów (rowy rozpoznajemy po kształcie); dopływ z sąsiednich pól to dolna granica (bufor 50 m); na terenie płaskim kierunki spływu wyznacza mikrorzeźba.
5. **Brak spływu powierzchniowego, podsiąku, drenowania** w bilansie; pogoda z siatki ~0,1° (lokalne burze niewidoczne); Kc bez korekty klimatycznej.
6. **Overpass i SoilGrids** zwykle niedostępne na żywo → R14 „nie oceniono”, TAW tylko z IUNG (węższa informacja).
7. **Sentinel-2** tylko informacyjnie; ocena „dobrze/źle” wymaga porównania z wieloma sezonami tej samej działki.
8. **Limit Open-Meteo na IP** – bez cache ok. 35 działek dziennie z jednego adresu.
9. **Pokrycie reguł na danych rzeczywistych jest wąskie**: działka testowa (gleba ciężka, teren płaski, rów) uruchamia tylko R11, R3, R15 i nawadnianie.
   R1, R2, R6, R7, R8, R14 i R16 są sprawdzone wyłącznie testami na danych sztucznych – potrzebne działki testowe z glebą lekką, stokiem, oczkiem i ciekiem.
10. **R15 w wersji historycznej pojawia się prawie zawsze** (niedobory w pełni wzrostu w większości lat) – może to być skutek zawyżonego progu z pkt 2.

## 8. Sugestie rozwoju (zebrane w trakcie prac)

- **Dodatkowe pytania do rolnika** (zmieniają wynik): sposób uprawy (orka/uproszczona → R7), czy wiosną stoi woda na polu (zastoiska, R6), wydajność źródła wody w m³/dobę (nawadnianie), nawożenie organiczne i międzyplony (R8), kategoria gleby z mapy glebowo-rolniczej (zastąpienie IUNG). Data siewu już obsługiwana.
- **Potwierdzenia przy znacznikach** (już działa dla rowu i oczka) rozszerzyć na odpływy i zastoiska.
- **Sentinel-2 bez pobierania kafli**: Copernicus Data Space (Sentinel Hub Statistical API / openEO) – statystyki dla wielokąta w kilka kB; anomalia NDMI względem poprzednich lat; daty siewu i zbioru z przebiegu NDVI zamiast heurystyk.
- **Walidacja**: tabele SMSR IUNG, dane plonów (GUS / ARiMR), pomiary wilgotności gleby; rozszerzyć weryfikację wstecz na więcej sezonów (pełne pobranie 20 lat).
- **Model**: SCS-CN (spływ, efekt „przed/po” działań w mm), współczynnik Ky (strata plonu), SPI/SPEI, korekta Kc na klimat, fazy z sum ciepła (GDD), TWI.
- **Dane**: rowy i cieki z BDOT10k / MPHP zamiast OSM; GLO-30 jako zapas NMT; dłuższy bufor terenu w pełnym pobraniu.
- **Opis LLM** (`/api/summary`): Claude opisuje gotowy wynik prostym językiem, z kontrolą ugruntowania (te same id rad, każda liczba z wejścia, czarna lista słów) i zapasowym szablonem.
- **Interfejs**: lista rad bez szczegółów, szczegóły po rozwinięciu; legenda mapy z kształtami znaczników; źródła naukowe na dole; dostępność (kontrast AA, klawiatura, czytniki ekranu, zatrzymanie animacji).

## 9. Mapa plików

| Plik | Rola |
| --- | --- |
| `backend/app/models.py` | kontrakty JSON (Pydantic) |
| `backend/app/sources/*.py` | adaptery źródeł (ULDK, Open-Meteo, IUNG, SoilGrids, NMT, Overpass, Sentinel-2, czytnik COG) |
| `backend/app/terrain/analysis.py` | analiza NMT: priority-flood, D8, akumulacja, klasyfikacja zagłębień, odpływy |
| `backend/app/engine/kbw.py` | KBW i progi z rozporządzenia |
| `backend/app/engine/crop.py`, `balance.py` | fazy uprawy i Kc; bilans FAO-56, przebiegi TAW |
| `backend/app/engine/forecast.py` | stan w dniu D, prognoza scenariuszowa, podatność z 10 lat |
| `backend/app/engine/terrain_rules.py`, `weather_rules.py` | reguły i przyczyny |
| `backend/app/engine/assemble.py`, `plain.py` | składanie wyniku, pewność całości, język dla rolnika |
| `backend/app/data/*.yaml` | progi KBW, parametry upraw, progi terenu, teksty i progi reguł (każdy ze źródłem lub jako heurystyka) |
| `backend/app/cache.py`, `prefetch.py` | cache kontekstów i pełne pobranie działki |
| `docs/pomiary-zrodel.md`, `silnik-pogodowy.md`, `sentinel.md` | pomiary źródeł, opis silnika pogodowego, analiza Sentinela |

