# Pomiary źródeł danych (21.11.2026, ok. 18:20, sieć hackathonu)

Działka testowa `046101_1.0445.7` (Bydgoszcz), centroid ok. 18,135°E 53,105°N, EPSG:2180 (442107, 582544).
Przepustowość pobierania z tej sieci: ok. 300 kB/s (PDF 595 kB w 1,8 s).

| Źródło | Czas | Rozmiar | Wynik |
| --- | --- | --- | --- |
| ULDK `GetParcelById` | 0,14–0,3 s | 0,4 kB | ok; przy przeciążeniu odpowiada 302 na `integracja01.gugik.gov.pl/resp/uldk.php` (bez parametrów), a ten adres zwraca niekończący się strumień gzip. Adapter nie śledzi przekierowań, ma limit 1 MB i jedną powtórkę |
| Open-Meteo archive 10 lat | 0,2 s | — | **429 „Daily API request limit exceeded”** dla IP sieci hackathonu |
| Open-Meteo forecast 16 dni | 0,3 s | 1,2 kB | ok |
| NASA POWER daily 10 lat (P, Tmax, Tmin, RH, wiatr, promieniowanie) | 1,7 s | 376 kB | ok, 3911 dni do 2026-11-14, brak luk |
| IUNG WCS `Susza__katgl_landuse2024`, `format=text/plain`, 400×400 m | 0,7 s | 14 kB | ok; tekst z „Grid bounds” i siatką wartości 5 m. Pierwszy pomiar miał zamienione osie (patrz niżej); po poprawce działka testowa: **83% kat. IV, 17% kat. III** |
| SoilGrids (5 właściwości × 5 głębokości × 3 kwantyle) | 27 s | 4 kB | za wolno |
| SoilGrids (wv0033, wv1500, 2 głębokości, mean) | 2,7 s | 0,8 kB | ok, ale niestabilnie |
| NMT WCS 1.0 `image/x-aaigrid`, 300×300 m, siatka 2 m, EPSG:2180 | 10,0 s | 457 kB | działa, ale na granicy limitu 10 s |
| Overpass (overpass-api.de, kumi, private.coffee) | >40 s | — | timeout na wszystkich trzech |
| Earth Search STAC (sezon 2026, chmury < 60%) | 0,8 s | 865 kB | ok (same metadane) |

Wnioski:

- `geo.to_2180` zgadza się z ULDK `srid=2180` co do 0,01 m.
- Open-Meteo liczy zapytanie o długim okresie jako wiele wywołań (ok. 1 wywołanie na 2 tygodnie danych), więc 10 lat to ok. 280 wywołań z dziennej puli 10 000 na IP. Przy wspólnym IP wszystkich drużyn pula znika.
- Overpass jest bezużyteczny z tej sieci; cieki trzeba wziąć skądinąd albo zostawić R11/R14 jako warunkowe.
- NMT: zmniejszyć bufor (150 → 50 m) albo siatkę (2 → 5 m), żeby zmieścić się w limicie.

## Poprawki po weryfikacji (21.11, ok. 19:30)

- **IUNG, kolejność osi:** w EPSG:2180 oś `x` to northing, a `y` to easting. Zapytanie `subset=y(northing)&subset=x(easting)`
  zwracało siatkę z miejsca oddalonego o ok. 140 km, a liczba komórek przypadkiem się zgadzała. Poprawne zapytanie:
  `subset=x(northing…)&subset=y(easting…)`. Sprawdzone z obrazem WMS `Susza:katgl_landuse2024`: kształty i liczebności klas
  zgodne co do komórki. Odpowiedź tekstowa to zwykły raster (wiersz 0 = północ), `Grid bounds` = (easting, northing).
- **IUNG, legenda:** 11 lasy, 12 wody, 13 zabudowa, 14 komunikacja i nieużytki, 19/99 nieklasyfikowane, 0/255 brak danych.
  W danych występuje też kod 9 (brak w legendzie), liczony jako nieklasyfikowany.
- **NMT w EPSG:3857** (jak w prototypie) działa: 4,5–9 s dla działki z buforem 50 m przy siatce 2 m.
- **WMS w przeglądarce:** ORTO `…/PZGIK/ORTO/WMS/StandardResolution` warstwa `Raster`; cieniowanie
  `…/PZGIK/NMT/GRID1/WMS/ShadedRelief` warstwa `Raster`; KIEG `integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow`
  warstwy `dzialki`, `numery_dzialek`.
- `/api/context` dla działki testowej: 5,2 s (Open-Meteo 429, Overpass timeout, reszta ok).
