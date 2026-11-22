# Silnik pogodowy (stan na 21.11.2026)

Kod: `backend/app/engine/` (`weather.py`, `kbw.py`, `crop.py`, `balance.py`, `forecast.py`, `weather_rules.py`, `assemble.py`).
Stałe: `backend/app/data/kbw_thresholds.yaml`, `crops.yaml`, `rules.yaml` (każda wartość ze źródłem albo jako heurystyka).

## Dane wejściowe

- Pogoda dobowa z Open-Meteo (archiwum ERA5 + prognoza 16 dni): opad P, ET0 FAO Penman-Monteith, Tmax, Tmin,
  od 1 marca sprzed 10 lat do dnia analizy D. Pobierana przy każdym `/api/context` (bez cache, zgodnie z CLAUDE.md).
- Historię ucinamy na dniu D: ocena jest taka, jaką dałoby się zrobić w dniu D.
- Gdy D wymaga innych 10 lat, `/api/recommend` zwraca 409 `meteo_range`, a frontend pobiera kontekst dla D.

## KBW (Dz.U. 2019 poz. 739)

KBW = ΣP − ΣET0 w każdym z 14 okresów 60-dniowych (21 III–20 V … 1 VIII–30 IX). Próg działki to średnia progów
kategorii I–IV ważona udziałem kategorii IUNG. Status: `zagrozenie`, `na_granicy` (|margines| < 15 mm),
`brak_zagrozenia`, `poza_okresem` (D poza 21 III–30 IX: pokazujemy ostatni okres sezonu), `brak_progu`
(„x” w tabeli), `brak_danych`. Zawsze z dopiskiem: przybliżenie SMSR (ET0 FAO-PM zamiast parowania IUNG).

## Bilans wody FAO-56

Dr = clip(Dr − P + Ks·Kc·ET0, 0, TAW); RAW = p·TAW (p korygowane o ETc); Ks < 1 gdy Dr > RAW. Start 1 marca, Dr = 0.
Kc(t): krzywa 4-fazowa FAO-56 (tab. 11, 12). Start sezonu: uprawy jare – typowa data siewu albo podana przez rolnika;
oziminy, rzepak, użytki zielone – początek wegetacji (5-dniowa średnia temperatury ≥ 5°C).
TAW jako przedział: dolna i górna granica kategorii IUNG (ważone udziałem) oraz SoilGrids (FC − WP) × Zr min/max
z FAO-56 tab. 22 → do 6 przebiegów; wynik jako mediana i zakres.

## Prognoza na zakres dat

Od stanu w dniu D do `range.to`: pierwsze ≤ 15–16 dni z prognozy pogody (gdy D = dzień pobrania), dalej 10 scenariuszy:
pogoda z tych samych dni kalendarzowych w 10 poprzednich latach. Liczymy tylko dni w sezonie wzrostu uprawy.
Wynik: szansa stresu „n z 10” (środkowy przebieg TAW), dni do przekroczenia RAW (przedział), niedobór
Σ(ETc − ETc,adj) w mm i m³ na działkę (przedział z przebiegów TAW).

## Podatność z 10 lat

10 ostatnich pełnych sezonów przed D: w ilu KBW spadł poniżej progu, w ilu było ≥ 10 dni stresu (Ks < 1) w fazie
pełni wzrostu, typowe miesiące ryzyka (≥ 5 dni stresu w miesiącu w ≥ 3 sezonach).

## Przyczyny i reguły

C1 (opad/upał): KBW poniżej progu w okresie odniesienia albo w ≥ 3 z 10 sezonów. C4 (okno uprawy): ≥ 5 z 10 sezonów
ze stresem w pełni wzrostu (pewność niska). R15: szansa stresu ≥ 5 z 10 w zakresie dat albo C4. R7/R8: gleby lekkie
(I–II ≥ 50%), R8 dodatkowo mało węgla organicznego. R16: C1 dominująca, C2 i C3 nie. Nawadnianie: zapas poniżej RAW
w dniu D albo szansa stresu ≥ 5 z 10, woda nie wykluczona; zawsze ostatnie, z dopiskiem o zgodzie wodnoprawnej.

## Do walidacji (pytania do mentora)

- KBW z ET0 FAO-PM nie przekroczył progu ani razu w 10 latach dla działki z glebą kat. IV (Bydgoszcz), choć bilans
  pokazuje niedobory w latach suchych (2018, 2019, 2022, 2023). Porównać z tabelami SMSR.
- Próg „≥ 10 dni z Ks < 1 w pełni wzrostu” może zawyżać liczbę sezonów z niedoborem (Ks < 1 to już łagodny stres).
- Daty siewu, długości faz dla ozimin i rzepaku, granice TAW dla kat. I i IV są heurystykami (crops.yaml).
