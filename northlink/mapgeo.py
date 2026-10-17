"""Display-only Web Mercator coordinates. Evidence matching stays in WGS84."""
import math

K = math.cos(math.radians(70)) * 100
MERCATOR_ORIGIN = math.asinh(math.tan(math.radians(70)))
METRES_PER_UNIT = 6378137 * math.pi / (180 * K)


def project(lon, lat):
    lat = max(-85.05112878, min(85.05112878, lat))
    return (round((lon - 25) * K, 4),
            round((MERCATOR_ORIGIN - math.asinh(math.tan(math.radians(lat)))) * 180 / math.pi * K, 4))


def tile_bounds(z, x0, y0, x1, y1):
    """Inclusive XYZ tile range -> WGS84 west, south, east, north."""
    n = 2 ** z
    def latitude(y):
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return [x0 / n * 360 - 180, latitude(y1 + 1),
            (x1 + 1) / n * 360 - 180, latitude(y0)]
