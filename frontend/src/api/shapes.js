// Kształty obiektów API: lustro backend/app/models.py (bez TypeScript, tylko JSDoc).
// Zmieniasz model Pydantic -> zmień też tutaj.

/**
 * @typedef {Object} Provenance
 * @property {string} source
 * @property {"ok"|"partial"|"timeout"|"error"|"empty"} status
 * @property {"live"|"constant"|"fallback"} mode
 * @property {number} latency_ms
 * @property {string} retrieved_at        ISO
 * @property {string} licence
 * @property {string|null} data_until     YYYY-MM-DD
 * @property {string|null} note
 */

/**
 * @typedef {Object} Parcel
 * @property {string} id                  np. "046101_1.0445.7"
 * @property {string|null} teryt7
 * @property {string|null} voivodeship
 * @property {string|null} county
 * @property {string|null} gmina
 * @property {string|null} obreb
 * @property {string|null} number
 * @property {number[][][]} rings         [[[lon, lat], ...], ...] EPSG:4326
 * @property {number[]} centroid          [lon, lat]
 * @property {number} area_ha
 */

/**
 * @typedef {Object} MeteoDay
 * @property {string} date
 * @property {number|null} p_mm
 * @property {number|null} et0_mm
 * @property {number|null} tmax
 * @property {number|null} tmin
 */

/**
 * @typedef {Object} ParcelContext
 * @property {number} schema_version
 * @property {string} as_of
 * @property {boolean} partial
 * @property {Parcel} parcel
 * @property {{daily: MeteoDay[], forecast: MeteoDay[], resolution: string}|null} meteo
 * @property {{iung: {shares: Object<string, number>, dominant: string|null, n_cells: number}|null,
 *             soilgrids: Object|null}} soil
 * @property {Object|null} terrain         stats, depressions, markers, layers (PNG data URL), bounds
 * @property {{nearest_watercourse_m: number|null, nearest_ditch_m: number|null, geojson: Object|null}|null} water
 * @property {Object|null} satellite
 * @property {Provenance[]} provenance
 */

/**
 * @typedef {Object} RecommendRequest
 * @property {"zboza_ozime"|"zboza_jare"|"kukurydza_ziarno"|"kukurydza_kiszonka"|"rzepak"|"ziemniak"|"burak_cukrowy"|"uzytki_zielone"} crop
 * @property {{from: string, to: string}} range
 * @property {string|null} sowing_date
 * @property {{irrigation_water: boolean|null, drained: boolean|null, ditch_with_weir: boolean|null}} answers
 */

export const CROPS = [
  ["zboza_ozime", "Zboża ozime"],
  ["zboza_jare", "Zboża jare"],
  ["kukurydza_ziarno", "Kukurydza na ziarno"],
  ["kukurydza_kiszonka", "Kukurydza na kiszonkę"],
  ["rzepak", "Rzepak"],
  ["ziemniak", "Ziemniaki"],
  ["burak_cukrowy", "Burak cukrowy"],
  ["uzytki_zielone", "Użytki zielone"],
];
