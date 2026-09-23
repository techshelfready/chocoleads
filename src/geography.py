"""Search ZIP codes in geographic order using bundled Census geographic ZIP-area centroids."""
import csv
import math
import re
from functools import lru_cache
from .config import settings


@lru_cache(maxsize=1)
def zip_centroids():
    with (settings.project_root / 'assets/us_zcta_centroids.csv').open() as f:
        return {r['zipcode']: (float(r['latitude']), float(r['longitude']))
                for r in csv.DictReader(f)}


def search_zipcodes(zipcode):
    if not re.fullmatch(r'\d{5}', zipcode):
        raise ValueError('Enter a valid five-digit US ZIP code.')
    coords = zip_centroids()
    if zipcode not in coords:
        raise ValueError('This ZIP code could not be located. Enter a nearby geographic ZIP code.')
    lat, lon = map(math.radians, coords[zipcode])
    def distance(item):
        other_lat, other_lon = map(math.radians, item[1])
        a = math.sin((other_lat-lat)/2)**2 + math.cos(lat)*math.cos(other_lat)*math.sin((other_lon-lon)/2)**2
        return 3958.8 * 2 * math.asin(min(1, math.sqrt(a)))
    yield zipcode, 0.0
    for code, miles in sorted(((code, distance((code, point))) for code, point in coords.items() if code != zipcode), key=lambda p: (p[1], p[0])):
        yield code, miles
