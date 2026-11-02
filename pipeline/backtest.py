"""Backtest the model on the 2022 and 2024 Texas legislative elections using only inputs
available before each election (statewide races from earlier years, that year's candidate list
and incumbency, that year's pre-election polls). Campaign finance and external ratings are not
available historically in this pipeline and are excluded (documented on the methodology page)."""
import copy, json, datetime
from common import *
import baseline, forecast
from forecast import tf, num, note

def main():
    cfg0 = load_config()
    leg_results = forecast.read_csv_opt("leg_results/leg_results.csv"); leg_races = forecast.read_csv_opt("leg_results/leg_races.csv", ["uncontested", "incumbent_party_if_known"])
    polls = forecast.read_csv_opt("polls/polls.csv"); pr = None
    if leg_results is None or leg_races is None:
        note("Backtest skipped: legislative results missing"); (PROC / "backtest.json").write_text(json.dumps(dict(status=forecast.STATUS))); return
    results = {}
    for year, bc in cfg0["backtest_years"].items():
        year = int(year)
        cfg = copy.deepcopy(cfg0)
        cfg["baseline"]["statewide_races"] = bc["statewide_races"]; cfg["baseline"]["reference_race"] = bc["reference_race"]
        cfg["baseline"]["legislative_years"] = {int(k): v for k, v in bc["legislative_years"].items()}
        cfg["environment"]["indicators"] = bc["indicators"]; cfg["environment"]["midterm_prior"] = bc["midterm_prior"]
        base, meta = baseline.build(cfg, write=False)
        # legislative lean must only use years < year: baseline.build already restricted via legislative_years
        # candidates from that year's results
        Y = leg_results[leg_results.year.astype(int) == year].copy()
        cands = pd.DataFrame(dict(chamber=Y.chamber, district=Y.district.astype(int), candidate_name=Y.candidate_name, party=Y.party.str[:1].str.upper(),
                                  party_raw=Y.party, incumbent=Y.get("incumbent", "").apply(tf).astype(str), withdrew="false"))
        cands.loc[~cands.party.isin(["D", "R"]), "party"] = cands.loc[~cands.party.isin(["D", "R"]), "party_raw"].str[:1].str.upper()
        dists = []
        for (ch, d), g in cands.groupby(["chamber", "district"]):
            inc = g[g.incumbent == "True"]
            dists.append(dict(chamber=ch, district=d, incumbent_party=inc.party.iloc[0] if len(inc) else "", open_seat=str(len(inc) == 0), notes=""))
        dists = pd.DataFrame(dists)
        hist = leg_results[leg_results.year.astype(int) < year]
        hist_races = leg_races[leg_races.year.astype(int) < year]
        # Senate: seats contested that year are the ones in results
        seats_up = set(cands[cands.chamber == "S"].district.unique().tolist())
        data = dict(base=base, meta=meta, cands=cands, dists=dists, seats_up=seats_up, ctrl={"H": None, "S": None},
                    leg_results=hist, leg_races=hist_races, finance=None, polls=polls, pr=pr, ratings=None, dpolls=None)
        as_of = datetime.date(year, 11, 1)
        ref = meta["reference_margin_pres_2024"]  # key name is historical; holds the reference race margin
        env = forecast.environment_layer(cfg, polls, pr, as_of, ref, year=year, out_party_is_dem=bc["out_party_is_dem"])
        seats = []
        for ch in ("H", "S"):
            seats += forecast.build_seats(cfg, base, cands, dists, seats_up if ch == "S" else None, hist, hist_races, None, ch, year=year)
        seats = forecast.compose(cfg, seats, env["expected_statewide_margin"])
        seats = forecast.apply_layer4(cfg, seats, None, None, as_of)
        seats = forecast.finalize(cfg, seats)
        out = dict(year=year, environment={k: v for k, v in env.items() if k != "components"},
                   environment_components=[{k: v for k, v in c.items() if k != "rows"} for c in env["components"]], chambers={})
        actual = leg_races[leg_races.year.astype(int) == year]
        for ch in ("H", "S"):
            if not any(s["chamber"] == ch and s.get("contest") for s in seats): continue
            ss, M, W, _ = forecast.simulate(cfg, seats, cfg["backtest"]["n_sims"], 11, ch)
            summ, per = forecast.summarize(cfg, ch, ss, M, W, None)
            rows = []
            for s, p in zip(ss, per):
                a = actual[(actual.chamber == ch) & (actual.district.astype(int) == s["district"])]
                if a.empty: continue
                a = a.iloc[0]; am = num(a.margin_d_minus_r); aw = str(a.winner_party).strip()[:1].upper()
                rows.append(dict(key=s["key"], contest=s.get("contest"), p_dem=p["p_dem"], margin_mean=p.get("margin_mean"), p10=p.get("margin_p10"), p90=p.get("margin_p90"),
                                 actual_margin=am, actual_winner=aw, called=(("D" if p["p_dem"] > 0.5 else "R") == aw) if aw in "DR" else None))
            df = pd.DataFrame(rows)
            con = df[df.contest == "D_vs_R"].dropna(subset=["actual_margin"])
            yD = (con.actual_winner == "D").astype(float)
            metrics = dict(seats_scored=len(df), seats_called=int(df.called.fillna(False).sum()), seats_called_pct=round(100 * df.called.fillna(False).mean(), 1),
                           contested_races=len(con), contested_called=int(con.called.sum()), contested_called_pct=round(100 * con.called.mean(), 1) if len(con) else None,
                           brier_contested=round(float(((con.p_dem - yD) ** 2).mean()), 4) if len(con) else None,
                           margin_mae=round(float((con.margin_mean - con.actual_margin).abs().mean()), 2) if len(con) else None,
                           margin_bias_d_minus_r=round(float((con.margin_mean - con.actual_margin).mean()), 2) if len(con) else None,
                           interval80_coverage=round(100 * float(((con.actual_margin >= con.p10) & (con.actual_margin <= con.p90)).mean()), 1) if len(con) else None,
                           dem_seats_forecast_mean=summ["dem_seats_mean"], dem_seats_actual=int((df.actual_winner == "D").sum()), rep_seats_actual=int((df.actual_winner == "R").sum()),
                           p_dem_control=summ["p_dem_control"])
            misses = con[~con.called.astype(bool)][["key", "p_dem", "margin_mean", "actual_margin", "actual_winner"]].to_dict("records")
            out["chambers"][ch] = dict(metrics=metrics, misses=misses, rows=rows)
            print(year, ch, metrics)
        results[str(year)] = out
    (PROC / "backtest.json").write_text(json.dumps(dict(results=results, notes=forecast.STATUS, excluded_inputs=["campaign finance (no historical pull)", "external ratings / district polls (not archived)"]), indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x)))

if __name__ == "__main__":
    main()
