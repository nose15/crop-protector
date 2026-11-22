// Mapa na cały ekran (styl rozdz. 7). Dwa widoki:
//  - szukanie: kliknięcie = podgląd działki z ULDK i dymek „Sprawdź tę działkę”, widać granice działek;
//  - zablokowanie na działce: przelot do działki, przesuwanie ograniczone do okolicy, reszta mapy przyciemniona,
//    kliknięcie obok nic nie wybiera; obrys w kolorze werdyktu, warstwy terenu i znaczniki.
import { useEffect, useRef } from "react";
import {
  ImageOverlay, LayersControl, MapContainer, Marker, Polygon, Popup, WMSTileLayer, ZoomControl, useMap, useMapEvents,
} from "react-leaflet";
import L from "leaflet";
import { BaseLayers, KIEG, ReliefLayer, toLatLng } from "./mapLayers.jsx";
import { KINDS } from "./MapLegend.jsx";
import Seg from "./Seg.jsx";
import { LEVEL } from "../lib/present.js";

const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// widok startowy: ostatnio sprawdzana działka (zapamiętana w przeglądarce), inaczej okolice Bydgoszczy
// (tam leży działka testowa; widać granice działek po przybliżeniu)
function startView() {
  try {
    const v = JSON.parse(localStorage.getItem("kowr-last-view") || "null");
    if (v && Number.isFinite(v.lat) && Number.isFinite(v.lon)) return { center: [v.lat, v.lon], zoom: 15 };
  } catch { /* brak dostępu do pamięci przeglądarki */ }
  return { center: [53.123, 18.008], zoom: 12 };       // Bydgoszcz
}

function fitPadding() {
  if (window.innerWidth <= 900) return { padding: [20, 20] };
  const panel = document.querySelector(".panel")?.getBoundingClientRect().width || 460;
  const top = document.querySelector(".topbar")?.getBoundingClientRect().height || 76;
  return { paddingTopLeft: [panel + 50, top + 40], paddingBottomRight: [60, 40] };
}

const WORLD = [[-89, -179], [-89, 179], [89, 179], [89, -179]];

// blokada na działce: po przelocie ograniczamy przesuwanie i oddalanie; po odblokowaniu zdejmujemy ograniczenia
function LockView({ rings, locked }) {
  const map = useMap();
  useEffect(() => {
    if (!locked || !rings?.length) {
      map.setMaxBounds(null);
      map.setMinZoom(0);
      return undefined;
    }
    const b = L.latLngBounds(toLatLng(rings[0]));
    const apply = () => {
      map.setMaxBounds(b.pad(1.5));
      map.setMinZoom(Math.max(map.getZoom() - 2, 12));
    };
    map.once("moveend", apply);
    const t = setTimeout(apply, 1700);
    return () => { clearTimeout(t); map.off("moveend", apply); };
  }, [rings, locked, map]);
  return null;
}

function FlyToParcel({ rings, version }) {
  const map = useMap();
  useEffect(() => {
    if (!rings?.length) return;
    const b = L.latLngBounds(toLatLng(rings[0]));
    try {
      const c = b.getCenter();
      localStorage.setItem("kowr-last-view", JSON.stringify({ lat: c.lat, lon: c.lng }));
    } catch { /* tryb prywatny */ }
    if (reduceMotion()) map.fitBounds(b, { maxZoom: 17, ...fitPadding() });
    else map.flyToBounds(b, { maxZoom: 17, duration: 1.4, ...fitPadding() });
  }, [rings, version, map]);
  return null;
}

// „Pokaż na mapie”: przelot do znacznika i otwarcie jego dymka
function FocusMarker({ target, markers }) {
  const map = useMap();
  useEffect(() => {
    if (!target) return;
    const open = () => markers.current[target.id]?.openPopup();
    if (reduceMotion()) { map.setView(target.at, Math.max(map.getZoom(), 17)); open(); return; }
    map.once("moveend", open);
    map.flyTo(target.at, Math.max(map.getZoom(), 17), { duration: 0.6 });
    const t = setTimeout(open, 750);
    return () => { clearTimeout(t); map.off("moveend", open); };
  }, [target, map, markers]);
  return null;
}

// MapContainer nie przekazuje atrybutów dostępności do HTML: ustawiamy je na kontenerze mapy
function MapA11y() {
  const map = useMap();
  useEffect(() => {
    const c = map.getContainer();
    c.setAttribute("role", "region");
    c.setAttribute("aria-label", "Mapa: kliknij działkę, żeby ją sprawdzić");
  }, [map]);
  return null;
}

function Clicks({ onPick, disabled }) {
  useMapEvents({ click: (e) => { if (!disabled) onPick(e.latlng.lat, e.latlng.lng); } });
  return null;
}

function PreviewPopup({ preview, onCheck }) {
  const ref = useRef(null);
  useEffect(() => { ref.current?.openPopup(); }, [preview]);
  return (
    <Polygon ref={ref} positions={preview.rings.map(toLatLng)}
      pathOptions={{ color: LEVEL.info.color, weight: 4, fillColor: LEVEL.info.color, fillOpacity: 0.2 }}>
      <Popup>
        <strong>Działka {preview.number}, obręb {preview.obreb}</strong><br />
        {preview.gmina}, {preview.area_ha.toLocaleString("pl-PL", { maximumFractionDigits: 2 })} ha
        <div><button type="button" className="sbtn primary popup-go" onClick={onCheck}>Sprawdź tę działkę</button></div>
      </Popup>
    </Polygon>
  );
}

const icon = (kind, active) => L.divIcon({
  className: `map-marker${active ? " active" : ""}`,
  html: `<span class="mk mk-${kind}"></span>`,
  iconSize: active ? [26, 26] : [20, 20],
});

const START = startView();

export default function MapView({ parcel, locked, level, terrain, preview, onPick, onCheckPreview, busy, flyVersion,
  questions = {}, active = new Set(), sites = {}, onSiteAnswer, focus }) {
  const markerRefs = useRef({});
  const color = LEVEL[level]?.color || LEVEL.info.color;
  return (
    <MapContainer id="map" center={START.center} zoom={START.zoom} zoomControl={false}>
      <MapA11y />
      <ZoomControl position="topright" zoomInTitle="Przybliż" zoomOutTitle="Oddal" />
      <LayersControl position="topright">
        <BaseLayers />
        {!locked && (
          <LayersControl.Overlay checked name="Granice działek">
            <WMSTileLayer url={KIEG} layers="dzialki,numery_dzialek" format="image/png" transparent version="1.3.0"
              attribution="KIEG © GUGiK" minZoom={15} maxZoom={20} />
          </LayersControl.Overlay>
        )}
        <ReliefLayer />
        {terrain?.layers && (
          <>
            <LayersControl.Overlay checked name="Tędy spływa woda">
              <ImageOverlay url={terrain.layers.flow} bounds={terrain.bounds} />
            </LayersControl.Overlay>
            <LayersControl.Overlay name="Zagłębienia">
              <ImageOverlay url={terrain.layers.depressions} bounds={terrain.bounds} />
            </LayersControl.Overlay>
            <LayersControl.Overlay name="Spadki terenu">
              <ImageOverlay url={terrain.layers.slope} bounds={terrain.bounds} />
            </LayersControl.Overlay>
          </>
        )}
      </LayersControl>

      {!locked && preview && <PreviewPopup preview={preview} onCheck={onCheckPreview} />}
      {locked && parcel && (
        <Polygon positions={[WORLD, toLatLng(parcel.rings[0])]} interactive={false}
          pathOptions={{ stroke: false, fillColor: "#1A1F1C", fillOpacity: 0.38 }} />
      )}
      {locked && parcel && (
        <Polygon positions={parcel.rings.map(toLatLng)} interactive={false}
          pathOptions={{ color, weight: 4, fillColor: color, fillOpacity: 0.2 }} />
      )}
      {locked && terrain?.markers?.map((m) => (
        <Marker key={m.id} position={m.at} icon={icon(m.kind, active.has(m.id))} title={KINDS[m.kind] || m.title}
          alt={KINDS[m.kind] || m.title} ref={(r) => { markerRefs.current[m.id] = r; }}>
          <Popup>
            <strong>{m.title}</strong><br />{m.text}
            {questions[m.id] && (
              <div className="popup-q">
                <span>{questions[m.id]}</span>
                <Seg label={questions[m.id]} value={sites[m.id] ?? null} onChange={(v) => onSiteAnswer(m.id, v)} />
              </div>
            )}
          </Popup>
        </Marker>
      ))}
      <FlyToParcel rings={locked ? parcel?.rings : null} version={flyVersion} />
      <LockView rings={parcel?.rings} locked={locked} />
      <FocusMarker target={focus} markers={markerRefs} />
      <Clicks onPick={onPick} disabled={busy || locked} />
    </MapContainer>
  );
}
