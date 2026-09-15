#!/usr/bin/env python3
"""
PRECIPITATION / COLD backtest, 2019-2025 (Jack 2026-09-15: "lets do it").
The shipped weather layer docks wind only. Does rain / snow / cold move
player scoring beyond the Vegas line? pbp `weather` string per game (outdoor
games only; ~94% coverage): precip keywords (rain, snow, shower, drizzle,
thunder, sleet, flurr), temperature parsed from "Temp: NN F".
Flags: rain (precip word, no snow), snow, any_precip, cold (<= 32F), freezing
(<= 20F), also wind >= 15 as the shipped reference.
Grading: actual / shipped by flag and position (shipped = base x Vegas x FPA,
i.e. AFTER Vegas has priced the weather), and the same on base x FPA only (is
it already in the line?); LOYO multipliers on flagged rows per position.
Log: precip_backtest.log
"""
import numpy as np
import re
from bt_common import iter_samples, to_arrays, load_games, bucket_table, loyo_flag, loyo, mse, YEARS, POS4

def parse(w):
    if not w: return None
    lw = w.lower()
    snow = bool(re.search(r"snow|flurr|sleet|wintry", lw))
    rain = bool(re.search(r"rain|shower|drizzle|thunder|storm", lw)) and not snow
    mt = re.search(r"temp:\s*(-?\d+)", lw); temp = int(mt.group(1)) if mt else None
    mw = re.search(r"wind:\s*[a-z]*\s*(\d+)", lw); wind = int(mw.group(1)) if mw else None
    return {"rain": rain, "snow": snow, "temp": temp, "wind": wind}

def main():
    S = iter_samples(POS4)
    A = to_arrays(S)
    years = sorted(set(A["year"]))
    n = len(S)
    F = {k: np.zeros(n, bool) for k in ("outdoor", "rain", "snow", "any_precip", "cold", "freezing", "wind15", "dry_mild")}
    covered = 0
    for i, s in enumerate(S):
        g = load_games(s["year"]).get((s["team"], s["wk"]))
        if not g: continue
        roof = str(g["roof"]).lower()
        if roof not in ("outdoors", "open"): continue
        F["outdoor"][i] = True
        w = parse(g["weather"])
        if not w: continue
        covered += 1
        F["rain"][i] = w["rain"]; F["snow"][i] = w["snow"]; F["any_precip"][i] = w["rain"] or w["snow"]
        F["cold"][i] = w["temp"] is not None and w["temp"] <= 32
        F["freezing"][i] = w["temp"] is not None and w["temp"] <= 20
        F["wind15"][i] = w["wind"] is not None and w["wind"] >= 15
        F["dry_mild"][i] = (not (w["rain"] or w["snow"])) and (w["temp"] is None or w["temp"] > 45) and (w["wind"] is None or w["wind"] < 10)
    print(f"\n{n} player-weeks | outdoor {F['outdoor'].sum()} | weather string parsed {covered} | rain {F['rain'].sum()} snow {F['snow'].sum()} cold {F['cold'].sum()} freezing {F['freezing'].sum()} wind15 {F['wind15'].sum()}")
    bucket_table(A, [(k, F[k]) for k in ("rain", "snow", "any_precip", "cold", "freezing", "wind15", "dry_mild")], "1. actual / shipped (AFTER Vegas)")
    # same ratios without the Vegas multiplier: is the line already pricing the weather?
    A2 = dict(A); A2["shipped"] = A["base"] * A["fpa"]
    bucket_table(A2, [(k, F[k]) for k in ("rain", "snow", "any_precip", "cold", "wind15")], "1b. actual / (base x FPA, NO Vegas) - if these are lower than 1., Vegas is pricing it")
    print("\n=== 2. LOYO multipliers on flagged rows, shipped base (grid[0] = shipped) ===")
    grid = (1.0, 0.97, 0.94, 0.91, 0.88, 1.03)
    for k in ("rain", "snow", "any_precip", "cold", "freezing"):
        loyo_flag(A, years, F[k], k, grid)
        for p in POS4:
            loyo_flag(A, years, F[k], f"   {k} {p}", grid, pos=p)

if __name__ == "__main__":
    main()
