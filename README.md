# Zatrzymaj wodę, chroń plony

Prototyp aplikacji webowej dla rolnika: z numeru działki ewidencyjnej albo punktu na mapie powstaje ocena sytuacji wodnej, przyczyny niedoboru i konkretne działania. Kolejność jest stała: **retencja → agrotechnika → nawadnianie**.

Zadanie HackNation 2026 (KOWR): *Zatrzymaj wodę, chroń plony – Inteligentne wsparcie gospodarowania wodą w rolnictwie*. Dokumentacja poniżej odpowiada wymaganiom z opisu zadania (rozdział 4.2) oraz zasadom z „Podstaw naukowych”: integracja danych, przyczyny, niepewność, uzasadnienie i ta sama sekwencja decyzji.

Szczegóły metod, reguł i ewaluacji są w [`docs/`](docs/). Ten plik opisuje tylko to, co jest w repozytorium.

## Problem, funkcje, dane, korzyść

Polska ma niskie zasoby wody i niską retencję. Otwarte dane o pogodzie, glebie, terenie i satelicie istnieją, ale są rozproszone i nieczytelne bez GIS. Sam komunikat „jest susza” nie wystarcza: susza wraca co roku, a decyzja dotyczy konkretnej działki, uprawy i terminu.

Aplikacja:

1. znajduje działkę (numer TERYT, adres albo kliknięcie na mapie);
2. zbiera pogodę z 10 lat, glebę, teren, cieki i wskaźnik satelitarny;
3. liczy stan wody i podatność wieloletnią dla wybranej uprawy i zakresu dat;
4. podaje przyczyny i działania z dowodem z tej działki, pewnością i ograniczeniami;
5. pozwala pobrać raport jako plik PDF albo go wydrukować.

Korzyść dla rolnika: jedna odpowiedź w języku gospodarstwa (ile wody, dlaczego, co zrobić i kiedy), bez obsługi usług WCS, STAC i bilansu wodnego. Inwestycje (zastawka, oczko, nawadnianie) zawsze z dopiskiem o konsultacji z ODR, spółką wodną albo Wodami Polskimi.

## 1. Instrukcja uruchomienia

Potrzebne: Python 3.11+ i Node.js 22. Działa w przeglądarce (Chrome, Firefox, Edge, Safari, Opera) na Windows i Linuksie. Rolnik niczego nie instaluje; poniższe kroki są dla jury i osób uruchamiających prototyp.

Dwa terminale, z katalogu głównego repozytorium:

```bash
# backend — http://127.0.0.1:8000
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

```bash
# frontend — http://localhost:5173  (zapytania /api idą na port 8000)
cd frontend
npm install
npm run dev
```

Sprawdzenie: `cd backend && pytest` oraz `cd frontend && npm run build`.

W przeglądarce: wpisać numer, na przykład `046101_1.0445.7`, albo kliknąć działkę na mapie, wybrać uprawę i zakres dat, potem **Sprawdź działkę**. Działka przykładowa jest w zapisie startowym (`backend/app/data/seed_cache/`), więc wynik pojawia się od razu, bez zapytań do usług. Inna działka z terenu Polski jest liczona na żywo: zwykle 5–20 s na zebranie danych, potem poniżej sekundy na rekomendacje. Raport: przycisk **Pobierz PDF** (plik składa backend z tego samego wyniku, który widać na ekranie) albo **Drukuj**. Pierwsza strona PDF to proste dane i opisy, bez wykresów: werdykt, trzy liczby, „Co się dzieje”, „Dlaczego” i „Co zrobić” (kiedy i jak). Kolejne strony to szczegóły z wykresami (woda w glebie, brak wody w 10 latach, bilans opadu i parowania w sezonie), rozwinięcie problemów, pełny opis działań, odpowiedzi i ograniczenia.

Inny port backendu: `BACKEND_PORT=8001 npm run dev` przy `uvicorn … --port 8001`.

Wdrożenie opisuje [`render.yaml`](render.yaml): usługa Python (Frankfurt, `uvicorn`) i statyczny build Vite. Adres API trafia do frontendu jako `VITE_API_URL`. Gdy obok backendu leży zbudowany `frontend/dist`, jedna usługa serwuje też stronę. Dysk na Render jest ulotny; zapis startowy w repozytorium zostaje.

Pełne pobranie jednej działki (dłuższe limity, 20 lat pogody, więcej scen satelitarnych, a przy koncie CDSE także baza satelitarna z lat ubiegłych przez openEO – kilka minut):

```bash
cd backend && python -m app.prefetch 046101_1.0445.7
```

## 2. Podstawowe funkcjonalności

Jeden ekran: mapa na całą szerokość, pasek wyszukiwania, panel wyniku.

| Krok rolnika | Co dostaje |
| --- | --- |
| Numer działki, adres albo kliknięcie | geometria, gmina, powierzchnia |
| Uprawa i zakres dat (od dziś albo data z ostatnich 10 lat, do 2 lat do przodu) | ocena na ten okres, nie na „zawsze” |
| Trzy odpowiedzi: źródło wody, drenowanie, zastawka — tak / nie / nie wiem | brak odpowiedzi daje radę warunkową („jeśli…”), analiza i tak powstaje |
| Potwierdzenie znacznika na mapie (rów, oczko) | wyższa pewność tej rady |

Uprawy: zboża ozime, zboża jare, kukurydza na ziarno, kukurydza na kiszonkę, rzepak, ziemniaki, burak cukrowy, użytki zielone.

Raport zawiera:

- stan wody w wybranym okresie i zdanie, czy jej zabraknie;
- rozróżnienie bieżącej sytuacji i wieloletniej podatności (w ilu z 10 sezonów brakowało wody, w których miesiącach);
- przyczyny niedoboru, od najważniejszej;
- działania w grupach retencja, agrotechnika, nawadnianie (zawsze na końcu), z terminem, dowodem z działki i pewnością;
- datę analizy, źródła (status, data danych, licencja) i ograniczenia;
- brak danych jako „nie oceniono”, bez cichej wartości domyślnej.

Poza sezonem wzrostu (ocena jury wypada w listopadzie, a monitoring KBW obejmuje 21 III–30 IX) aplikacja mówi o tym wprost i pokazuje, co widać po wydłużeniu zakresu do wiosny.

Na mapie: ortofotomapa i granice działek, cieniowanie terenu, granica działki, miejsca spływu, rowy i zagłębienia oraz wykres zapasu wody w wybranym okresie. Rozmiar tekstu i wysoki kontrast są w pasku i zostają w przeglądarce.

## 3. Architektura

Aplikacja jest bezstanowa poza plikowym cache kontekstów. Nie ma bazy danych, kolejek ani konta użytkownika. Wynik liczy kod; model językowy nie jest podłączony.

```
przeglądarka (React, Vite)
    GET  /api/parcel?q=… | ?lat=&lon= | ?address=…
    POST /api/context     { parcel, as_of? }
    POST /api/recommend   { context | context_ref, request }
    GET  /api/cache, /api/cache/{numer}
        │
        ▼
FastAPI
    sources/     adapter na usługę; błąd zamienia się w status, nie w wyjątek
    terrain/     NMT: wypełnienie zagłębień, spływ, klasyfikacja form
    engine/      KBW, fazy uprawy, bilans FAO-56, prognoza, przyczyny, reguły
    data/*.yaml  progi i teksty, każdy ze źródłem albo oznaczeniem „heurystyka”
    cache        jeden plik .json.gz na działkę
```

| Endpoint | Wejście | Wyjście | Czas |
| --- | --- | --- | --- |
| `GET /api/parcel` | numer, punkt albo adres | działka (WGS84, centroid, pole, TERYT) | 0,2–0,6 s |
| `POST /api/context` | działka, opcjonalnie dzień D | pogoda, gleba, teren, cieki, satelita, `provenance[]` | 5–20 s na żywo; z cache ok. 20 ms |
| `POST /api/recommend` | kontekst i prośba (uprawa, daty, odpowiedzi) | ocena, przyczyny, działania | zwykle poniżej 1 s |
| `POST /api/report.pdf` | gotowy wynik z `/api/recommend` i opcjonalnie działka (gmina, obręb) | plik PDF do pobrania (`raport-<numer>-<data>.pdf`) | ok. 0,4 s |
| `GET /api/health` | — | `{"status":"ok"}` | — |
| `GET /api/status` | — | czy serwer działa, główne źródło pogody, czy jest konto CDSE, ile zadań openEO trwa; frontend odpytuje co 30 s i pokazuje „Serwer działa / nie odpowiada” w pasku | natychmiast (bez zapytań do usług) |
| `GET /api/baseline/{numer}` | — | stan bazy satelitarnej działki: `gotowe`, `liczenie`, `blad`, `brak`, `nieskonfigurowane`; frontend odpytuje co 15 s, gdy porównanie jest w przygotowaniu, i sam przelicza wynik | natychmiast |

`/api/context` woła źródła równolegle i urywa całość po 28 s. Każde źródło ma własny, krótszy limit. Awaria jednego nie blokuje reszty: w raporcie widać status (`ok`, `partial`, `timeout`, `error`, `empty`). Trafienie w cache nie wykonuje zapytań. Przy `?refresh=true` źródło, które teraz zawiedzie, może wrócić z poprzedniego zapisu (`provenance.mode = "cache"`).

Błędy: 404 `parcel_not_found`, 502 `uldk_unavailable`, 422 `invalid_request`, 409 `meteo_missing` (bez pogody nie ma oceny), 409 `meteo_range` (kontekst nie obejmuje 10 lat przed wybraną datą; interfejs pobiera go ponownie).

Silnik, w skrócie:

1. klimatyczny bilans wodny (KBW) w 14 okresach sezonu, progi z rozporządzenia ważone udziałem kategorii gleby IUNG;
2. fazy uprawy i współczynnik Kc (FAO-56);
3. bilans wody w strefie korzeniowej; zapas jako przedział (kategoria IUNG i, gdy jest, SoilGrids);
4. od dnia analizy do końca zakresu: do 16 dni z prognozy, dalej 10 scenariuszy z tych samych dni w poprzednich latach; częstość jako „n z 10”;
5. podatność z 10 sezonów i przyczyny (opad i temperatura, gleba, spływ, okno uprawy);
6. reguły z `backend/app/data/rules.yaml`. Reguła działa tylko na policzonym wskaźniku. Nawadnianie jest ostatnie.

Pełny opis reguł, progów i przepływu: [`docs/analiza-silnika.md`](docs/analiza-silnika.md). Silnik pogodowy: [`docs/silnik-pogodowy.md`](docs/silnik-pogodowy.md).

### Pewność wyniku (od 22.11.2026)

Pewność całości to **najniższa** z pewności: danych pogodowych, zapasu wody w glebie (zgodność map IUNG i SoilGrids), głównych przyczyn i trzech pierwszych rad. Awaria źródła obniża tylko to, co z niego liczymy: brak mapy cieków daje „nie oceniono” dwóm radom o ciekach, a nie „niską” pewność całego raportu (wcześniej dowolne dwie awarie dawały „niską”, a „wysoka” była niemożliwa).

Zdjęcia satelitarne z lat ubiegłych (openEO) działają jako niezależne potwierdzenie z pola: gdy przeczą bilansowi wody, pewność spada o stopień i raport radzi obejrzeć pole; gdy go potwierdzają (baza ≥ 5 lat) i rolnik odpowiedział, czy działka ma dreny albo rów z zastawką, pewność może wzrosnąć do „wysokiej”. Powody (najwyżej 4) są w wyniku i w raporcie.

Porównanie dla nowej działki liczy się w tle 3–4 minuty (zmierzone 22.11.2026: 217 s dla 9 sezonów). Zadanie startuje już przy pobieraniu danych działki (`/api/context`), a gdy pierwszy wynik ma porównanie „w przygotowaniu”, frontend sam go przelicza, kiedy baza jest gotowa – rolnik nic nie klika. Działka przykładowa ma bazę w zapisie startowym (`backend/app/data/seed_cache/s2base_046101_1.0445.7.json.gz`), więc pokaz działa od razu.

Konto CDSE dla openEO: zmienne `CDSE_CLIENT_ID` i `CDSE_CLIENT_SECRET` (serwer) albo `CDSE_REFRESH_TOKEN`; lokalnie wystarcza jednorazowe logowanie klientem `openeo` (token w profilu użytkownika). Bez konta aplikacja działa, tylko bez porównania satelitarnego. `KOWR_OPENEO_DISABLED=1` wyłącza openEO (testy). Graf procesów: `backend/app/data/openeo_s2_graph.json`, wygenerowany offline narzędziem `backend/tools/gen_openeo_graph.py` – backend nie importuje pakietu `openeo`.

## 4. Źródła i zakresy danych

Wszystkie źródła są bezpłatne. KOWR nie dostarczał paczki danych; pobranie jest w adapterach.

| Źródło | Zakres | Do czego |
| --- | --- | --- |
| ULDK GUGiK | geometria działki z numeru lub punktu, cała Polska | granica, pole, TERYT |
| Usługa geokodowania GUGiK (UUG) | adres → punkt, tylko dopasowania o dokładności ≥ 0,9 | wyszukiwanie „miejscowość, ulica numer” |
| **NASA POWER** (daily point, społeczność AG) – źródło główne historii od 22.11.2026 | opad, Tmax, Tmin, wiatr, punkt rosy, promieniowanie; ET0 FAO-56 Penman–Monteith liczone w aplikacji (`engine/et0.py`); od 1 marca sprzed 10 lat (pełne pobranie: 20 lat), siatka ~50 km, opóźnienie ok. 3 dni | KBW, bilans, scenariusze |
| Open-Meteo, archiwum ERA5 / ERA5-Land i prognoza | zapas historii (gdy POWER zawiedzie) oraz ostatnie dni i 16 dni prognozy; przełącznik `KOWR_METEO_PRIMARY=open_meteo` odwraca kolejność | prognoza; zapas |
| IUNG-PIB, WCS `Susza__katgl_landuse2024` | kategorie podatności gleb I–IV, siatka 5 m, stan użytkowania 2024 | próg KBW i przedział pojemności wodnej |
| ISRIC SoilGrids 2.0 | pojemność polowa, punkt więdnięcia, piasek, ił, węgiel organiczny; 250 m | drugi przebieg pojemności; przy braku danych zostaje sam IUNG |
| NMT GUGiK, WCS | model terenu 1 m, próbkowany co 2 m, działka i bufor 50 m | zagłębienia, rowy, odpływy, nachylenie |
| OpenStreetMap przez Overpass | rowy i cieki w promieniu 500 m | pas zieleni przy cieku; timeout = „nie oceniono” |
| Sentinel-2 L2A, Earth Search STAC | NDMI z 3 czystych scen sezonu (pasma 20 m, maska chmur SCL) | informacja o wodzie w roślinach w panelu |
| **Sentinel-2 L2A przez openEO (CDSE)**, zadanie wsadowe w tle | NDVI, NDMI i udział ważnych pikseli działki od 1.03.2018 do dziś (maska SCL, mediana w obrysie −10 m); jedno zadanie na działkę, kilka minut, zapis w cache | porównanie z tymi samymi dekadami w latach ubiegłych (odporny z-score); potwierdza albo podważa bilans wody i zmienia pewność |
| Dz.U. 2019 poz. 739 | progi KBW: uprawa × kategoria gleby × okres | stała w `kbw_thresholds.yaml` |
| Geoportal WMS i kafelki OSM | ortofotomapa, granice działek (KIEG), cieniowanie, mapa podkładowa | tylko obraz w przeglądarce |

Parametry upraw (Kc, głębokość korzeni, daty) i progi terenu są w `backend/app/data/crops.yaml` i `terrain.yaml`. Przy każdej wartości jest źródło (FAO-56, rozporządzenie, literatura) albo jawna heurystyka.

Pomiary czasów i problemy usług z 21.11.2026: [`docs/pomiary-zrodel.md`](docs/pomiary-zrodel.md). Koszt i rola Sentinela: [`docs/sentinel.md`](docs/sentinel.md).

## 5. Co jest pobierane na bieżąco, a co było pobrane wcześniej

Wynik i rekomendacje liczy aplikacja w chwili żądania, na danych z kontekstu. Nie ma katalogu gotowych porad.

**Na bieżąco**, przy każdej nowej działce albo odświeżeniu:

- geometria (ULDK) i ewentualnie adres (UUG);
- pogoda, IUNG, SoilGrids, NMT, cieki i lekki NDMI — równolegle, z limitami czasu;
- w raporcie pole `provenance`: status, tryb (`live` albo `cache`), czas pobrania, data ważności danych, licencja.

NASA POWER ma około 3 dni opóźnienia; ostatnie dni i prognozę 16 dni dokłada Open-Meteo. Gdy Open-Meteo nie odpowie (np. dzienny limit, HTTP 429), ocena i tak powstaje: stan wody liczymy na ostatni dzień z danymi (najwyżej 7 dni przed dniem analizy), a dalej działają scenariusze z poprzednich lat; raport mówi to wprost. Historia do rekomendacji jest ucinana na dniu analizy, więc ocena daty historycznej widzi tylko to, co było znane tego dnia.

**Wcześniej, w repozytorium (nie liczą się same z siebie jako wynik):**

| Zbiór | Kiedy | Co zawiera |
| --- | --- | --- |
| `backend/app/data/seed_cache/046101_1.0445.7.json.gz` | pobranie 21.11.2026, 19:18 UTC | działka w Bydgoszczy, 2,66 ha. Pogoda 1.03.2016–21.11.2026 (archiwum ważne do 16.11.2026). IUNG i NMT pobrane tego dnia. Sentinel: ostatnia czysta scena 28.09.2026. SoilGrids i Overpass w tym zapisie: timeout |
| `kbw_thresholds.yaml`, `crops.yaml`, `rules.yaml`, `terrain.yaml` | stałe w kodzie | progi rozporządzenia, parametry FAO-56 i heurystyki; nie są dociągane z sieci przy analizie |
| `backend/tests/fixtures/` | zapisane odpowiedzi do testów | testy nie wołają usług zewnętrznych |

Własny cache (`backend/cache/`, poza gitem, albo `KOWR_CACHE_DIR`) ma pierwszeństwo przed zapisem startowym. Zapis powstaje, gdy pobranie na dziś ma pogodę.

Gdy zapis nie ma map (teren NMT, rowy i cieki, SoilGrids), bo usługa chwilowo nie odpowiadała, kolejne otwarcie działki po co najmniej 30 minutach ponawia tylko te źródła (z limitem 40 s; pogoda i reszta zostają z zapisu) i dopisuje je do zapisu. Bez tego działka zapisana podczas awarii GUGiK nigdy nie dostawała warstw spływu, zagłębień i spadków. Zapytanie o NMT ma jedną powtórkę przy zerwanym połączeniu (22.11.2026 WCS GUGiK na przemian odpowiadał w ok. 4 s i zrywał połączenia).

## 6. Biblioteki, komponenty, modele i usługi

### Backend (`backend/requirements.txt`)

| Pakiet | Rola | Licencja |
| --- | --- | --- |
| FastAPI, Uvicorn | HTTP API | MIT, BSD-3-Clause |
| Pydantic (zależność FastAPI) | kontrakty JSON | MIT |
| httpx | wywołania usług | BSD-3-Clause |
| NumPy | rastry NMT i Sentinela, bez GDAL i rasterio | BSD-3-Clause |
| PyYAML | progi i reguły | MIT |
| fpdf2 (z zależnościami Pillow i fontTools) | raport PDF (`app/report_pdf.py`) | LGPL-3.0 (Pillow: MIT-CMU, fontTools: MIT) |
| pytest | testy | MIT |
| anthropic | zadeklarowany, **nieużywany** | MIT |

Katalog `backend/app/llm/` jest pusty. Trasa `/api/summary` jest opisana w kontrakcie jako jeszcze niewystawiona. Aplikacja nie wywołuje Claude, Bielika ani innego modelu. Koszt modeli językowych: 0 zł. Klucz API nie jest potrzebny.

### Frontend (`frontend/package.json`)

| Pakiet | Rola | Licencja |
| --- | --- | --- |
| React, React DOM | interfejs | MIT |
| Vite, `@vitejs/plugin-react` | budowanie i serwer deweloperski | MIT |
| Leaflet | mapa | BSD-2-Clause |
| react-leaflet, `@react-leaflet/core` | mapa w React | Hippocratic-2.1 |
| Chart.js, react-chartjs-2 | wykres zapasu wody | MIT |
| `@fontsource-variable/atkinson-hyperlegible-next` | krój czytelny w gospodarstwie | OFL-1.1 |

Pełna lista zależności przechodnich jest w `frontend/package-lock.json`.

**Sztuczna inteligencja.** Prototyp jej nie używa. Ocena, przyczyny i teksty rad pochodzą z reguł i wzorów (FAO-56, KBW, analiza terenu). Pakiet `anthropic` został zostawiony pod ewentualny opis gotowego wyniku; bez klucza i bez wywołania nie bierze udziału w działaniu.

**Usługi zewnętrzne:** ULDK, UUG, NASA POWER, Open-Meteo, openEO CDSE (konto CDSE, opcjonalnie), WCS IUNG, SoilGrids, WCS i WMS Geoportalu, Overpass, Earth Search (Element 84, obiekty COG Sentinela na S3), kafelki OSM. Wszystkie w darmowych warunkach publicznych, bez konta i bez klucza.

## 7. Licencje danych i warunki użycia

| Dane | Warunki |
| --- | --- |
| NASA POWER | dane publiczne NASA, bez opłat, z podaniem źródła |
| Open-Meteo (ERA5, ERA5-Land, prognoza) | [CC BY 4.0](https://open-meteo.com/en/terms). W raporcie jest atrybucja |
| SoilGrids 2.0 | CC BY 4.0, ISRIC |
| Sentinel-2 | Copernicus Sentinel data, bezpłatnie; aplikacja liczy wskaźnik (dane zmodyfikowane) |
| OpenStreetMap (cieki i kafelki mapy) | ODbL, © współtwórcy OpenStreetMap |
| ULDK, NMT, ortofotomapa, KIEG, cieniowanie, UUG | GUGiK, dane bezpłatne na warunkach serwisów Geoportalu |
| IUNG-PIB, kategorie gleb SMSR | brak jawnej licencji na usłudze WCS; użycie informacyjne, z oznaczeniem źródła w raporcie |
| Progi KBW | akt prawny, domena publiczna (Dz.U. 2019 poz. 739) |
| Leaflet | BSD-2-Clause |
| react-leaflet | Hippocratic License 2.1 — licencja z klauzulą etyczną, inna niż MIT/BSD. Dotyczy biblioteki mapy, nie danych KOWR. Przed ewentualnym wdrożeniem produkcyjnym warto ją osobno przejrzeć |
| Krój Atkinson Hyperlegible Next | SIL Open Font License 1.1; plik TTF z tekstem licencji w `backend/app/data/fonts/`, osadzany (podzbiór znaków) w raporcie PDF |

Kod prototypu powstał w trakcie wydarzenia. Przeniesienie praw do rozwiązania zwycięskiego reguluje regulamin zadania (§ 5), nie ten plik.

## 8. Ograniczenia

- **Jedna działka na raz**, w przeglądarce. Brak konta gospodarstwa i brak listy wielu pól w jednym raporcie.
- **KBW jest przybliżeniem SMSR.** Liczymy ET0 metodą FAO Penman–Monteith, a IUNG używa własnego parowania. Dla gleby kategorii IV na działce testowej próg KBW nie został przekroczony w 10 latach, choć bilans FAO-56 pokazuje niedobory w suchych latach (2018, 2019, 2022, 2023). Porównanie z tabelami SMSR jest otwarte.
- **Część progów to heurystyki** (daty siewu, długości faz ozimin i rzepaku, granice pojemności dla skrajnych kategorii, kształt rowu i oczka). Są opisane w YAML-u. Rolnik może podać datę siewu.
- **Bilans nie obejmuje** spływu powierzchniowego, podsiąku i drenów. Pogoda jest z siatki około 0,1°, więc lokalna burza może być niewidoczna.
- **NMT nie zna przepustów.** Rów przy drodze bywa zamkniętą niecką; klasyfikacja po kształcie to poprawia, ale wymaga potwierdzenia na mapie. Na terenie płaskim kierunek spływu wyznacza mikrorzeźba.
- **SoilGrids i Overpass często nie zdążą** (timeout). Wtedy pojemność wody pochodzi tylko z kategorii IUNG, a rada o pasie przy cieku dostaje status „nie oceniono”.
- **Sentinel w trybie na żywo jest informacją**, nie werdyktem. O pewności decyduje dopiero porównanie z latami ubiegłymi z openEO, a ono wymaga konta CDSE i liczy się w tle (pierwszy raport nowej działki jest bez niego, kolejny już z nim). Płodozmian w latach bazowych daje flagę „baza mieszana” zamiast wniosku o suszy.
- **Pogoda z NASA POWER ma siatkę ok. 50 km** (Open-Meteo ok. 10 km), więc lokalne burze są jeszcze mniej widoczne. Wybraliśmy ją, bo Open-Meteo ma dzienny limit na adres IP (HTTP 429 z sieci hackathonu i z tej maszyny 22.11.2026) i wtedy nowa działka nie dostawała żadnej oceny.
- **Czas.** Rekomendacja po zebraniu danych jest poniżej sekundy. Zebranie nowej działki zwykle mieści się w 30 s, ale wolny NMT albo SoilGrids mogą dobić do bezpiecznika 28 s i wrócić z częściowym kontekstem (`partial: true`).
- **Reguły sprawdzone na prawdziwej działce testowej** to głównie zastawka na rowie, pas trawy przy odpływie, oszczędzanie wody przed suchym okresem i nawadnianie. Pozostałe reguły (stok, gleba lekka, oczko, ciek) mają testy na danych sztucznych i czekają na kolejne działki.
- **Brak opisu z modelu językowego.** Teksty rad są z szablonów reguł, wypełnionych liczbami z silnika.

## 9. Weryfikacja wyników

Liczby nie pochodzą z modelu językowego. Sprawdzenie jest trojakie.

**Testy automatyczne** (`cd backend && pytest`), bez sieci i bez zapisu do `backend/cache/`:

- przeliczenie współrzędnych zgodne z ULDK co do 0,01 m; parser ULDK i IUNG; odrzucenie siatki IUNG z zamienionymi osiami;
- teren: płaszczyzna, misa o znanej objętości, rozróżnienie rowu, oczka i zastoiska, regresja na prawdziwym NMT działki testowej;
- KBW: sumy okresu, próg ważony, listopad → `poza_okresem`;
- bilans FAO-56 zgodny ze wzorami, na stałych danych i na zapisie pogodowym;
- niezmienniki rad: każda ma dowód, pewność i tytuł; inwestycje mają dopisek o konsultacji; grupy idą w kolejności retencja → agrotechnika → nawadnianie;
- API: złe daty i uprawa (422), brak pogody i zły zakres (409), trafienie w cache bez zapytań.

**Porównanie z niezależnym obrazem.** Kolejność osi IUNG w EPSG:2180 sprawdzono z usługą WMS tej samej warstwy (zgodność liczebności klas co do komórki). Klasyfikację rowów na działce `046101_1.0445.7` porównano z ortofotomapą: obniżenia przy drogach, wcześniej brane za oczka, pokrywają się z rowami.

**Prognoza wstecz, sezon 2026, ta sama działka.** Dla 6 upraw i trzech dni startu silnik widział pogodę tylko do dnia D, a „fakt” policzono tym samym bilansem na pogodzie, która naprawdę nadeszła. Brier score częstości niedoboru: 0,053 (18 przypadków) wobec 0,099 dla prognozy stałą częstością. Niedobór w milimetrach jest zwykle tego samego rzędu i raczej zawyżony (mediana różnicy +6 mm). To sprawdza scenariusze pogodowe, nie wilgotność zmierzoną na polu. Jedna wyraźna pomyłka: burak cukrowy od 1 maja (prognoza 6 z 10, faktycznie bez niedoboru). Tabela i zastrzeżenia: [`docs/analiza-silnika.md`](docs/analiza-silnika.md), rozdział 6.

Jury może powtórzyć ocenę dla dowolnej działki z numeru i dowolnej daty z ostatnich 10 lat. Dla działki przykładowej wystarczy zapis z 21.11.2026. W panelu „Źródła danych” widać, które warstwy są z tego dnia, a które z nowego pobrania.

## Skalowanie na wielu rolników

Prototyp nie zakłada równoczesnego ruchu z całego kraju. Działa dla dowolnej działki ewidencyjnej w Polsce, pojedynczo.

Żeby służyć wielu gospodarstwom:

- **wspólny cache działek** (dziś plik na dysku) ogranicza powtórne pobrania; bez niego jedno IP mieści rząd 30 pełnych historii Open-Meteo na dobę;
- **trwały dysk i kolejka pobrań**, z limitem równoległych wywołań do GUGiK, IUNG i Open-Meteo; odpowiedź z cache zostaje natychmiastowa, a pierwsza wizyta na działce może trwać te same 5–20 s;
- **aktualizacja:** kategorie gleb i NMT zmieniają się rzadko (wystarczy ważność w `provenance`); pogodę warto odświeżać codziennie dla działek oglądanych w ostatnich dniach, nie dla całej ewidencji;
- **tańsze satelitarne statystyki** (Copernicus Data Space, zapytanie o wielokąt zamiast kafla) przy wielu sezonach NDMI;
- **koszt infrastruktury:** dziś 0 zł za dane i modele. Hosting klasy bezpłatnego Render wystarcza do prezentacji. Ruch ogólnokrajowy to zwykły serwer aplikacyjny, dysk na cache i ewentualnie płatny pakiet pogody, jeśli darmowy limit IP przestanie wystarczać. Samo liczenie rekomendacji jest tanie (CPU, poniżej sekundy na działkę).

## Bezpieczeństwo

Prototyp nie zakłada konta i nie prosi o dane osobowe. Numer działki jest identyfikatorem ewidencyjnym, nie danymi osoby. W przeglądarce zostają tylko preferencje tekstu i kontrastu (`localStorage`). API nie używa ciasteczek; CORS dopuszcza dowolną domenę, bo nie ma sesji ani zapisu po stronie użytkownika. Sekrety nie leżą w repozytorium (`.env` jest w `.gitignore`). Wywołania zewnętrzne mają limit czasu i rozmiaru odpowiedzi; ULDK nie śledzi przekierowań, które przy przeciążeniu prowadzą w nieskończony strumień.

## Dalsza lektura

| Dokument | Treść |
| --- | --- |
| [`docs/analiza-silnika.md`](docs/analiza-silnika.md) | przepływ, reguły, składanie wyniku, ewaluacja, mapa plików |
| [`docs/silnik-pogodowy.md`](docs/silnik-pogodowy.md) | KBW, bilans FAO-56, prognoza, podatność 10 lat |
| [`docs/pomiary-zrodel.md`](docs/pomiary-zrodel.md) | czasy i awarie usług, 21.11.2026 |
| [`docs/sentinel.md`](docs/sentinel.md) | ile waży Sentinel-2 i czego z niego nie wnioskujemy |
| [`docs/alternatywy-zrodel.md`](docs/alternatywy-zrodel.md) | zamienniki zawodnych usług (pogoda, gleba, NMT, cieki, satelita), stan na 22.11.2026 |
