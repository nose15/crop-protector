# Sentinel-2: czy warto i ile to kosztuje (21.11.2026)

## Jak pobieramy

Earth Search STAC (`sentinel-2-c1-l2a`), pliki COG na S3. Bez rasterio: czytamy nagłówek TIFF, pobieramy zakresem
bajtów tylko kafel z działką, rozpakowujemy deflate (zlib) i odwracamy predyktor poziomy (`app/sources/cog.py`).
Działka musi leżeć w całości w scenie (kafle Sentinela się nakładają; działka testowa leży na krawędzi kafla 33UXU
i ta scena obejmowała tylko 1,7 z 2,66 ha – wybieramy scenę, której zasięg zawiera całą działkę).

## Koszt (zmierzone przez hotspot)

| Plik | Kafel (1024 × 1024 px) |
| --- | --- |
| pasmo 10 m (B04, B08) | ok. 1,1–1,2 MB |
| pasmo 20 m (B8A, B11, B05) | ok. 0,35 MB |
| maska SCL (20 m) | ok. 75 kB |

Wycinka mniejszego niż kafel nie da się pobrać (deflate obejmuje cały kafel, a działka to ok. 15 × 15 px), więc
koszt zależy wyłącznie od liczby kafli. Podgląd zmniejszonych wersji (overviews) nie pomaga: kafel ma tyle samo pikseli.

| Tryb | Co | Ok. MB na działkę |
| --- | --- | --- |
| pierwsza wersja | 6 scen NDMI + NDVI 10 m | 7 |
| **lekki (teraz w /api/context)** | maski 8 scen + NDMI dla 3 czystych | **2** |
| pełny (`python -m app.prefetch`, do cache) | maski 40 scen + NDMI i NDRE dla 20 + NDVI | 15–25, jednorazowo |

## Co daje (działka testowa)

- Sezon 2026: NDMI (woda w roślinach) rośnie od 0,19 (14.08) do 0,38 (28.09), NDVI 0,85 (28.09) – pole warzyw.
- Sezon 2025: goła gleba w kwietniu–maju (NDMI ok. −0,15), wzrost od czerwca (NDMI 0,10, NDVI 0,40 w połowie czerwca).
- Połowa scen z zachmurzeniem < 40% ma działkę zasłoniętą – maska SCL jest niezbędna.

## Wnioski

1. **Przydatne jako potwierdzenie z pola**: czy rośliny faktycznie tracą wodę (spadek NDMI), czy pole jest obsiane,
   kiedy był siew i zbiór. To może zastąpić nasze heurystyczne daty siewu i zweryfikować bilans FAO-56.
2. **Nie nadaje się do oceny „dobrze/źle” bez punktu odniesienia**: progi NDMI zależą od uprawy i fazy. Sensowna ocena
   to anomalia względem tej samej działki w poprzednich latach – wymaga ok. 9 sezonów, czyli pełnego pobrania do cache
   (w trybie na żywo się nie mieści).
3. **W trybie na żywo** zostawiamy lekki wariant (ok. 2 MB, tylko informacja w panelu, bez wpływu na rekomendacje).
4. **Docelowo bez pobierania kafli**: Copernicus Data Space (Sentinel Hub Statistical API / openEO) liczy statystyki
   wskaźnika dla wielokąta po stronie serwera i zwraca kilka kB JSON. Wymaga darmowego konta i klucza w backendzie.
