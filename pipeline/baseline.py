"""Layer 1: district partisan baseline from statewide races on current lines (+ legislative lean)."""
import json, shapefile
from common import *

def statewide_margins(ret):
    """D-R margin (points, share of all votes) by (year, race) statewide and by district."""
    g = ret.groupby(["chamber", "year", "race", "district", "party"])["votes"].sum().unstack("party").fillna(0)
    g["total"] = g.sum(axis=1)
    g["margin"] = (g.get("D", 0) - g.get("R", 0)) / g["total"] * 100
    g["d_share"] = g.get("D", 0) / g["total"] * 100
    g["r_share"] = g.get("R", 0) / g["total"] * 100
    g["other_share"] = 100 - g["d_share"] - g["r_share"]
    g = g.reset_index()
    sw = g.groupby(["year", "race"]).apply(lambda x: (x["D"].sum() - x["R"].sum()) / x["total"].sum() * 100).rename("state_margin").reset_index()
    g = g.merge(sw, on=["year", "race"])
    g["lean"] = g["margin"] - g["state_margin"]
    return g

def build(cfg, write=True):
    ret = pd.read_csv(RAW / "tlc/tlc_district_returns.csv")
    turn = pd.read_csv(RAW / "tlc/tlc_district_turnout.csv")
    g = statewide_margins(ret)
    races = cfg["baseline"]["statewide_races"]
    rows = []
    for ch in ["H", "S"]:
        nd = 150 if ch == "H" else 31
        for d in range(1, nd + 1):
            row = dict(chamber=ch, district=d, key=district_key(ch, d))
            wsum, acc = 0.0, 0.0
            for r in races:
                x = g[(g.chamber == ch) & (g.year == r["year"]) & (g.race == r["race"]) & (g.district == d)]
                if len(x):
                    row[f"margin_{r['key']}"] = round(float(x.margin.iloc[0]), 2)
                    row[f"lean_{r['key']}"] = round(float(x.lean.iloc[0]), 2)
                    row[f"state_{r['key']}"] = round(float(x.state_margin.iloc[0]), 2)
                    acc += r["weight"] * float(x.lean.iloc[0]); wsum += r["weight"]
            row["lean_statewide_blend"] = round(acc / wsum, 2)
            t = turn[(turn.chamber == ch) & (turn.year == 2024) & (turn.district == d)]
            row["ssvr_share_2024"] = round(float(t.ssvr_share.iloc[0]), 4) if len(t) else None
            row["turnout_2024"] = int(t.turnout.iloc[0]) if len(t) else None
            row["turnout_2022"] = int(turn[(turn.chamber == ch) & (turn.year == 2022) & (turn.district == d)].turnout.iloc[0])
            rows.append(row)
    df = pd.DataFrame(rows)
    # regions from shapefile centroids
    for ch, p in [("H", RAW / "tlc/shp_h/PLANH2316/PLANH2316"), ("S", RAW / "tlc/shp_s/PLANS2168/PLANS2168")]:
        r = shapefile.Reader(str(p))
        for sr in r.iterShapeRecords():
            pts = sr.shape.points
            cx = sum(q[0] for q in pts) / len(pts); cy = sum(q[1] for q in pts) / len(pts)
            lat, lon = lcc_inverse(cx, cy)
            m = (df.chamber == ch) & (df.district == int(sr.record[0]))
            df.loc[m, "lat"] = round(lat, 4); df.loc[m, "lon"] = round(lon, 4); df.loc[m, "region"] = region_for(lat, lon)
    # legislative lean (optional, from leg_results agent output)
    lr = RAW / "leg_results/leg_races.csv"
    df["lean_legislative"] = np.nan; df["leg_contested_years"] = ""
    if lr.exists():
        L = pd.read_csv(lr)
        L = L[L.year.isin([int(y) for y in cfg["baseline"]["legislative_years"]])]
        L = L[(~L.uncontested.astype(str).str.lower().isin(["true", "1"])) & L.dem_pct.notna() & L.rep_pct.notna() & (L.dem_pct > 0) & (L.rep_pct > 0)]
        # statewide legislative environment that year = vote-weighted mean margin of contested races in that chamber
        for (ch, y), grp in L.groupby(["chamber", "year"]):
            env = float(np.average(grp.margin_d_minus_r, weights=np.ones(len(grp))))
            L.loc[grp.index, "leg_lean"] = grp.margin_d_minus_r - env
        for (ch, d), grp in L.groupby(["chamber", "district"]):
            w = np.array([cfg["baseline"]["legislative_years"][int(y)] for y in grp.year])
            m = (df.chamber == ch) & (df.district == int(d))
            df.loc[m, "lean_legislative"] = round(float(np.average(grp.leg_lean, weights=w)), 2)
            df.loc[m, "leg_contested_years"] = ",".join(str(int(y)) for y in sorted(grp.year))
    wl = cfg["baseline"]["legislative_lean_weight"]
    # Legislative lean is noisy (candidate effects): blend at lower weight, shrunk halfway toward statewide lean first
    adj = 0.5 * df.lean_legislative + 0.5 * df.lean_statewide_blend
    df["lean_final"] = np.where(df.lean_legislative.notna(), (1 - wl) * df.lean_statewide_blend + wl * adj, df.lean_statewide_blend).round(2)
    if write: df.to_csv(PROC / "baseline.csv", index=False)
    ref = cfg["baseline"]["reference_race"]
    meta = dict(reference_margin_pres_2024=round(float(df[f"state_{ref}"].iloc[0]), 2),
                statewide_margins={k: round(float(df[f"state_{k}"].iloc[0]), 2) for k in [r["key"] for r in races]})
    if write: (PROC / "baseline_meta.json").write_text(json.dumps(meta, indent=1))
    if not write: return df, meta
    print(df[["key", "lean_statewide_blend", "lean_legislative", "lean_final", "region"]].head(8).to_string()); print(meta)
    print(df.region.value_counts().to_string())

def main():
    build(load_config())

if __name__ == "__main__":
    main()
