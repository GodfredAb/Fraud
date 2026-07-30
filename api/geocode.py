"""
geocode.py (api/)
------------------
Resolves a (lat, lon) pair to a human-readable place - Region -> City ->
Suburb -> Street -> Building - WITHOUT calling a real reverse-geocoding
API. See design.md at the project root for why: every coordinate in this
project is synthetic (database/seed_generator.py jitters points around
Accra), and feeding a fake coordinate to a real geocoder returns the
address of a REAL building that has nothing to do with the fictional
subscriber "standing" there - not a rounding error, actively misleading.

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

CENTER_LAT, CENTER_LON = 5.6037, -0.1870  # database/seed_generator.py's Accra center

SUBURBS = [
    "Osu", "Labone", "Cantonments", "Airport Residential", "East Legon", "Dzorwulu",
    "Roman Ridge", "North Legon", "Achimota", "Dansoman", "Kaneshie", "Adenta",
    "Madina", "Spintex", "Teshie", "Nungua", "La", "Labadi", "Ridge", "Abelemkpe",
    "Tesano", "Abeka", "Dome", "Haatso", "Ashongman",
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


def resolve_address(lat, lon) -> dict | None:
    if lat is None or lon is None:
        return None
    lat, lon = round(float(lat), 6), round(float(lon), 6)

    # City: mostly "Accra" (database/seed_generator.py's whole jitter box is
    # only +-0.15deg / ~17km, well inside real Accra's actual extent), with
    # Tema/Kasoa reserved for the box's outer edge - and even then decided by
    # a stable grid hash, not a raw east/west sign: a sign flip right at
    # dlon==0 would put two points a few hundred meters apart in different
    # "cities" whenever they straddle the center meridian, which is exactly
    # where most of the jittered data actually clusters.
    dist_deg = math.hypot(lat - CENTER_LAT, lon - CENTER_LON)
    if dist_deg < 0.10:
        city = "Accra"
    else:
        city_cell = (round(lat / 0.06), round(lon / 0.06))
        city = _pick(["Tema", "Kasoa"], "city", *city_cell)

    # Suburb: coarse grid (~0.02deg ~ 2km cells), hashed to a curated name.
    suburb_cell = (round(lat / 0.02), round(lon / 0.02))
    suburb = _pick(SUBURBS, "suburb", *suburb_cell)

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

    formatted = f"{building}, {street}, {suburb}, {city}"
    return {
        "region": "Greater Accra",
        "city": city,
        "suburb": suburb,
        "street": street,
        "building": building,
        "formatted": formatted,
    }
