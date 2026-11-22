// Źródła naukowe i metody: lista do sekcji szczegółów i nakładki „Jak liczymy”. Przy każdym: do czego go używamy.
export const REFS = [
  {
    use: "Bilans wody w glebie, zużycie wody przez uprawy (Kc), pojemność wodna gleby, stres wodny",
    cite: "Allen R.G., Pereira L.S., Raes D., Smith M. (1998). Crop evapotranspiration – Guidelines for computing crop water requirements. FAO Irrigation and Drainage Paper 56. FAO, Rzym.",
    url: "https://www.fao.org/4/x0490e/x0490e00.htm",
  },
  {
    use: "Progi suszy (klimatyczny bilans wodny) dla upraw i kategorii gleb",
    cite: "Rozporządzenie Ministra Rolnictwa i Rozwoju Wsi z dnia 11 kwietnia 2019 r. w sprawie wartości klimatycznego bilansu wodnego dla poszczególnych gatunków roślin uprawnych i gleb (Dz.U. 2019 poz. 739).",
    url: "https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20190000739",
  },
  {
    use: "Kategorie podatności gleb na suszę",
    cite: "IUNG-PIB, System Monitoringu Suszy Rolniczej w Polsce (warstwa kategorii gleb, 2024).",
    url: "https://susza.iung.pulawy.pl/",
  },
  {
    use: "Pogoda historyczna (opad, parowanie, temperatura)",
    cite: "Hersbach H. i in. (2020). The ERA5 global reanalysis. Quarterly Journal of the Royal Meteorological Society 146: 1999–2049; Muñoz-Sabater J. i in. (2021). ERA5-Land: a state-of-the-art global reanalysis dataset for land applications. Earth System Science Data 13: 4349–4383. Dostęp przez Open-Meteo.com (CC BY 4.0).",
    url: "https://open-meteo.com/",
  },
  {
    use: "Właściwości wodne gleby (pojemność polowa, punkt więdnięcia)",
    cite: "Poggio L. i in. (2021). SoilGrids 2.0: producing soil information for the globe with quantified spatial uncertainty. SOIL 7: 217–240.",
    url: "https://soilgrids.org/",
  },
  {
    use: "Zagłębienia terenu i miejsca, gdzie zbiera się woda",
    cite: "Barnes R., Lehman C., Mulla D. (2014). Priority-flood: An optimal depression-filling and watershed-labeling algorithm for digital elevation models. Computers & Geosciences 62: 117–127.",
  },
  {
    use: "Kierunki i linie spływu wody po polu",
    cite: "O'Callaghan J.F., Mark D.M. (1984). The extraction of drainage networks from digital elevation data. Computer Vision, Graphics, and Image Processing 28: 323–344.",
  },
  {
    use: "Model wysokości terenu (siatka 1 m, lotniczy skaning laserowy)",
    cite: "Główny Urząd Geodezji i Kartografii, Numeryczny Model Terenu (NMT), usługa WCS Geoportalu.",
    url: "https://www.geoportal.gov.pl/",
  },
  {
    use: "Wilgotność roślin ze zdjęć satelitarnych (NDMI)",
    cite: "Gao B.-C. (1996). NDWI – A normalized difference water index for remote sensing of vegetation liquid water from space. Remote Sensing of Environment 58: 257–266. Dane: Copernicus Sentinel-2 (ESA).",
  },
  {
    use: "Działania zatrzymujące wodę (pasy buforowe, zastawki, oczka, uprawa konserwująca)",
    cite: "European Commission (2015). Natural Water Retention Measures – katalog działań i dowodów skuteczności.",
    url: "https://nwrm.eu/",
  },
  {
    use: "Przeliczenia współrzędnych (PUWG 1992, UTM)",
    cite: "Snyder J.P. (1987). Map Projections – A Working Manual. U.S. Geological Survey Professional Paper 1395.",
  },
];

export default function ScienceSources() {
  return (
    <ol className="refs">
      {REFS.map((r) => (
        <li key={r.cite}>
          <b>{r.use}.</b> {r.cite}{r.url && <> <a href={r.url} target="_blank" rel="noreferrer">{r.url.replace(/^https:\/\//, "").replace(/\/$/, "")}</a></>}
        </li>
      ))}
    </ol>
  );
}
