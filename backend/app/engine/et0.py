"""ET0 FAO Penman-Monteith (FAO-56 r. 6) z dobowych danych NASA POWER.

Przeniesione ze sprawdzonej wersji starej aplikacji (KOWR/app/kowr/calc/et0.py, 21.11.2026). Wzory FAO-56 rozdz. 3:
ciśnienie (r. 7), γ (r. 8), e° (r. 11), Δ (r. 13), Ra (r. 21–25), Rso (r. 37), Rs z temperatury (r. 50),
Rn (r. 38–40). NASA POWER nie podaje ET0, więc liczymy je w aplikacji tym samym wzorem, którego Open-Meteo używa
dla `et0_fao_evapotranspiration` – bilans i KBW nie zmieniają metody po zmianie źródła pogody.
"""

from __future__ import annotations

import math

import numpy as np

GSC = 0.0820          # stała słoneczna, MJ m⁻² min⁻¹
SIGMA = 4.903e-9      # stała Stefana-Boltzmanna, MJ K⁻⁴ m⁻² d⁻¹


def e0(t):
    """Ciśnienie pary nasyconej [kPa] (FAO-56 r. 11)."""
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def ra_mj(lat_deg: float, doy) -> np.ndarray:
    """Promieniowanie pozaziemskie Ra [MJ m⁻² d⁻¹] (FAO-56 r. 21–25)."""
    doy = np.asarray(doy, float)
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    dec = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-math.tan(phi) * np.tan(dec), -1, 1))
    return 24 * 60 / np.pi * GSC * dr * (ws * math.sin(phi) * np.sin(dec) + math.cos(phi) * np.cos(dec) * np.sin(ws))


def fao_pm(tmax, tmin, doy, lat: float, z: float, u2=None, tdew=None, rs=None, krs: float = 0.16) -> np.ndarray:
    """Dobowe ET0 [mm/d]. Brak Rs → z temperatury (r. 50, krs 0,16 dla wnętrza lądu), brak u2 → 2 m/s (FAO-56 r. 3),
    brak Tdew → ea z Tmin (FAO-56 r. 48). Dni bez Tmax/Tmin dają NaN (bez cichej wartości domyślnej)."""
    tmax = np.asarray(tmax, float)
    tmin = np.asarray(tmin, float)
    t = (tmax + tmin) / 2
    p = 101.3 * ((293 - 0.0065 * z) / 293) ** 5.26
    gamma = 0.665e-3 * p
    delta = 4098 * e0(t) / (t + 237.3) ** 2
    es = (e0(tmax) + e0(tmin)) / 2
    ea = e0(np.asarray(tdew, float)) if tdew is not None else e0(tmin)
    ea = np.where(np.isnan(ea), e0(tmin), ea)
    ea = np.minimum(ea, es)
    ra = ra_mj(lat, doy)
    rs_est = krs * np.sqrt(np.maximum(tmax - tmin, 0)) * ra
    rs = rs_est if rs is None else np.where(np.isnan(np.asarray(rs, float)), rs_est, rs)
    rso = (0.75 + 2e-5 * z) * ra
    rns = (1 - 0.23) * rs
    ratio = np.clip(np.where(rso > 0, rs / rso, 0.5), 0.25, 1.0)
    rnl = SIGMA * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2 * (0.34 - 0.14 * np.sqrt(ea)) * (1.35 * ratio - 0.35)
    rn = rns - rnl
    u2 = np.full_like(t, 2.0) if u2 is None else np.where(np.isnan(np.asarray(u2, float)), 2.0, u2)
    et0 = (0.408 * delta * rn + gamma * 900 / (t + 273) * u2 * (es - ea)) / (delta + gamma * (1 + 0.34 * u2))
    return np.maximum(et0, 0.0)
