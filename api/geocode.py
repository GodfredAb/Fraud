"""
geocode.py (api/)
------------------
Resolves a (lat, lon) pair to a human-readable place - Region -> City ->
Suburb -> Street -> Building - WITHOUT calling a real reverse-geocoding
API. See design.md at the project root for why: every coordinate in this
project is synthetic (database/seed_generator.py jitters points around
one of ten real Ghanaian regional capitals - GHANA_REGIONS below, kept in
sync with seed_generator.py's own copy by lat/lon value), and feeding a
fake coordinate to a real geocoder returns the address of a REAL building
that has nothing to do with the fictional subscriber "standing" there -
not a rounding error, actively misleading.

Instead this is a small deterministic synthetic gazetteer: region/city/
suburb names are real (harmless at that granularity - like any map
showing real neighborhood names), but street and building identifiers are
synthetically generated, so nothing asserts a specific real building is
involved. Same spirit as the rest of this project's synthetic data (real
Ghanaian first/last names, fake national ID numbers, fake IMEIs).

Deterministic: the same (lat, lon) always resolves to the same address -
no randomness, no external call, no state. Pure presentation layer; does
not touch ml/, schema.sql, or how locations are generated.
"""

import math

# Kept in sync (by lat/lon) with database/seed_generator.py's GHANA_REGIONS -
# nearest-center classification, not a bearing/sign split: region centers
# here are 50km+ apart (closest pair, Central/Western, ~52km), so "nearest
# of these ten points" is stable even right at a region's jitter edge,
# unlike a single-center bearing split (see the Accra-only version's git
# history for why that broke: two points a few hundred meters apart could
# land in different "cities" whenever they straddled the split line).
GHANA_REGIONS = [
    {"region": "Greater Accra", "city": "Accra", "lat": 5.6037, "lon": -0.1870,
     "suburbs": ["Osu", "Labone", "Cantonments", "Airport Residential", "East Legon", "Dzorwulu",
                 "Roman Ridge", "North Legon", "Achimota", "Dansoman", "Kaneshie", "Adenta",
                 "Madina", "Spintex", "Teshie", "Nungua", "La", "Labadi", "Ridge", "Abelemkpe",
                 "Tesano", "Abeka", "Dome", "Haatso", "Ashongman"]},
    {"region": "Ashanti", "city": "Kumasi", "lat": 6.6885, "lon": -1.6244,
     "suburbs": ["Adum", "Bantama", "Asokwa", "Suame", "Tafo", "Ahodwo", "Nhyiaeso",
                 "Asafo", "Kwadaso", "Atonsu"]},
    {"region": "Western", "city": "Sekondi-Takoradi", "lat": 4.9047, "lon": -1.7124,
     "suburbs": ["Effia", "Kwesimintsim", "Anaji", "Sekondi", "Takoradi", "Beach Road",
                 "New Takoradi", "Airport Ridge"]},
    {"region": "Central", "city": "Cape Coast", "lat": 5.1053, "lon": -1.2466,
     "suburbs": ["Pedu", "Abura", "OLA", "University", "Kotokuraba", "Bakaano"]},
    {"region": "Eastern", "city": "Koforidua", "lat": 6.0940, "lon": -0.2591,
     "suburbs": ["Adweso", "Betom", "Effiduase", "Zongo", "Srodae"]},
    {"region": "Volta", "city": "Ho", "lat": 6.6018, "lon": 0.4713,
     "suburbs": ["Bankoe", "Ahoe", "Dome", "Heve", "Klefe"]},
    {"region": "Northern", "city": "Tamale", "lat": 9.4035, "lon": -0.8393,
     "suburbs": ["Sagnarigu", "Lamashegu", "Kalpohin", "Vittin", "Zogbeli"]},
    {"region": "Upper East", "city": "Bolgatanga", "lat": 10.7856, "lon": -0.8514,
     "suburbs": ["Zaare", "Soe", "Kalbeo"]},
    {"region": "Upper West", "city": "Wa", "lat": 10.0601, "lon": -2.5099,
     "suburbs": ["Kambali", "Dobile", "Bamahu"]},
    {"region": "Bono", "city": "Sunyani", "lat": 7.3399, "lon": -2.3268,
     "suburbs": ["Fiapre", "Abesim", "Penkwase"]},
]

STREET_WORDS = [
    "Boundary", "Ring", "Palm", "Liberation", "Independence", "Freedom", "Sunset",
    "Harbour", "Coastal", "Hillview", "Riverside", "Cedar", "Baobab", "Volta", "Oak",
]
STREET_SUFFIXES = ["Road", "Street", "Close", "Avenue", "Crescent"]

ESTATE_NAMES = [
    "Golden Gate Apartments", "Sunset Court", "Palm View Estate", "Silver Star Towers",
    "Regency Heights", "Green Acres", "Lakeside Villas", "Unity Plaza",
]


def _stable_hash(*parts) -> int:
    """A hash that's stable across process restarts (unlike Python's salted
    built-in hash() for str, which varies run to run unless
    PYTHONHASHSEED is fixed) - needed so the same coordinate always
    resolves to the same address."""
    h = 0
    for p in parts:
        for ch in str(p):
            h = (h * 131 + ord(ch)) & 0xFFFFFFFF
    return h


def _pick(options, *seed_parts):
    return options[_stable_hash(*seed_parts) % len(options)]


def _nearest_region(lat, lon):
    return min(GHANA_REGIONS, key=lambda r: (lat - r["lat"]) ** 2 + (lon - r["lon"]) ** 2)


def resolve_address(lat, lon) -> dict | None:
    if lat is None or lon is None:
        return None
    lat, lon = round(float(lat), 6), round(float(lon), 6)

    region = _nearest_region(lat, lon)

    # Suburb: coarse grid (~0.02deg ~ 2km cells), hashed to a name from
    # THIS region's own curated suburb list.
    suburb_cell = (round(lat / 0.02), round(lon / 0.02))
    suburb = _pick(region["suburbs"], "suburb", region["region"], *suburb_cell)

    # Street: finer grid (~0.004deg ~ 400m cells), synthetic name.
    street_cell = (round(lat / 0.004), round(lon / 0.004))
    street = f"{_pick(STREET_WORDS, 'street-word', *street_cell)} {_pick(STREET_SUFFIXES, 'street-suffix', *street_cell)}"

    # Building: exact coordinate -> house number, occasionally an estate name.
    house_no = (_stable_hash("house", lat, lon) % 200) + 1
    if _stable_hash("estate", lat, lon) % 100 < 15:
        estate = _pick(ESTATE_NAMES, "estate-name", lat, lon)
        building = f"{estate}, Unit {house_no}"
    else:
        building = f"House No. {house_no}"

    formatted = f"{building}, {street}, {suburb}, {region['city']}"
    return {
        "region": region["region"],
        "city": region["city"],
        "suburb": suburb,
        "street": street,
        "building": building,
        "formatted": formatted,
    }
