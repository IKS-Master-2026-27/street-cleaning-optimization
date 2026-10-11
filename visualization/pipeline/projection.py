"""Longitude/latitude to UTM metres (WGS84), without third-party packages.

Uses the Krüger series to sixth order, which is accurate to well under a
millimetre inside a UTM zone. The zone is picked from the city centre, so a
city is always projected in one zone even if it touches a zone border.
"""

import math

_A = 6378137.0
_F = 1 / 298.257223563
_K0 = 0.9996
_N = _F / (2 - _F)
_RECT = _A / (1 + _N) * (1 + _N**2 / 4 + _N**4 / 64 + _N**6 / 256)
_ALPHA = (
    _N / 2 - 2 * _N**2 / 3 + 5 * _N**3 / 16 + 41 * _N**4 / 180
    - 127 * _N**5 / 288 + 7891 * _N**6 / 37800,
    13 * _N**2 / 48 - 3 * _N**3 / 5 + 557 * _N**4 / 1440
    + 281 * _N**5 / 630 - 1983433 * _N**6 / 1935360,
    61 * _N**3 / 240 - 103 * _N**4 / 140 + 15061 * _N**5 / 26880
    + 167603 * _N**6 / 181440,
    49561 * _N**4 / 161280 - 179 * _N**5 / 168 + 6601661 * _N**6 / 7257600,
    34729 * _N**5 / 80640 - 3418889 * _N**6 / 1995840,
    212378941 * _N**6 / 319334400,
)
_E2N = 2 * math.sqrt(_N) / (1 + _N)


def utm_zone(lon: float, lat: float) -> tuple[int, bool]:
    """Return (zone number, is_south)."""
    zone = int((lon + 180) // 6) + 1
    return min(max(zone, 1), 60), lat < 0


class Projector:
    """Projects lon/lat into metres relative to an origin, as (east, north)."""

    def __init__(self, zone: int, south: bool, origin=(0.0, 0.0)):
        self.zone = zone
        self.south = south
        self.lon0 = math.radians(zone * 6 - 183)
        self.origin = origin

    @property
    def label(self) -> str:
        return f"{self.zone}{'S' if self.south else 'N'}"

    def utm(self, lon: float, lat: float) -> tuple[float, float]:
        phi = math.radians(lat)
        dlon = math.radians(lon) - self.lon0
        sin_phi = math.sin(phi)
        t = math.sinh(math.atanh(sin_phi) - _E2N * math.atanh(_E2N * sin_phi))
        xi = math.atan2(t, math.cos(dlon))
        eta = math.atanh(math.sin(dlon) / math.sqrt(1 + t * t))
        east, north = eta, xi
        for j, alpha in enumerate(_ALPHA, start=1):
            east += alpha * math.cos(2 * j * xi) * math.sinh(2 * j * eta)
            north += alpha * math.sin(2 * j * xi) * math.cosh(2 * j * eta)
        east = 500000.0 + _K0 * _RECT * east
        north = _K0 * _RECT * north + (10000000.0 if self.south else 0.0)
        return east, north

    def __call__(self, lon: float, lat: float) -> tuple[float, float]:
        east, north = self.utm(lon, lat)
        return east - self.origin[0], north - self.origin[1]


def projector_for(points) -> Projector:
    """Choose the zone from the bounding-box centre and centre the origin there."""
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    lon_c = (min(lons) + max(lons)) / 2
    lat_c = (min(lats) + max(lats)) / 2
    zone, south = utm_zone(lon_c, lat_c)
    projector = Projector(zone, south)
    east, north = projector.utm(lon_c, lat_c)
    projector.origin = (round(east), round(north))
    return projector
