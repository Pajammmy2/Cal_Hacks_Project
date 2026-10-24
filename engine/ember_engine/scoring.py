"""Refuge score terms (spec "Scoring"). score = 40 f_heat + 20 f_area + 20 f_access + 10 f_shelter + 10 f_water."""

HEAT_FLOOR_M = 15.0        # radiant-heat floor: d_fuel below this is excluded outright
HEAT_FULL_M = 45.0         # ~150 ft
AREA_ZERO_M2 = 2000.0
AREA_FULL_M2 = 10000.0
INNER_BUFFER_M = 10.0
WEIGHTS = {"f_heat": 40, "f_area": 20, "f_access": 20, "f_shelter": 10, "f_water": 10}
VISION_PENALTY_PER_RING = 10.0
VISION_PENALTY_CAP = 30.0


def _ramp(x, lo, hi):
    if x <= lo:
        return 0.0
    if x >= hi:
        return 1.0
    return (x - lo) / (hi - lo)


def f_heat(d_fuel_m):
    """0 below 15 m, linear to 1 at 45 m, capped."""
    return _ramp(d_fuel_m, HEAT_FLOOR_M, HEAT_FULL_M)


def excluded(d_fuel_m):
    return d_fuel_m < HEAT_FLOOR_M


def f_area(a_clear_m2):
    """0 below 2,000 m2, linear to 1 at 10,000 m2."""
    return _ramp(a_clear_m2, AREA_ZERO_M2, AREA_FULL_M2)


def base_score(terms):
    return round(sum(w * float(terms[k]) for k, w in WEIGHTS.items()), 1)


def make_terms(d_fuel_m, a_clear_m2, f_access, f_shelter, f_water):
    t = {
        "d_fuel_m": round(float(d_fuel_m), 1),
        "f_heat": round(f_heat(d_fuel_m), 4),
        "A_clear_m2": round(float(a_clear_m2), 1),
        "f_area": round(f_area(a_clear_m2), 4),
        "f_access": float(f_access),
        "f_shelter": float(f_shelter),
        "f_water": float(f_water),
    }
    t["base_score"] = base_score(t)
    t["vision_penalty"] = 0.0
    return t


def vision_penalty(fuel_ring):
    return min(VISION_PENALTY_CAP, VISION_PENALTY_PER_RING * max(0, int(fuel_ring)))
