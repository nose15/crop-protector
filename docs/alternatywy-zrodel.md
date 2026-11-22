# Alternatywy dla zawodnych źródeł backendu

Stan na 22.11.2026. Backend (`hacknation/backend`) bierze dane działki z usług na żywo. Poniżej jest pełna lista tych usług, ocena, które są zawodne, i po kilka zamienników dla każdej zawodnej. Przy wyborze liczyły się dwie rzeczy: czy źródło wytrzyma wiele działek z jednego adresu IP (hackathon, a docelowo jedna usługa na Render) oraz czy współrzędne gospodarstwa zostają u nas.

Współrzędne i obrys działki wskazują gospodarstwo. Zapytanie na żywo wysyła je do operatora usługi. Lepszy układ to zbiór pobrany raz, przypięty do wersji, ze sumą kontrolną, czytany lokalnie. Klucz API, jeśli jest potrzebny, zostaje w środowisku backendu. Odpowiedź ma twardy limit rozmiaru: ULDK przy przeciążeniu odsyła w niekończący się strumień i ten przypadek już jest w kodzie obsłużony.

Pomiary czasów pochodzą z `docs/pomiary-zrodel.md` (21.11.2026, działka `046101_1.0445.7`). Limity w kodzie są w adapterach i bywają ostrzejsze niż tabela w `CLAUDE.md`.

## Wszystkie źródła, z których backend pobiera dane

| Źródło | Kod | Adres | Po co | Ocena |
| --- | --- | --- | --- | --- |
| ULDK GUGiK | `app/sources/uldk.py` | `https://uldk.gugik.gov.pl/` | geometria działki po numerze albo punkcie | warunkowo zawodne |
| UUG GUGiK | `app/sources/geocode.py` | `https://services.gugik.gov.pl/uug/` | adres na współrzędne | brak pomiaru awarii; limit 3 s |
| Open-Meteo, archiwum | `app/sources/meteo.py` | `https://archive-api.open-meteo.com/v1/archive` | opad, ET0, Tmax, Tmin od 1 marca sprzed 10–20 lat | zawodne |
| Open-Meteo, prognoza | `app/sources/meteo.py` | `https://api.open-meteo.com/v1/forecast` | domknięcie luki archiwum i 16 dni do przodu | ta sama pula co archiwum |
| IUNG-PIB, kategorie suszy | `app/sources/iung.py` | `https://sgeo.iung.pl/geoserver/ows` | kategorie gleb SMSR, siatka 5 m | w pomiarze stabilne (0,7 s) |
| ISRIC SoilGrids 2.0 | `app/sources/soilgrids.py` | `https://rest.isric.org/soilgrids/v2.0/properties/query` | retencja, piasek, ił, SOC | zawodne |
| NMT GUGiK | `app/terrain/analysis.py` | `https://mapy.geoportal.gov.pl/wss/service/PZGIK/NMT/GRID1/WCS/DigitalTerrainModel` | wysokości 1 m, ASCII Grid | zawodne |
| OpenStreetMap przez Overpass | `app/sources/water.py` | `https://overpass-api.de/api/interpreter` | rowy i cieki w promieniu 500 m | zawodne |
| Sentinel-2 przez Earth Search | `app/sources/satellite.py`, `app/sources/cog.py` | `https://earth-search.aws.element84.com/v1/search` i pliki COG | NDMI, NDRE, NDVI | słabo skalowalne, często `partial` |

Progi KBW (`kbw_thresholds.yaml`), współczynniki upraw (`crops.yaml`) i progi terenu (`terrain.yaml`) leżą w repozytorium. Przy żądaniu nikt ich nie pobiera.

## 1. Open-Meteo (archiwum i prognoza)

Adapter prosi o `precipitation_sum`, `et0_fao_evapotranspiration`, `temperature_2m_max`, `temperature_2m_min`. Archiwum ma około 5 dni opóźnienia, prognoza ma je domknąć i dodać 16 dni.

21.11.2026 archiwum zwróciło 429 „Daily API request limit exceeded” dla IP sieci hackathonu. Prognoza tego dnia odpowiedziała w 0,3 s. Obie końcówki wchodzą do jednej puli darmowego API: 10 000 wywołań na dobę, 5 000 na godzinę, 600 na minutę, liczone na adres IP, tylko do użytku niekomercyjnego. Długi zakres archiwum jest liczony wielokrotnie (w naszym pomiarze rząd 1 wywołania na 2 tygodnie, więc 10 lat to około 280). Regulamin Open-Meteo wprost ostrzega, że z Render, Vercel i Netlify limit przychodzi wcześniej. Własny serwis na Render wpadnie w ten sam problem, co wspólne IP sali.

### AgERA5, wycinek Polski trzymany u nas

Copernicus CDS, wskaźniki agrometeorologiczne od 1979. Jest dobowy opad, Tmax, Tmin i `reference_evapotranspiration_penman_monteith_fao56` (ET0 FAO-56, to samo, czego używa silnik). Siatka 0,1°, czyli ten sam rząd wielkości co ERA5-Land w Open-Meteo.

**Zalety.** Polska z 20 lat i czterech zmiennych to kilkaset MB. Odczyt punktu idzie z dysku. Współrzędne zostają u nas. Licencja Copernicus, z podaniem źródła. Jedno pobranie obsługuje dowolną liczbę działek.

**Wady.** Pobranie z CDS jest zadaniem wsadowym, więc na ścieżce `/api/context` zostaje plik lokalny, a nie wywołanie API. Aktualizacja jest codzienna i trzeba ją dowieźć osobnym jobem. Brak prognozy 16 dni. Konto CDS i token zostają na backendzie.

### Własna instancja Open-Meteo

Ten sam kontrakt JSON co dziś (`/v1/archive` i `/v1/forecast`). Obraz Dockera, minimum 8 GB RAM i około 100 GB dysku na małe wdrożenie. Dane modeli można brać z dystrybucji S3 i trzymać w cache.

**Zalety.** Po zapełnieniu cache dla Polski kolejne działki zostają na dysku. Pula 10 000 wywołań nas nie dotyczy. Archiwum i prognoza są w jednym procesie, więc luka pięciu dni i horyzont 16 dni zostają bez zmian w silniku.

**Wady.** Kod serwera jest na AGPL-3.0: zmodyfikowana instancja wystawiona w sieci ma udostępnić źródła tej modyfikacji. Zimny cache ściąga kafle z S3, więc widać, który region był pytany. Trzeba pilnować aktualizacji prognozy i atrybucji CC BY 4.0.

### NASA POWER, jeden szereg na punkt

`https://power.larc.nasa.gov/api/temporal/daily/point`, społeczność `AG`. 21.11.2026 dziesięć lat (opad, Tmax, Tmin, wilgotność, wiatr, promieniowanie) wróciło w 1,7 s, 376 kB, bez luk. 22.11.2026 krótkie zapytanie dla tej samej okolicy (18,135°E, 53,105°N) odpowiedziało poprawnym JSON-em, źródło MERRA-2.

**Zalety.** Bez klucza. Jedno wywołanie niesie cały zakres dat, więc długa historia ma jeden koszt. Oficjalnie nie ma sztywnego limitu. Wilgotność, wiatr i promieniowanie pozwalają policzyć ET0 FAO-56 u nas (dzisiejsze zapytanie Open-Meteo tych składników w ogóle nie bierze). Da się też ściągnąć wycinek siatki raz i czytać go lokalnie.

**Wady.** Meteorologia jest na siatce około 0,5° × 0,625° (rzędu 50 km), wyraźnie grubszej niż 0,1°. Gotowego ET0 w słowniku POWER nie ma. Wartość braku danych to −999. Czas domyślnie jest lokalnym czasem słonecznym (`time-standard=UTC` wyrównuje doby). Opóźnienie około tygodnia i brak prognozy. Zapytanie na żywo wysyła współrzędne do NASA; przy nadużyciu NASA przycina ruch.

Prognozę 16 dni AgERA5 i POWER zostawiają pustą. Do tego odcinka pasuje własna instancja Open-Meteo albo lokalne wczytanie otwartych pól GRIB: ICON-EU (DWD, Polska w zasięgu, krok kilku kilometrów) albo otwarte dane ECMWF (IFS, 0,25°, horyzont krótszy niż 16 dni). Oba zestawy są bez klucza. Współrzędne zostają u nas, bo pytamy własny plik. Koszt to job, który co kilka godzin dokłada nowy GRIB.

Płatny plan Open-Meteo zdejmuje limit i zezwala na użytek komercyjny, klucz zostaje na backendzie. Każda działka i tak leci na ich serwer, więc przy dużej liczbie gospodarstw operator widzi mapę zapytań. Ma to sens jako pomost, zanim stanie lokalne archiwum.

## 2. SoilGrids (REST ISRIC)

Dwa równoległe GET-y: retencja `wv0033` i `wv1500` (kwantyle, pięć głębokości) oraz piasek, ił i SOC (średnia, trzy głębokości). Wspólny limit adaptera to 6 s. W pomiarze pełne zapytanie trwało do 27 s, samo wodne 2,7 s i bywało niestabilne. Przy przekroczeniu 6 s przepadają oba wyniki, także ten szybszy. Usługa jest jedna, bez umowy na dostępność. Na ścieżce wielu działek naraz ten czas się nie mieści.

22.11.2026 katalog plików `https://files.isric.org/soilgrids/latest/data/` ma m.in. `sand`, `clay`, `silt`, `soc`, `bdod`. Nie ma w nim `wv0033` ani `wv1500`. Samo zmirrorowanie „latest” nie odtwarza retencji, którą dziś oddaje REST.

### Wycinek tekstury SoilGrids i retencja liczona u nas

Piasek, ił i SOC (średnia oraz kwantyle, osobne pliki) z `files.isric.org`, złożone raz w wycinek Polski.

**Zalety.** Siatka 250 m, dla Polski to setki MB. Odczyt punktu jest milisekundowy i zostawia współrzędne u nas. Licencja CC BY 4.0, ta sama co REST. Kwantyle tekstury dają przedział TAW, tak jak dziś kwantyle `wv`. Jedno źródło, jedna suma kontrolna, dowolna liczba działek.

**Wady.** Trzeba przypiąć funkcję pedotransferu (np. europejskie PTF Tóth i in. 2015) i trzymać jej wersję obok progu w YAML. Wynik jest naszym wyliczeniem, więc `provenance` powinno podać wzór. Pliki na WebDAV są kaflami VRT, wycinek Polski trzeba raz złożyć. Liczby rozjadą się z dzisiejszym `wv0033`/`wv1500`; porównanie na działce testowej wchodzi przed podmianą w silniku.

### EU-SoilHydroGrids 250 m

Europejska mapa FC (pF 2,5, czyli ten sam próg co `wv0033`) i WP (pF 4,2, czyli `wv1500`), siedem głębokości do 2 m, GeoTIFF.

**Zalety.** Po pobraniu leży u nas, więc ścieżka żądania nie woła ISRIC. Semantycznie jest bliżej bilansu wody niż surowa tekstura: od razu jest polowa pojemność i punkt więdnięcia. Odczyt lokalny skaluje się razem z liczbą działek.

**Wady.** Wersja 1.0 jest z 2017 i powstała ze starszego SoilGrids. Brak kwantyli. Licencja ODbL (share-alike przy dalszym udostępnianiu bazy) i rejestracja w ESDAC. Zbiór jest statyczny.

### Kolejka nocna do obecnego REST, odczyt z magazynu

Worker woła `rest.isric.org` poza limitem 6 s, z odstępem między zapytaniami, i zapisuje `wv0033`, `wv1500`, piasek, ił i SOC przy centroidzie. `/api/context` czyta magazyn.

**Zalety.** Zostają liczby i kwantyle z tej samej usługi, której używa silnik dziś. Użytkownik nie czeka 27 s i nie traci szybkie zapytanie, gdy wolne przekroczy limit. Przy trafieniu w magazyn współrzędne wychodzą tylko raz.

**Wady.** REST nadal jest pojedynczym punktem awarii, tylko zeszedł ze ścieżki użytkownika. Nowa działka ma glebę dopiero po przejściu kolejki. ISRIC widzi centroid. Trzeba limitu zapytań workera, inaczej wraca ten sam problem, który dziś daje timeout.

Drugi adres tej samej rodziny (`maps.isric.org`, WCS) zostaje poza ścieżką żywą: to nadal jedno publiczne API bez limitu, który da się udźwignąć przy wielu działkach.

## 3. Cieki i rowy (Overpass)

Zapytanie `way["waterway"]` w promieniu 500 m, serwer `overpass-api.de`, limit 5 s po naszej stronie i w treści zapytania. 21.11.2026 trzy publiczne instancje (overpass-api.de, kumi, private.coffee) nie odpowiedziały przez ponad 40 s. Później `overpass-api.de` potrafił oddać 502, bo kolejka była pełna. Bez tych danych reguły R11 i R14 schodzą do „nie oceniono”. Kolejne publiczne instancje Overpass powielają ten sam wzorzec: współdzielona kolejka, brak umowy, łatwe do zapchania z jednego IP.

### BDOT10k, klasy sieci wodnej

GUGiK publikuje klasy jako GeoParquet. 22.11.2026 sprawdzone pliki krajowe:

| Klasa | Co to jest | Rozmiar |
| --- | --- | --- |
| `OT_SWRM_L.parquet` | rów melioracyjny | około 152 MB |
| `OT_SWRS_L.parquet` | rzeka i strumień | około 192 MB |
| `OT_SWKN_L.parquet` | kanał | około 3,7 MB |

Adres: `https://opendata.geoportal.gov.pl/bdot10k/schemat2021/GeoParquet/<klasa>.parquet`.

**Zalety.** Cała Polska mieści się w jednym indeksie lokalnym. Zapytanie o 500 m jest milisekundowe, obrys działki zostaje u nas. Dane urzędowe, bezpłatne, z atrybucją GUGiK. Rów melioracyjny jest osobną klasą.

**Wady.** Aktualizacja idzie z publikacją GUGiK. Trzeba własny indeks przestrzenny (filtr na GeoParquet albo PostGIS). Nazwy i kompletność różnią się od tagu `waterway`, więc progi R11/R14 warto przeliczyć na działce testowej.

### MPHP10 (ISOK / Wody Polskie), pobrane raz z ATOM

Kanał Atom `https://wody.isok.gov.pl/atom_web/atom/HY_10k` odpowiada. To urzędowa hydrografia cieków.

**Zalety.** Spójne z tym, jak na cieki patrzą Wody Polskie. Po złożeniu lokalnie działa jak BDOT: na ścieżce żądania nie ma WFS. Licencja danych publicznej służby, hosting u nas, współrzędne zostają lokalnie.

**Wady.** MPHP opisuje cieki, a rowów śródpolnych tam nie ma, więc klasę `OT_SWRM_L` i tak warto trzymać obok. Live WFS ISOK ma ten sam słaby punkt co Overpass, dlatego do adaptera wchodzi plik z ATOM. Atrybuty są pod INSPIRE.

### Geofabrik, wycinek Polski, warstwa `waterway` w PostGIS

`poland-latest.osm.pbf`, te same tagi co dziś: `ditch`, `drain`, `stream`, `river`, `canal`.

**Zalety.** Adapter prawie się nie zmienia. Dyfy dzienne, zapytanie lokalne. Polska w PBF ma rząd 2 GB, same cieki są dużo mniejsze. Współrzędne zostają u nas.

**Wady.** Kompletność rowów na wsi w OSM jest nierówna. ODbL wymaga uznania autorstwa i share-alike, gdy publikujemy pochodną bazę. Trzeba utrzymać job aktualizacji.

Rowy widać też w NMT: silnik już klasyfikuje wydłużone zagłębienia. To uzupełnia plik wektorowy przy samej działce. Ciek 500 m dalej nadal bierze się z warstwy wektorowej. Bufor NMT ma dziś 50 m.

## 4. NMT GUGiK (WCS, ASCII Grid)

`GetCoverage` w EPSG:3857, format `image/x-aaigrid`, pokrycie `DTM_PL-EVRF2007-NH`, bufor 50 m, próbka co 2 m. W pomiarze 4,5–10 s i około 457 kB tekstu; limit adaptera to 15 s. W testach opisanych w `CLAUDE.md` ta sama usługa milczała 45–90 s. ASCII jest cięższe niż GeoTIFF, a serwer i tak bywa głuchy. Bez NMT reguły terenu zostają przy „nie oceniono”.

Osobna końcówka WCS z GeoTIFF (`…/DigitalTerrainModelFormatTIFF`) jest na tym samym hoście. Mniejszy plik częściej zmieści się w 15 s. Milczenie przez 45–90 s dotyczy serwera, więc sam format go nie usuwa.

### Mozaika COG z otwartych arkuszy NMT 1 m

GUGiK oddaje NMT bezpłatnie, do dowolnego użytku. Skorowidz (WFS albo WMS GetFeatureInfo) daje URL arkusza na `opendata.geoportal.gov.pl`. Arkusze składamy raz w COG.

**Zalety.** Okno działki czytamy lokalnie, tym samym odczytem zakresu bajtów co Sentinel (`app/sources/cog.py`) albo wprost z dysku. Rozdzielczość 1 m zostaje, więc wykrywanie rowów i oczek ma sens. Kolejne działki nie wołają WCS. Współrzędne zostają u nas.

**Wady.** Krajowa mozaika 1 m po kompresji to rząd setek GB. Na start wystarcza województwo albo cache arkuszy: pierwsze pobranie schodzi z GUGiK poza ścieżką użytkownika. Trzeba pilnować układu wysokości (EVRF2007) i daty arkusza.

### Lokalny NMT 5 m z tego samego zasobu

Też dane otwarte GUGiK, ten sam sposób pobrania.

**Zalety.** Dużo mniejszy dysk niż siatka 1 m. Spadek i różnica wysokości na działce wychodzą. Odczyt lokalny, bez limitu WCS, współrzędne zostają u nas.

**Wady.** Siatka 5 m gubi wąski rów. Progi w `terrain.yaml` (głębokość od 0,1 m, szerokość rowu do 6 m) są ustawione pod model 1 m próbkowany co 2 m. 5 m wystarcza do spadku i jest słabe do oczka oraz zastawki.

### Copernicus DEM GLO-30 (albo FABDEM) jako plik lokalny

Siatka 30 m, otwarty zbiór, wycinek Polski jest mały. W `CLAUDE.md` GLO-30 jest już wpisane jako zapas na później.

**Zalety.** Działa, gdy WCS GUGiK milczy. Odczyt lokalny, licencja Copernicus, obrys nie idzie do Geoportalu. Mały plik, łatwy do przypięcia wersją.

**Wady.** 30 m nie widzi rowu ani oczka śródpolnego. Może zasilić grube statystyki (średni spadek, różnica wysokości) i w `provenance` trzeba oznaczyć gorszą rozdzielczość.

## 5. Sentinel-2 (Earth Search i kafle COG)

Wyszukanie STAC 21.11.2026 trwało 0,8 s i wróciło. Dalej adapter ściąga kafle z S3: maska SCL, potem pasma. Tryb lekki to około 2 MB na działkę, pełny 15–25 MB. Po limicie czasu zostaje `partial`. Earth Search (Element84) jest publicznym STAC bez umowy na dostępność. Przy wielu działkach naraz koszt jest w liczbie połączeń i w transferze.

Silnik potrzebuje średniej na poligonie.

### Copernicus Data Space, Statistical API

Liczy NDMI, NDRE i NDVI po stronie serwera i zwraca kilka kB JSON. Oficjalny dostęp do Sentinela, hosting w UE, OAuth2 (client credentials).

**Zalety.** Konto ogólne: 10 000 żądań i 10 000 jednostek przeliczeniowych na miesiąc, 300 żądań na minutę. Odpowiedź ma kilka kB, więc limit czasu adaptera przestaje ucinać sceny. Token żyje minuty; bierzemy go raz i używamy wielokrotnie, bo endpoint tokenów ma własny limit. Sekret zostaje na backendzie. Obrys idzie do operatora publicznego programu Copernicus.

**Wady.** Darmowa pula jednostek przy dużym prefetchu (20 scen × wiele działek) się kończy; nadwyżka jest płatna. Trzeba evalscript i przeliczenia jednostek. Konto i do 10 aktywnych klientów OAuth. Wynik sezonu i tak warto trzymać w cache, który już mamy.

### CDSE STAC i S3 z krótkim poświadczeniem

Ten sam schemat co dziś (katalog + COG), oficjalny kubełek i token zamiast anonimowego Earth Search.

**Zalety.** Zostaje obecny czytnik COG. Transfer konta ogólnego jest duży (rząd 12 TB / 30 dni, potem łącze zwalnia), więc kilka kafli na działkę się mieści. Dostęp jest na konto, z wygasającym poświadczeniem, a kubełek jest urzędowy.

**Wady.** Nadal ciągniemy megabajty na działkę i nadal możemy skończyć na `partial`. Token S3 wygasa i trzeba go odświeżać. Przy samej średniej na poligonie Statistical API jest lżejsze.

### Microsoft Planetary Computer, kolekcja Sentinel-2 L2A

STAC bez konta, pliki za tokenem SAS. Przy kluczu subskrypcji i ruchu z regionu Azure West Europe limity są wyższe.

**Zalety.** Infrastruktura ma opisane zachowanie przy 503/504. Token SAS da się wziąć na cały kontener i użyć wielokrotnie. Do eksperymentu wystarcza dostęp bez umowy.

**Wady.** Nadal pobieramy kafle. Zapytanie (bbox działki) idzie do Microsoftu. Dla danych gospodarstw słabszy wybór niż CDSE w UE. Bez klucza limity są ostrzejsze, a token i tak trzeba odnawiać.

## 6. ULDK (warunkowo)

Zwykła odpowiedź trwa 0,14–0,3 s. Przy przeciążeniu usługa daje 302 na `integracja01.gugik.gov.pl/resp/uldk.php` bez parametrów, a tamten adres zwraca niekończący się gzip. Adapter już nie idzie za przekierowaniem, ucina ciało po 1 MB i ma jedną powtórkę w limicie 3 s. Dodatkowo GUGiK podaje rząd 200 zapytań na minutę. Z jednego IP sali albo Render da się ten próg przekroczyć samymi wyszukiwaniami.

Drugiej krajowej usługi, która po numerze TERYT oddaje geometrię ewidencyjną, nie ma. KIEG (`KrajowaIntegracjaEwidencjiGruntow`) rysuje granice w przeglądarce. Geometrię do silnika oddaje ULDK. PRG ma granice jednostek i adresy.

### Trwały magazyn geometrii, którą ULDK już oddał

`/api/parcel` potrafi zajrzeć do cache, zanim zapyta ULDK.

**Zalety.** Zapis każdego udanego `Parcel` zdejmuje powtórne wyszukania z limitu 200/min i z okna, w którym usługa zwraca gzip. Obrys zostaje u nas. Działa na danych, które i tak już pobieramy.

**Wady.** Pierwsze trafienie nowej działki nadal wisi na ULDK. Ewidencja się zmienia (podziały), więc zapis potrzebuje daty i drogi odświeżenia.

### Kolejka do ULDK z budżetem 200 zapytań na minutę

Obok zostaje twardy limit bajtów i zakaz śledzenia przekierowania 302.

**Zalety.** Chroni i nas, i usługę. Po przekroczeniu budżetu użytkownik dostaje komunikat. Jedno IP (Render, sala) przestaje być w stanie zalać ULDK.

**Wady.** To obudowa tej samej usługi. W szczycie ludzie czekają. Nowej geometrii ta kolejka nie dodaje.

### Zrzut EGiB od GUGiK albo starosty

Ma sens dopiero przy umowie o zasób.

**Zalety.** Geometria jest wtedy lokalna, jak BDOT, i ULDK zostaje dla działek spoza zrzutu. Współrzędne wyszukiwania zostają u nas. Skala przestaje zależeć od 200 zapytań na minutę.

**Wady.** Dziś nie ma otwartego, krajowego pliku działek ewidencyjnych w stylu GeoParquet BDOT10k. Zrzut wymaga podstawy prawnej i aktualizacji z urzędu. Na hackathon się tego nie podmieni.

## Źródła, które w pomiarze trzymały się limitu

**IUNG WCS** (`Susza__katgl_landuse2024`) odpowiedział w 0,7 s. Zostaje jedna instancja GeoServer bez jawnej licencji i z pułapką osi EPSG:2180 (oś `x` to northing), już poprawioną w `iung.py`. Gdy ta usługa padnie, zamiennikiem o tej samej treści jest wycinek tego rastra trzymany lokalnie.

**UUG** (adres na punkt) ma limit 3 s i nie ma w `docs/pomiary-zrodel.md` śladu awarii. To ta sama rodzina GUGiK co ULDK: przy wzroście ruchu warto trzymać wyniki wyszukiwania u nas.

## Kolejność, gdyby podmieniać

1. Cieki: GeoParquet BDOT10k (`OT_SWRM_L`, `OT_SWRS_L`, `OT_SWKN_L`). Pliki są małe, urzędowe i zdejmują usługę, która dziś nie odpowiada.
2. Pogoda: wycinek AgERA5 na archiwum (jest ET0 FAO-56) i osobne, lokalne źródło prognozy. NASA POWER zostaje zapasem archiwum, z grubszą siatką i ET0 liczonym u nas.
3. Gleba: wycinek SoilGrids (piasek, ił, SOC) i retencja z pedotransferu. EU-SoilHydroGrids, gdy wolimy gotowe FC/WP i wchodzi ODbL oraz starszy rocznik.
4. NMT: COG z arkuszy 1 m, najpierw region, który naprawdę obsługujemy. GLO-30 jako oznaczony zapas spadku.
5. Sentinel: Statistical API w CDSE, wynik sezonu w obecnym cache.
6. ULDK: magazyn geometrii i budżet zapytań. Drugiego rejestru nie ma.
