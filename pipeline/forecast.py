"""Layers 2-4 and the Monte Carlo simulation for the Texas Legislature 2026 Forecast.
Usage: forecast.py [--as-of YYYY-MM-DD]  (all weights come from config/model_config.yaml)
"""
import json, re, sys, unicodedata, datetime
from common import *

STATUS = []   # data-availability notes surfaced on the methodology page
def note(msg):
    STATUS.append(msg); print("NOTE:", msg)

def read_csv_opt(path, required_cols=()):
    p = RAW / path
    if not p.exists() or p.stat().st_size == 0:
        note(f"Missing input {path}; layer that needs it runs without it."); return None
    df = pd.read_csv(p, dtype=str).fillna("")
    for c in required_cols:
        if c not in df.columns: df[c] = ""
    return df

def norm_name(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    s = re.sub(r"\(.*?\)|\".*?\"|'.*?'", " ", s)        # drop nicknames/titles in quotes/parens
    s = re.sub(r"\b(jr|sr|ii|iii|iv|dr|mr|mrs|ms|the honorable|hon)\b\.?", " ", s.lower())
    s = re.sub(r"[^a-z ]", " ", s)
    return [t for t in s.split() if t]

def last_first(tokens):
    return (tokens[-1], tokens[0]) if tokens else ("", "")

def tf(x): return str(x).strip().lower() in ("true", "1", "yes", "y")
def num(x, default=None):
    try:
        v = float(str(x).replace(",", "").replace("$", "").replace("%", "").strip()); return v if np.isfinite(v) else default
    except Exception: return default

# ----------------------------------------------------------------------------- environment
def polling_average(cfg, polls, ratings, race, as_of, dem_col="dem_pct", rep_col="rep_pct"):
    """Weighted average margin (D-R) for one race code. Returns (margin, n_polls, eff_n, rows)."""
    env = cfg["environment"]
    P = polls[polls.race == race].copy()
    if P.empty: return None, 0, 0.0, []
    P["end"] = pd.to_datetime(P.end_date, errors="coerce")
    P = P[P.end.notna() & (P.end <= pd.Timestamp(as_of))]
    P["age"] = (pd.Timestamp(as_of) - P.end).dt.days
    P = P[P.age <= env["max_poll_age_days"]]
    if P.empty: return None, 0, 0.0, []
    rw = env["pollster_rating_weights"]
    def rating_weight(pollster):
        if ratings is None: return rw["unrated"]
        pn = " ".join(norm_name(pollster)); pn = pn.replace("university", "").replace("college", "").strip()
        if not pn: return rw["unrated"]
        first = pn.split()[0]
        m = ratings[ratings.pollster_norm.apply(lambda x: pn in x or (x in pn and len(x) > 3) or (len(first) > 4 and first in x.split()))]
        if m.empty: return rw["unrated"]
        g = m.iloc[0].grade
        gv = num(g)
        if gv is not None:  # numeric 0-3 scale (538 2024 ratings): map to weight
            return rw["numeric_floor"] + (1 - rw["numeric_floor"]) * max(0.0, min(gv, 3.0)) / 3.0
        g = str(g).strip(); return rw.get(g, rw.get(g[:1], rw["unrated"]))
    rows = []
    for _, r in P.iterrows():
        d, rp = num(r.get(dem_col)), num(r.get(rep_col))
        if d is None or rp is None: continue
        margin = d - rp
        internal = tf(r.get("internal")) or str(r.get("partisan", "")).strip() in ("D", "R")
        if internal:
            side = str(r.get("partisan", "")).strip() or ("D" if margin > 0 else "R")
            margin += -env["partisan_poll_shift"] if side == "D" else env["partisan_poll_shift"]
        n = num(r.get("sample_size"), 500) or 500
        w = (0.5 ** (r.age / env["poll_half_life_days"])) * np.sqrt(min(n, env["sample_size_cap"]) / env["sample_size_cap"]) * rating_weight(r.pollster)
        if internal: w *= env["partisan_poll_weight"]
        rows.append(dict(pollster=r.pollster, end_date=str(r.end.date()), sample_size=int(n), population=r.get("population", ""), dem=d, rep=rp, margin=round(margin, 1), internal=internal, weight=round(float(w), 3), url=r.get("source_url", "")))
    if not rows: return None, 0, 0.0, []
    W = np.array([x["weight"] for x in rows]); M = np.array([x["margin"] for x in rows])
    return float(np.sum(W * M) / W.sum()), len(rows), float(W.sum()), rows

def environment_layer(cfg, polls, ratings, as_of, ref_margin, year=2026, race_suffix="", out_party_is_dem=True):
    env = cfg["environment"]
    comps, acc, wsum, total_polls = [], 0.0, 0.0, 0
    for ind, spec in env["indicators"].items():
        code = ind + race_suffix
        if ind == "tx_abbott_approval":
            m, n, effn, rows = polling_average(cfg, polls, ratings, code, as_of, "approve_pct", "disapprove_pct") if polls is not None else (None, 0, 0, [])
            if m is None: comps.append(dict(indicator=ind, polls=0, implied_margin=None, weight=0)); continue
            implied = m * spec["net_to_margin"] + env["indicators"]["tx_gov"]["adjust"]   # treat as a governor-race proxy
        else:
            m, n, effn, rows = polling_average(cfg, polls, ratings, code, as_of) if polls is not None else (None, 0, 0, [])
            if m is None: comps.append(dict(indicator=ind, polls=0, implied_margin=None, weight=0)); continue
            adj = spec["adjust"]
            implied = m + (env["texas_lean_vs_nation"] if adj == "texas_lean" else adj)
        w = spec["weight"] * min(1.0, effn / 1.5)   # thin indicators get down-weighted
        comps.append(dict(indicator=ind, polls=n, raw_average=round(m, 1), implied_margin=round(implied, 1), weight=round(w, 3), rows=rows))
        acc += w * implied; wsum += w; total_polls += n
    poll_margin = acc / wsum if wsum > 0 else None
    mp = env["midterm_prior"]
    prior = ref_margin + (mp["swing_toward_out_party"] if out_party_is_dem else -mp["swing_toward_out_party"])
    pw = mp["weight_when_polls_full"]
    if total_polls < env["min_polls_for_full_weight"]:
        pw = pw + (1 - pw) * (1 - total_polls / env["min_polls_for_full_weight"])
    if poll_margin is None: pw = 1.0
    expected = pw * prior + (1 - pw) * (poll_margin if poll_margin is not None else prior)
    return dict(year=year, as_of=str(as_of), reference_margin=ref_margin, poll_based_margin=None if poll_margin is None else round(poll_margin, 2),
                midterm_prior_margin=round(prior, 2), prior_weight=round(pw, 3), expected_statewide_margin=round(expected, 2),
                swing_vs_reference=round(expected - ref_margin, 2), total_polls=total_polls, components=comps)

# ----------------------------------------------------------------------------- candidates
def build_seats(cfg, base, cands, dists, seats_up, leg_results, leg_races, finance, chamber, year=2026, holders=None, specials=None, env_hint=0.0):
    C = cfg["candidate"]; ch = chamber; chname = "house" if ch == "H" else "senate"
    rows = []
    fin = None
    if finance is not None:
        office = "State Representative" if ch == "H" else "State Senator"
        fin = finance[finance.office_sought.str.contains(office, case=False, na=False)].copy()
        fin["dist"] = fin.district.apply(lambda x: int(num(x, 0) or 0))
        fin["contrib"] = fin.total_contributions_2025_2026.apply(lambda x: num(x, 0.0) or 0.0)
        fin["toks"] = fin.filer_name.apply(norm_name)
    for _, b in base[base.chamber == ch].iterrows():
        d = int(b.district); key = b.key
        up = (seats_up is None) or (d in seats_up)
        row = dict(key=key, chamber=ch, district=d, region=b.region, lean=b.lean_final, lean_statewide=b.lean_statewide_blend,
                   lean_legislative=b.lean_legislative if pd.notna(b.lean_legislative) else None, ssvr=b.ssvr_share_2024, up=up,
                   leg_contested_years=str(b.leg_contested_years) if pd.notna(b.leg_contested_years) else "")
        for col in base.columns:
            if col.startswith(("margin_", "lean_")) and col not in row and pd.notna(b[col]): row[col] = float(b[col])
        dc = cands[(cands.chamber == ch) & (cands.district.astype(int) == d)] if cands is not None else None
        info = dists[(dists.chamber == ch) & (dists.district.astype(int) == d)] if dists is not None else None
        info = info.iloc[0] if info is not None and len(info) else None
        dem = [c for _, c in dc.iterrows() if c.party == "D"] if dc is not None else []
        rep = [c for _, c in dc.iterrows() if c.party == "R"] if dc is not None else []
        oth = [c for _, c in dc.iterrows() if c.party not in ("D", "R")] if dc is not None else []
        row.update(dem_name=dem[0].candidate_name if dem else "", rep_name=rep[0].candidate_name if rep else "",
                   other_names="; ".join(f"{c.candidate_name} ({c.party_raw or c.party})" for c in oth),
                   dem_incumbent=any(tf(c.incumbent) for c in dem), rep_incumbent=any(tf(c.incumbent) for c in rep),
                   incumbent_party=(info.incumbent_party if info is not None else ""), open_seat=tf(info.open_seat) if info is not None else not (any(tf(c.incumbent) for c in dem + rep)),
                   notes=(info.notes if info is not None else ""))
        if not up:
            row.update(contest="not_up")
            if holders and str(d) in holders: row["incumbent_party"] = holders[str(d)]
            rows.append(row); continue
        if dc is None or len(dc) == 0:
            row.update(contest="no_candidate_data"); note(f"{key}: no candidate data"); rows.append(row); continue
        # --- adjustments (points toward D) ---
        adj = {}
        bonus = C["incumbency_bonus"][chname]
        if row["dem_incumbent"] and not row["rep_incumbent"]: adj["incumbency"] = bonus
        elif row["rep_incumbent"] and not row["dem_incumbent"]: adj["incumbency"] = -bonus
        else: adj["incumbency"] = 0.0
        # freshman discount: incumbent whose first win in this seat was the last election
        if leg_results is not None and adj["incumbency"] != 0:
            inc = (dem if row["dem_incumbent"] else rep)[0]
            hist = leg_results[(leg_results.chamber == ch) & (leg_results.district.astype(int) == d) & (leg_results.year.astype(int) < year)]
            toks = norm_name(inc.candidate_name)
            ran_years = sorted({int(y) for y, n in zip(hist.year, hist.candidate_name) if last_first(norm_name(n))[0] == toks[-1]}) if toks else []
            if len(ran_years) <= 1: adj["incumbency"] *= (1 - C["freshman_incumbent_discount"])
            row["incumbent_prior_runs_here"] = len(ran_years)
        # prior nominee bonus & performance carryover
        adj["prior_performance"] = 0.0; adj["prior_nominee"] = 0.0
        if leg_results is not None and leg_races is not None:
            for side, lst, sign in (("D", dem, 1), ("R", rep, -1)):
                if not lst: continue
                toks = norm_name(lst[0].candidate_name)
                if not toks: continue
                hist = leg_results[(leg_results.chamber == ch) & (leg_results.district.astype(int) == d) & (leg_results.year.astype(int) < year) & (leg_results.party == side)]
                hist = hist[[last_first(norm_name(n))[0] == toks[-1] for n in hist.candidate_name]]
                if hist.empty: continue
                if not tf(lst[0].incumbent): adj["prior_nominee"] += sign * C["prior_nominee_bonus"]
                # over/under-performance vs that year's expectation (lean + statewide legislative env that year)
                y = int(hist.year.astype(int).max())
                rr = leg_races[(leg_races.chamber == ch) & (leg_races.district.astype(int) == d) & (leg_races.year.astype(int) == y)]
                if rr.empty or tf(rr.iloc[0].uncontested): continue
                m = num(rr.iloc[0].margin_d_minus_r)
                env_y = leg_races[(leg_races.chamber == ch) & (leg_races.year.astype(int) == y) & (~leg_races.uncontested.apply(tf))].margin_d_minus_r.apply(num).mean()
                if m is None or env_y is None or pd.isna(env_y): continue
                over = m - (b.lean_statewide_blend + env_y)
                # strip the generic incumbency bonus if they were an incumbent then, so we don't double count
                if str(rr.iloc[0].get("incumbent_party_if_known", "")).strip() == side: over -= sign * bonus
                adj["prior_performance"] += C["performance_carryover"] * float(np.clip(over, -12, 12)) * (1 if side == "D" else 1)  # 'over' already signed D-R
        # 2025-26 special election winner now running: carry part of the special over-performance
        adj["special_election"] = 0.0
        for sp in (specials or []):
            if int(sp.get("district", -1) or -1) != d or sp.get("status") not in ("decided", None) or not sp.get("winner_party"): continue
            wp = sp["winner_party"][:1].upper(); nm = (dem if wp == "D" else rep)
            if not nm or last_first(norm_name(nm[0].candidate_name))[0] != last_first(norm_name(sp.get("winner", "")))[0]: continue
            res = None
            for rd in sp.get("rounds", []):
                if "runoff" in rd.get("round", "").lower() or res is None: res = rd.get("results")
            if not res: continue
            dp = sum(float(x.get("pct", 0) or 0) for x in res if str(x.get("party", ""))[:1].upper() == "D"); rp = sum(float(x.get("pct", 0) or 0) for x in res if str(x.get("party", ""))[:1].upper() == "R")
            over = (dp - rp) - (b.lean_statewide_blend + env_hint)
            adj["special_election"] = C["special_election_carryover"] * float(np.clip(over, -C["special_election_cap_points"], C["special_election_cap_points"]))
            row["special_election"] = dict(date=sp.get("election_date"), runoff=sp.get("runoff_date"), dem_pct=dp, rep_pct=rp, winner=sp.get("winner"))
        # finance
        adj["finance"] = 0.0; row["dem_receipts"] = None; row["rep_receipts"] = None
        if fin is not None and dem and rep:
            def receipts(c):
                toks = norm_name(c.candidate_name)
                if not toks: return None
                m = fin[(fin.dist == d) & fin.toks.apply(lambda t: bool(t) and t[0] == toks[-1])]
                if m.empty:  # try first-name match within district
                    m = fin[(fin.dist == d) & fin.toks.apply(lambda t: bool(t) and len(t) > 1 and t[1] == toks[0] and t[0][:4] == toks[-1][:4])]
                if m.empty:  # statewide search by last+first (district blank in TEC filing)
                    m = fin[fin.toks.apply(lambda t: len(t) > 1 and t[0] == toks[-1] and t[1] == toks[0])]
                return float(m.contrib.max()) if not m.empty else None
            dr, rr_ = receipts(dem[0]), receipts(rep[0])
            row["dem_receipts"], row["rep_receipts"] = dr, rr_
            fl = C["finance"]["floor_dollars"]
            d_eff = (dr if dr is not None else 0.0) + fl; r_eff = (rr_ if rr_ is not None else 0.0) + fl
            adj["finance"] = float(np.clip(C["finance"]["points_per_log_ratio"] * np.log(d_eff / r_eff), -C["finance"]["cap_points"], C["finance"]["cap_points"]))
        row["adj"] = {k: round(v, 2) for k, v in adj.items()}
        row["adj_total"] = round(sum(adj.values()), 2)
        # contest type
        if dem and rep: row["contest"] = "D_vs_R"
        elif dem and oth: row["contest"] = "D_vs_other"
        elif rep and oth: row["contest"] = "R_vs_other"
        elif dem or rep: row["contest"] = "uncontested"
        else: row["contest"] = "others_only"
        # recent contested result on these lines?
        row["recent_contested"] = False
        if leg_races is not None:
            rr = leg_races[(leg_races.chamber == ch) & (leg_races.district.astype(int) == d) & (leg_races.year.astype(int).isin([2022, 2024])) & (~leg_races.uncontested.apply(tf))]
            row["recent_contested"] = len(rr) > 0
        rows.append(row)
    return rows

# ----------------------------------------------------------------------------- district polls & ratings
RATING_RE = re.compile(r"(safe|likely|lean|tilt|toss)", re.I)
def apply_layer4(cfg, seats, ratings, dpolls, as_of, disabled=()):
    L = cfg["district_polls_and_ratings"]
    for s in seats:
        s["rating_rows"] = []; s["poll_rows"] = []; s["ratings_shift"] = 0.0; s["poll_shift"] = 0.0; s["extra_sd"] = 0.0
        if s.get("contest") not in ("D_vs_R",): continue
        mu0 = s["mu_model"]
        # ratings
        if ratings is not None and "ratings" not in disabled:
            R = ratings[(ratings.chamber == s["chamber"]) & (ratings.district.astype(int) == s["district"])]
            tw, acc, pull = 0.0, 0.0, 0.0
            for _, r in R.iterrows():
                src = r.source; std = str(r.rating_std).strip()
                if f"ratings_{src}" in disabled or ("ratings_other" in disabled and src not in ("State Navigate", "CNalysis", "Ballotpedia")): continue
                w = L["rating_source_weights"].get(src, L["rating_source_weights"]["Other"])
                if std.startswith("Target"):
                    pull += L["target_list_pull_to_zero_weight"]; s["extra_sd"] = max(s["extra_sd"], L["target_list_extra_sd"])
                    s["rating_rows"].append(dict(source=src, rating=std, implied=None, weight=L["target_list_pull_to_zero_weight"], url=r.get("source_url", "")))
                    continue
                m = RATING_RE.search(std)
                if not m: continue
                cat = m.group(1).title(); cat = "Toss-up" if cat == "Toss" else cat
                mag = L["rating_implied_margin"][cat]
                implied = 0.0 if cat == "Toss-up" else (mag if std.strip().endswith("D") else -mag)
                tw += w; acc += w * implied
                s["rating_rows"].append(dict(source=src, rating=std, implied=implied, weight=w, url=r.get("source_url", "")))
            tw = min(tw, L["ratings_total_weight_cap"])
            shift = 0.0
            if tw > 0: shift = tw * ((acc / sum(x["weight"] for x in s["rating_rows"] if x["implied"] is not None)) - mu0)
            if pull > 0: shift += min(pull, 0.15) * (0 - mu0)
            s["ratings_shift"] = float(np.clip(shift, -L["ratings_max_shift_points"], L["ratings_max_shift_points"]))
        # district polls
        if dpolls is not None and "district_polls" not in disabled:
            P = dpolls[(dpolls.chamber == s["chamber"]) & (dpolls.district.astype(int) == s["district"])].copy()
            P["end"] = pd.to_datetime(P.end_date, errors="coerce"); P = P[P.end.notna() & (P.end <= pd.Timestamp(as_of))]
            if len(P):
                acc, wsum = 0.0, 0.0
                for _, p in P.iterrows():
                    d, r = num(p.dem_pct), num(p.rep_pct)
                    if d is None or r is None: continue
                    m = d - r; internal = tf(p.internal); w = 0.5 ** (((pd.Timestamp(as_of) - p.end).days) / cfg["environment"]["poll_half_life_days"])
                    if internal:
                        w *= L["internal_poll_weight"]; m += -L["internal_poll_shift"] if m > 0 else L["internal_poll_shift"]
                    acc += w * m; wsum += w
                    s["poll_rows"].append(dict(pollster=p.pollster, sponsor=p.get("sponsor", ""), end_date=str(p.end.date()), n=p.get("sample_size", ""), dem=d, rep=r, internal=internal, weight=round(w, 3), url=p.get("source_url", "")))
                if wsum > 0:
                    pw = min(L["district_poll_weight_cap"], L["district_poll_weight_per_poll"] * wsum)
                    s["poll_shift"] = pw * (acc / wsum - (mu0 + s["ratings_shift"]))
    return seats

# ----------------------------------------------------------------------------- compose + simulate
def compose(cfg, seats, env_margin, disabled=()):
    C = cfg["candidate"]; S = cfg["simulation"]
    for s in seats:
        if s.get("contest") in (None, "not_up", "no_candidate_data"): continue
        adj = dict(s["adj"])
        if "finance" in disabled: adj["finance"] = 0.0
        s["adj_used"] = adj
        s["mu_model"] = s["lean"] + env_margin + sum(adj.values())
    return seats

def finalize(cfg, seats):
    S = cfg["simulation"]
    for s in seats:
        if s.get("contest") in (None, "not_up", "no_candidate_data"): continue
        s["mu"] = s["mu_model"] + s["ratings_shift"] + s["poll_shift"]
        sd = S["district_error_sd"]["house" if s["chamber"] == "H" else "senate"]
        if s["open_seat"]: sd = np.hypot(sd, S["open_seat_extra_sd"])
        if not s.get("recent_contested"): sd = np.hypot(sd, S["no_recent_result_extra_sd"])
        if s["extra_sd"]: sd = np.hypot(sd, s["extra_sd"])
        s["sd_district"] = float(sd)
        # one-major-party races: model the major vs the strongest minor candidate explicitly
        if s["contest"] in ("D_vs_other", "R_vs_other"):
            tp = cfg["candidate"]["third_party"]
            pD = 50 + s["mu"] / 2           # expected two-party D share if both majors ran
            if s["contest"] == "R_vs_other":
                ch_share = tp["orphan_capture"] * pD + tp["base_share"]; s["mu_major"] = (100 - ch_share) - ch_share; s["major"] = "R"
            else:
                ch_share = tp["orphan_capture"] * (100 - pD) + tp["base_share"]; s["mu_major"] = (100 - ch_share) - ch_share; s["major"] = "D"
            s["sd_district"] = float(np.hypot(sd, tp["extra_sd_when_major_absent"]))
    return seats

def simulate(cfg, seats, n, seed, chamber):
    S = cfg["simulation"]; rng = np.random.default_rng(seed)
    sim_seats = [s for s in seats if s["chamber"] == chamber]
    regions = sorted({s["region"] for s in sim_seats})
    ssvr = np.array([s["ssvr"] if s.get("ssvr") is not None else 0.26 for s in sim_seats]); load_h = (ssvr - ssvr.mean()) / 0.2
    t = rng.standard_t(S["statewide_error"]["student_t_df"], n) * S["statewide_error"]["sd"] * np.sqrt((S["statewide_error"]["student_t_df"] - 2) / S["statewide_error"]["student_t_df"])
    reg = rng.normal(0, S["regional_error_sd"], (n, len(regions)))
    hisp = rng.normal(0, S["hispanic_factor_sd"], n)
    D = len(sim_seats); margins = np.zeros((n, D), dtype=np.float32)   # D-R margin; +-100 for fixed seats
    winner = np.zeros((n, D), dtype=np.int8)   # 1 = D, -1 = R, 0 = other
    for j, s in enumerate(sim_seats):
        c = s.get("contest")
        if c == "not_up" or c == "no_candidate_data":
            p = s.get("incumbent_party", "") or s.get("holder", "")
            margins[:, j] = 100 if p == "D" else (-100 if p == "R" else 0); winner[:, j] = 1 if p == "D" else (-1 if p == "R" else 0); continue
        if c == "uncontested":
            p = "D" if s["dem_name"] else "R"
            margins[:, j] = 100 if p == "D" else -100; winner[:, j] = 1 if p == "D" else -1; continue
        if c == "others_only":
            winner[:, j] = 0; continue
        shared = t + reg[:, regions.index(s["region"])] + hisp * load_h[j]
        eps = rng.normal(0, s["sd_district"], n)
        if c == "D_vs_R":
            m = s["mu"] + shared + eps
            margins[:, j] = m; winner[:, j] = np.where(m > 0, 1, -1)
        else:
            sign = 1 if s["major"] == "D" else -1
            m = s["mu_major"] + sign * cfg["candidate"]["third_party"]["orphan_capture"] * shared + eps
            margins[:, j] = np.where(m > 0, sign * 100, 0) if False else sign * m   # D-R-style scale for sorting
            winner[:, j] = np.where(m > 0, sign, 0)
    return sim_seats, margins, winner, regions

def summarize(cfg, chamber, sim_seats, margins, winner, current):
    maj = cfg["chambers"]["house" if chamber == "H" else "senate"]["majority"]
    n = margins.shape[0]
    dseats = (winner == 1).sum(axis=1); rseats = (winner == -1).sum(axis=1)
    p_d = float((dseats >= maj).mean()); p_r = float((rseats >= maj).mean())
    hist = np.bincount(dseats, minlength=cfg["chambers"]["house" if chamber == "H" else "senate"]["seats"] + 1)
    # tipping point: seat at rank `maj` when sorted most- to least-Democratic
    order = np.argsort(-margins, axis=1)
    tip = order[:, maj - 1]
    tip_counts = np.bincount(tip, minlength=len(sim_seats)) / n
    out = []
    for j, s in enumerate(sim_seats):
        pd_ = float((winner[:, j] == 1).mean()); pr = float((winner[:, j] == -1).mean()); po = 1 - pd_ - pr
        m = margins[:, j]
        row = dict(key=s["key"], chamber=chamber, district=s["district"], p_dem=round(pd_, 4), p_rep=round(pr, 4), p_other=round(max(po, 0), 4),
                   tipping_prob=round(float(tip_counts[j]), 4))
        if s.get("contest") in ("D_vs_R",):
            row.update(margin_mean=round(float(m.mean()), 2), margin_p10=round(float(np.percentile(m, 10)), 2), margin_p90=round(float(np.percentile(m, 90)), 2))
        elif s.get("contest") in ("D_vs_other", "R_vs_other"):
            mm = m * (1 if s["major"] == "D" else -1)
            row.update(margin_mean=round(float(mm.mean()), 2), margin_p10=round(float(np.percentile(mm, 10)), 2), margin_p90=round(float(np.percentile(mm, 90)), 2), margin_is_major_vs_other=True)
        out.append(row)
    summ = dict(chamber=chamber, majority=maj, p_dem_control=round(p_d, 4), p_rep_control=round(p_r, 4), p_no_majority=round(1 - p_d - p_r, 4),
                dem_seats_mean=round(float(dseats.mean()), 2), dem_seats_p10=int(np.percentile(dseats, 10)), dem_seats_p90=int(np.percentile(dseats, 90)),
                dem_seats_median=int(np.median(dseats)), rep_seats_mean=round(float(rseats.mean()), 2), seat_distribution=hist.tolist(), current=current)
    return summ, out

def load_all(cfg):
    base = pd.read_csv(PROC / "baseline.csv")
    meta = json.loads((PROC / "baseline_meta.json").read_text())
    hc = read_csv_opt("ballotpedia/house_candidates_2026.csv"); sc = read_csv_opt("ballotpedia/senate_candidates_2026.csv")
    cands = None
    if hc is not None: hc["chamber"] = "H"
    if sc is not None: sc["chamber"] = "S"
    parts = [x for x in (hc, sc) if x is not None]
    if parts:
        cands = pd.concat(parts, ignore_index=True)
        for col in ("withdrew", "did_not_make_ballot"):
            if col in cands.columns: cands = cands[~cands[col].apply(tf)]
    hd = read_csv_opt("ballotpedia/house_districts_2026.csv"); sd = read_csv_opt("ballotpedia/senate_districts_2026.csv")
    if hd is not None: hd["chamber"] = "H"
    if sd is not None: sd["chamber"] = "S"
    parts = [x for x in (hd, sd) if x is not None]
    dists = pd.concat(parts, ignore_index=True) if parts else None
    su = RAW / "ballotpedia/senate_seats_up_2026.json"
    seats_up = set(json.loads(su.read_text())["districts_up"]) if su.exists() else None
    if seats_up is None: note("Senate seats-up list missing; Senate forecast skipped")
    ctrl = {}
    for ch, f in (("H", "house_control_2026.json"), ("S", "senate_control_2026.json")):
        p = RAW / "ballotpedia" / f
        ctrl[ch] = json.loads(p.read_text()) if p.exists() else None
    leg_results = read_csv_opt("leg_results/leg_results.csv"); leg_races = read_csv_opt("leg_results/leg_races.csv", ["uncontested", "incumbent_party_if_known"])
    finance = read_csv_opt("tec/candidate_finance_2026.csv")
    polls = read_csv_opt("polls/polls.csv"); pr = read_csv_opt("polls/pollster_ratings.csv")
    if pr is not None:
        pcol = next((c for c in pr.columns if "pollster" in c.lower()), pr.columns[0]); gcol = next((c for c in pr.columns if "grade" in c.lower() or "rating" in c.lower()), None)
        pr = pd.DataFrame(dict(pollster_norm=pr[pcol].apply(lambda x: " ".join(norm_name(x)).replace("university", "").replace("college", "").strip()), grade=pr[gcol] if gcol else "unrated"))
    ratings = read_csv_opt("ratings/ratings.csv"); dpolls = read_csv_opt("ratings/district_polls.csv")
    return dict(base=base, meta=meta, cands=cands, dists=dists, seats_up=seats_up, ctrl=ctrl, leg_results=leg_results, leg_races=leg_races, finance=finance, polls=polls, pr=pr, ratings=ratings, dpolls=dpolls)

def run(cfg, data, as_of, n_sims=None, disabled=(), seed=None, quiet=False):
    meta = data["meta"]; ref = meta["reference_margin_pres_2024"]
    env = environment_layer(cfg, data["polls"], data["pr"], as_of, ref)
    bc = cfg["environment"].get("poll_bias_correction", 0.0)
    if env["poll_based_margin"] is not None and bc:
        env["poll_based_margin_raw"] = env["poll_based_margin"]; env["poll_bias_correction"] = bc
        env["poll_based_margin"] = round(env["poll_based_margin"] + bc, 2)
        env["expected_statewide_margin"] = round(env["prior_weight"] * env["midterm_prior_margin"] + (1 - env["prior_weight"]) * env["poll_based_margin"], 2)
        env["swing_vs_reference"] = round(env["expected_statewide_margin"] - env["reference_margin"], 2)
    if "statewide_polls" in disabled:
        env = dict(env); env["expected_statewide_margin"] = env["midterm_prior_margin"]
    if "midterm_prior" in disabled and env["poll_based_margin"] is not None:
        env = dict(env); env["expected_statewide_margin"] = env["poll_based_margin"]
    seats = []
    for ch in ("H", "S"):
        if ch == "S" and data["seats_up"] is None: continue
        holders = None
        if ch == "S" and data["ctrl"].get("S") and isinstance(data["ctrl"]["S"].get("members"), dict):
            holders = {k: (v.get("party") if isinstance(v, dict) else str(v))[:1].upper() for k, v in data["ctrl"]["S"]["members"].items()}
        specials = []
        for k in ("H", "S"):
            cj = data["ctrl"].get(k) or {}
            for sp in cj.get("special_elections_2025_2026", []):
                if isinstance(sp, dict) and ("Senate" in str(sp.get("seat", "")) or "district" in sp) and ((k == "S") == (ch == "S")): specials.append(sp)
        seats += build_seats(cfg, data["base"], data["cands"], data["dists"], data["seats_up"] if ch == "S" else None, data["leg_results"], data["leg_races"], data["finance"], ch, holders=holders, specials=specials, env_hint=env["expected_statewide_margin"])
    # current holders for not-up seats
    seats = compose(cfg, seats, env["expected_statewide_margin"], disabled)
    seats = apply_layer4(cfg, seats, data["ratings"], data["dpolls"], as_of, disabled)
    seats = finalize(cfg, seats)
    n = n_sims or cfg["simulation"]["n_sims"]; seed = seed or cfg["simulation"]["seed"]
    results = {}
    for ch in ("H", "S"):
        if not any(s["chamber"] == ch for s in seats): continue
        cur = None
        if data["ctrl"].get(ch):
            pc = data["ctrl"][ch].get("partisan_composition") or data["ctrl"][ch].get("composition_ballotpedia_table") or {}
            cur = dict(dem=pc.get("democratic", pc.get("D")), rep=pc.get("republican", pc.get("R")), vacancies=pc.get("vacancies", pc.get("vacant")))
        ss, M, W, regions = simulate(cfg, seats, n, seed + (0 if ch == "H" else 1), ch)
        summ, per = summarize(cfg, ch, ss, M, W, cur)
        results[ch] = dict(summary=summ, seats=per)
    return env, seats, results

def main():
    args = sys.argv[1:]
    as_of = datetime.date.fromisoformat(args[args.index("--as-of") + 1]) if "--as-of" in args else today()
    cfg = load_config(); data = load_all(cfg)
    env, seats, results = run(cfg, data, as_of)
    # sensitivity
    sens = []
    base_stats = {ch: (results[ch]["summary"]["dem_seats_mean"], results[ch]["summary"]["p_dem_control"]) for ch in results}
    for src in cfg["sensitivity"]["sources"]:
        _, _, r2 = run(cfg, data, as_of, n_sims=cfg["sensitivity"]["n_sims"], disabled=(src,), seed=7)
        row = dict(source=src)
        for ch in results:
            if ch in r2:
                row[f"{ch}_dem_seats_delta"] = round(base_stats[ch][0] - r2[ch]["summary"]["dem_seats_mean"], 2)
                row[f"{ch}_p_dem_control_delta"] = round(base_stats[ch][1] - r2[ch]["summary"]["p_dem_control"], 4)
        sens.append(row)
    # assemble outputs
    per = {}
    for ch in results:
        for r in results[ch]["seats"]: per[r["key"]] = r
    out_rows = []
    for s in seats:
        r = per.get(s["key"], {})
        o = {k: v for k, v in s.items() if k not in ("adj",)}
        o.update(r); out_rows.append(o)
    df = pd.DataFrame(out_rows)
    df.to_csv(PROC / "forecast_seats.csv", index=False)
    (PROC / "forecast_seats.json").write_text(json.dumps(out_rows, default=lambda x: None if (isinstance(x, float) and np.isnan(x)) else (x.item() if hasattr(x, "item") else str(x))))
    summary = dict(generated_at=datetime.datetime.now().isoformat(timespec="minutes"), as_of=str(as_of), election_date=cfg["election_date"],
                   environment=env, chambers={ch: results[ch]["summary"] for ch in results}, sensitivity=sens, data_status=STATUS,
                   statewide_margins=data["meta"]["statewide_margins"], config=cfg)
    (PROC / "forecast_summary.json").write_text(json.dumps(summary, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x)))
    for ch in results:
        s = results[ch]["summary"]; print(ch, f"P(D control)={s['p_dem_control']:.3f} D seats mean={s['dem_seats_mean']} [{s['dem_seats_p10']}-{s['dem_seats_p90']}] current={s['current']}")
    print("env:", {k: v for k, v in env.items() if k != "components"})

if __name__ == "__main__":
    main()
