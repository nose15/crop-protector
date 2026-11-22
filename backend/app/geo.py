"""Proste przeliczenia geometrii bez zewnętrznych bibliotek (bez pyproj/GDAL).

EPSG:2180 (PUWG 1992): odwzorowanie poprzeczne Merkatora na elipsoidzie GRS80,
południk osiowy 19°E, k0 = 0,9993, FE = 500 000 m, FN = −5 300 000 m.
Wzory: Snyder, „Map Projections – A Working Manual” (1987), s. 61. Dokładność ≪ 1 m w Polsce.
"""

from __future__ import annotations

import math

import numpy as np

_A = 6378137.0
_F = 1 / 298.257222101
_E2 = 2 * _F - _F * _F
_EP2 = _E2 / (1 - _E2)
_K0 = 0.9993
_FE, _FN = 500000.0, -5300000.0


def _meridian_arc(phi: float) -> float:
    e2, e4, e6 = _E2, _E2**2, _E2**3
    return _A * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
                 - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
                 + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
                 - (35 * e6 / 3072) * math.sin(6 * phi))


def _tm(lon: float, lat: float, lon0_deg: float, k0: float, fe: float, fn: float) -> tuple[float, float]:
    """Odwzorowanie poprzeczne Merkatora (elipsoida GRS80 ≈ WGS84), wzory Snydera."""
    phi, lam = math.radians(lat), math.radians(lon)
    n = _A / math.sqrt(1 - _E2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = _EP2 * math.cos(phi) ** 2
    a = (lam - math.radians(lon0_deg)) * math.cos(phi)
    x = fe + k0 * n * (a + (1 - t + c) * a**3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * _EP2) * a**5 / 120)
    y = fn + k0 * (_meridian_arc(phi) + n * math.tan(phi) * (
        a * a / 2 + (5 - t + 9 * c + 4 * c * c) * a**4 / 24
        + (61 - 58 * t + t * t + 600 * c - 330 * _EP2) * a**6 / 720))
    return x, y


def to_2180(lon: float, lat: float) -> tuple[float, float]:
    """(lon, lat) WGS84 → (x = easting, y = northing) w metrach EPSG:2180."""
    return _tm(lon, lat, 19.0, _K0, _FE, _FN)


def to_utm(lon: float, lat: float, epsg: int) -> tuple[float, float]:
    """(lon, lat) → UTM północny (EPSG 326xx, np. 32633 = strefa 33N), w metrach."""
    zone = epsg - 32600
    return _tm(lon, lat, zone * 6 - 183, 0.9996, 500000.0, 0.0)


def ring_area_m2(ring: list[list[float]]) -> float:
    """Pole pierścienia [[lon, lat], ...] w m² (w EPSG:2180)."""
    xy = [to_2180(lon, lat) for lon, lat in ring]
    s = 0.0
    for (x1, y1), (x2, y2) in zip(xy, xy[1:] + xy[:1]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def bbox_2180(ring: list[list[float]], buffer_m: float = 0.0) -> tuple[float, float, float, float]:
    xy = [to_2180(lon, lat) for lon, lat in ring]
    xs, ys = [p[0] for p in xy], [p[1] for p in xy]
    return min(xs) - buffer_m, min(ys) - buffer_m, max(xs) + buffer_m, max(ys) + buffer_m


def polygon_mask(ring_xy: list[tuple[float, float]], xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Maska środków komórek siatki (xs: kolumny, ys: wiersze) wewnątrz wielokąta; ray casting."""
    X, Y = np.meshgrid(xs, ys)
    inside = np.zeros(X.shape, bool)
    n = len(ring_xy)
    for k in range(n):
        x1, y1 = ring_xy[k]
        x2, y2 = ring_xy[(k + 1) % n]
        cond = (y1 > Y) != (y2 > Y)
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = (x2 - x1) * (Y - y1) / (y2 - y1) + x1
        inside ^= cond & (X < xint)
    return inside
