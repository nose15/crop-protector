// Wspólne warstwy map (Geoportal GUGiK, OSM). Nazwy warstw sprawdzone 21.11.2026 (docs/pomiary-zrodel.md).
import { LayersControl, TileLayer, WMSTileLayer } from "react-leaflet";

export const ORTO = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardResolution";
export const KIEG = "https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow";
export const RELIEF = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/NMT/GRID1/WMS/ShadedRelief";

export const toLatLng = (ring) => ring.map(([lon, lat]) => [lat, lon]);

export function BaseLayers() {
  return (
    <>
      <LayersControl.BaseLayer checked name="Ortofotomapa">
        <WMSTileLayer url={ORTO} layers="Raster" format="image/jpeg" version="1.3.0" styles="default"
          attribution="Ortofotomapa © GUGiK" maxZoom={20} />
      </LayersControl.BaseLayer>
      <LayersControl.BaseLayer name="Mapa">
        <TileLayer url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" attribution="© OpenStreetMap" maxZoom={19} />
      </LayersControl.BaseLayer>
    </>
  );
}

export function ReliefLayer() {
  return (
    <LayersControl.Overlay name="Cieniowanie terenu">
      <WMSTileLayer url={RELIEF} layers="Raster" format="image/png" transparent version="1.3.0" opacity={0.5}
        attribution="NMT © GUGiK" maxZoom={20} />
    </LayersControl.Overlay>
  );
}
