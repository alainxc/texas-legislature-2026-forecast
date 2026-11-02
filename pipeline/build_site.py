"""Build the static site in site/ from data/processed outputs. No build tooling: plain HTML/CSS/JS."""
import json, shutil, re, html, datetime
from common import *

SITE = ROOT / "site"; SRC = ROOT / "site_src"
TITLE = "Texas Legislature 2026 Forecast"
FOOT = ("Built from public data only: Texas Legislative Council, Texas Secretary of State, Texas Ethics Commission, Ballotpedia, "
        "and publicly released polls and ratings. Not affiliated with any campaign, caucus, party committee, or news outlet. "
        "Forecasts are probabilities, not predictions; see the methodology page for every assumption.")
NAV = [("index.html", "Overview"), ("house.html", "House"), ("senate.html", "Senate"), ("tipping-point.html", "Tipping point"), ("methodology.html", "Methodology"), ("changelog.html", "Changelog")]

def page(title, body, root="", active="", desc=""):
    nav = "".join(f'<a href="{root}{h}" class="{"on" if h == active else ""}">{t}</a>' for h, t in NAV)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><meta name="description" content="{html.escape(desc or TITLE)}"><link rel="stylesheet" href="{root}style.css">
<script>window.ROOT={json.dumps(root)};</script></head><body>
<header class="top"><div class="wrap"><nav class="main"><a class="brand" href="{root}index.html">{TITLE}</a>{nav}</nav></div></header>
<main class="wrap">{body}</main>
<footer class="wrap"><p>{FOOT}</p><p>Last model run: <span data-generated></span>. <a href="{root}methodology.html#sources">Sources and retrieval dates</a>.</p></footer>
<script src="{root}data/forecast.js"></script><script src="{root}data/geo.js"></script><script src="{root}data/backtest.js"></script><script src="{root}app.js"></script>
<script>document.querySelector('[data-generated]').textContent = window.FORECAST.generated_at.replace('T',' ');</script>
</body></html>"""

def md_lite(text):
    out, in_list = [], False
    for line in text.splitlines():
        if line.startswith("- "):
            if not in_list: out.append("<ul>"); in_list = True
            out.append(f"<li>{inline(line[2:])}</li>"); continue
        if in_list: out.append("</ul>"); in_list = False
        if line.startswith("### "): out.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("## "): out.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("# "): out.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.strip(): out.append(f"<p>{inline(line)}</p>")
    if in_list: out.append("</ul>")
    return "\n".join(out)
def inline(s):
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s); s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2" rel="noopener">\1</a>', s)

def fmtm(m): return "—" if m is None else (f"D+{m:.1f}" if m > 0 else f"R+{-m:.1f}" if m < 0 else "Even")

def main():
    summ = json.loads((PROC / "forecast_summary.json").read_text())
    seats = json.loads((PROC / "forecast_seats.json").read_text())
    bt = json.loads((PROC / "backtest.json").read_text()) if (PROC / "backtest.json").exists() else {}
    geo = {k: json.loads((PROC / f"{k}_geo.json").read_text()) for k in ("house", "senate") if (PROC / f"{k}_geo.json").exists()}
    if SITE.exists(): shutil.rmtree(SITE)
    (SITE / "data").mkdir(parents=True); (SITE / "districts").mkdir()
    shutil.copy(SRC / "style.css", SITE / "style.css"); shutil.copy(SRC / "app.js", SITE / "app.js")
    cfg = summ["config"]
    F = dict(generated_at=summ["generated_at"], as_of=summ["as_of"], election_date=summ["election_date"], environment=summ["environment"], chambers=summ["chambers"],
             sensitivity=summ["sensitivity"], statewide_margins=summ["statewide_margins"], data_status=summ["data_status"], seats=seats,
             config=dict(environment=cfg["environment"], candidate=cfg["candidate"], simulation=cfg["simulation"], district_polls_and_ratings=cfg["district_polls_and_ratings"]))
    (SITE / "data/forecast.js").write_text("window.FORECAST=" + json.dumps(F, separators=(",", ":")) + ";")
    (SITE / "data/geo.js").write_text("window.GEO=" + json.dumps(geo, separators=(",", ":")) + ";")
    (SITE / "data/backtest.js").write_text("window.BACKTEST=" + json.dumps({k: v for k, v in bt.items() if k != "rows"}, separators=(",", ":"), default=str) + ";")
    H, S = summ["chambers"].get("H"), summ["chambers"].get("S")
    env = summ["environment"]
    # ---- index
    body = f"""<h1>Who will control the Texas Legislature after November 3, 2026?</h1>
<p class="sub">A FiveThirtyEight-style probabilistic forecast of all 150 Texas House seats and the 16 Texas Senate seats on the ballot, updated through {summ['as_of']}. Republicans hold both chambers going in.</p>
<div class="grid"><div class="card" data-render="chamberCard:H"></div><div class="card" data-render="chamberCard:S"></div></div>
<h2>The statewide environment</h2><div class="card"><p>The model expects a generic Texas legislative race to run about <b>{fmtm(env['expected_statewide_margin'])}</b> statewide, a swing of <b>{'D' if env['swing_vs_reference']>0 else 'R'}+{abs(env['swing_vs_reference']):.1f}</b> from the 2024 presidential result ({fmtm(env['reference_margin'])}). It blends {env['total_polls']} public polls of the governor race, the U.S. Senate race, Texas generic-ballot questions, the national generic ballot and Abbott approval with a structural midterm prior. <a href="methodology.html#environment">How this is computed</a>.</p><div data-render="envTable"></div></div>
<div class="grid"><div class="card"><h2>Closest races</h2><div data-render="closest:14"></div><p class="small">Every seat: <a href="house.html">House table and map</a> · <a href="senate.html">Senate table and map</a></p></div>
<div class="card"><h2>Seats most likely to flip</h2><div data-render="flips"></div></div></div>
<h2>Maps</h2><div class="grid"><div class="card"><h3><a href="house.html">Texas House</a></h3><div data-render="drawMap:H"></div></div><div class="card"><h3><a href="senate.html">Texas Senate</a></h3><div data-render="drawMap:S"></div></div></div>
<div class="legend"><span><i style="background:var(--dem)"></i>Democrat favored</span><span><i style="background:var(--neutral)"></i>Toss-up</span><span><i style="background:var(--rep)"></i>Republican favored</span><span><i style="background:repeating-linear-gradient(45deg,var(--neutral),var(--neutral) 3px,var(--card) 3px,var(--card) 6px)"></i>Not up in 2026</span><span>Darker = more certain. Hover for details, click for the district page.</span></div>"""
    (SITE / "index.html").write_text(page(TITLE, body, active="index.html", desc="Probabilistic forecast of the 2026 Texas House and Texas Senate elections"))
    for ch, fn, name in (("H", "house.html", "Texas House"), ("S", "senate.html", "Texas Senate")):
        c = summ["chambers"].get(ch)
        intro = f"All 150 seats are up. Republicans hold {c['current']['rep']} seats, Democrats {c['current']['dem']}, with {c['current']['vacancies']} vacant; 76 is a majority." if ch == "H" and c else (f"16 of 31 seats are on the ballot (terms were reset by lots after redistricting). Republicans hold {c['current']['rep']}, Democrats {c['current']['dem']}, 1 vacant; 16 is a majority." if c else "")
        body = f"""<h1>{name}</h1><p class="sub">{intro}</p><div class="card" data-render="chamberCard:{ch}"></div>
<h2>Map</h2><div class="card"><div data-render="drawMap:{ch}"></div><div class="legend"><span><i style="background:var(--dem)"></i>Democrat favored</span><span><i style="background:var(--neutral)"></i>Toss-up</span><span><i style="background:var(--rep)"></i>Republican favored</span>{'<span><i style="background:repeating-linear-gradient(45deg,var(--neutral),var(--neutral) 3px,var(--card) 3px,var(--card) 6px)"></i>Not up in 2026</span>' if ch=='S' else ''}<span>Darker = more certain. Hover for details, click for the district page.</span></div></div>
<h2>All seats</h2><p class="small">Click a column to sort. "Lean" is the district's partisan lean relative to Texas as a whole (layer 1). "Exp. margin" is the modelled Democratic-minus-Republican margin.</p><div data-render="seatTable:{ch}"></div>"""
        (SITE / fn).write_text(page(f"{name} · {TITLE}", body, active=fn))
    body = f"""<h1>Tipping-point seats</h1><p class="sub">Which seats decide the majority.</p><h2>Texas House</h2><div class="card" data-render="tippingPage:H"></div><h2>Texas Senate</h2><div class="card" data-render="tippingPage:S"></div>"""
    (SITE / "tipping-point.html").write_text(page(f"Tipping point · {TITLE}", body, active="tipping-point.html"))
    # ---- district pages
    for s in seats:
        nm = ("House District " if s["chamber"] == "H" else "Senate District ") + str(s["district"])
        body = f'<div data-render="districtPage:{s["key"]}"></div><p class="small"><a href="../{"house" if s["chamber"]=="H" else "senate"}.html">← All {"House" if s["chamber"]=="H" else "Senate"} seats</a></p>'
        (SITE / "districts" / f"{s['key']}.html").write_text(page(f"{nm} · {TITLE}", body, root="../", desc=f"2026 forecast for Texas {nm}: {s.get('dem_name','')} vs {s.get('rep_name','')}"))
    # ---- methodology
    (SITE / "methodology.html").write_text(page(f"Methodology · {TITLE}", methodology(summ, seats, bt), active="methodology.html"))
    cl = (ROOT / "docs/CHANGELOG.md").read_text() if (ROOT / "docs/CHANGELOG.md").exists() else "# Changelog\n"
    (SITE / "changelog.html").write_text(page(f"Changelog · {TITLE}", "<div class='prose'>" + md_lite(cl) + "</div>", active="changelog.html"))
    (SITE / ".nojekyll").write_text("")
    print("site built:", sum(1 for _ in SITE.rglob("*.html")), "pages")

def methodology(summ, seats, bt):
    cfg = summ["config"]; env = summ["environment"]; b = cfg["baseline"]; c = cfg["candidate"]; e = cfg["environment"]; L = cfg["district_polls_and_ratings"]; S = cfg["simulation"]
    races = ", ".join(f"{r['key'].replace('_', ' ')} ({r['weight']:.0%})" for r in b["statewide_races"])
    # sources from manifests
    src_rows = []
    for mf in sorted(RAW.rglob("manifest.json")):
        try:
            for m in json.loads(mf.read_text()):
                if isinstance(m, dict) and m.get("url"): src_rows.append((mf.parent.name, m.get("file", ""), m["url"], str(m.get("retrieved_at", ""))[:16], m.get("description", "")))
        except Exception: pass
    seen = set(); src_html = ""
    for d, f, u, t, desc in src_rows:
        if u in seen: continue
        seen.add(u); src_html += f"<tr><td>{html.escape(d)}</td><td><a href='{html.escape(u)}' rel='noopener'>{html.escape(u[:90])}{'…' if len(u)>90 else ''}</a><div class='small'>{html.escape(desc[:120])}</div></td><td>{html.escape(t)}</td></tr>"
    # markets
    mk = RAW / "markets/markets.csv"; mk_html = "<p>No open Kalshi or Polymarket market on Texas legislative control was found at retrieval time, so there is no market cross-check to show.</p>"
    if mk.exists() and mk.stat().st_size > 10:
        M = pd.read_csv(mk, dtype=str).fillna("")
        if len(M): mk_html = "<div class='tablewrap'><table><thead><tr><th>Platform</th><th>Market</th><th>Outcome</th><th class='num'>Yes price</th><th>As of</th></tr></thead><tbody>" + "".join(f"<tr><td>{html.escape(r.platform)}</td><td><a href='{html.escape(r.url)}' rel='noopener'>{html.escape(r.market_title)}</a></td><td>{html.escape(r.outcome)}</td><td class='num'>{html.escape(r.yes_price)}</td><td>{html.escape(r.as_of[:10])}</td></tr>" for r in M.itertuples()) + "</tbody></table></div><p class='small'>Markets are shown for comparison only and are never an input to the model.</p>"
    # State Navigate comparison
    sn_html = "<p>No State Navigate district ratings were retrievable, so no seat-level comparison is shown.</p>"
    rt = RAW / "ratings/ratings.csv"
    if rt.exists() and rt.stat().st_size > 10:
        R = pd.read_csv(rt, dtype=str).fillna("")
        R = R[R.source.str.contains("State Navigate", case=False)]
        if len(R):
            order = ["Safe D", "Likely D", "Lean D", "Tilt D", "Toss-up", "Tilt R", "Lean R", "Likely R", "Safe R"]
            def ours(s):
                p = s.get("p_dem")
                if p is None or s.get("contest") not in ("D_vs_R",): return None
                q = p if p >= .5 else 1 - p; side = "D" if p >= .5 else "R"
                return "Toss-up" if q <= .65 else f"Lean {side}" if q <= .85 else f"Likely {side}" if q <= .97 else f"Safe {side}"
            byk = {s["key"]: s for s in seats}; rows = []
            for r in R.itertuples():
                key = f"{'HD' if r.chamber=='H' else 'SD'}{int(float(r.district)):03d}"; s = byk.get(key)
                if not s: continue
                o = ours(s)
                if o is None or r.rating_std not in order: continue
                gap = order.index(o) - order.index(r.rating_std.replace("Tilt", "Lean") if r.rating_std.startswith("Tilt") else r.rating_std)
                rows.append((abs(gap), key, r.rating_std, o, s["p_dem"], s.get("margin_mean")))
            rows.sort(reverse=True)
            sn_html = f"<p>State Navigate rates {len(R)} Texas legislative seats. Where both make a call, the two agree on the category in {sum(1 for x in rows if x[0]==0)} of {len(rows)} seats. The largest disagreements:</p><div class='tablewrap'><table><thead><tr><th>Seat</th><th>State Navigate</th><th>This model</th><th class='num'>Dem win</th><th class='num'>Exp. margin</th></tr></thead><tbody>" + "".join(f"<tr><td><a href='districts/{k}.html'>{k[:2]} {int(k[2:])}</a></td><td>{html.escape(a)}</td><td>{o}</td><td class='num'>{p:.0%}</td><td class='num'>{fmtm(m)}</td></tr>" for g, k, a, o, p, m in rows[:12] if g > 0) + "</tbody></table></div>"
    status = "".join(f"<li>{html.escape(x)}</li>" for x in summ.get("data_status", [])) or "<li>All configured inputs were found.</li>"
    bt_excl = ", ".join(bt.get("excluded_inputs", [])) if bt else ""
    return f"""<div class="prose"><h1>Methodology</h1>
<p class="sub">Plain-language description of how the Texas Legislature 2026 Forecast works. Every weight below is read from one configuration file (<code>config/model_config.yaml</code>) and nothing in the processed data is hand-edited.</p>
<h2>The short version</h2>
<p>For each seat we estimate the expected Democratic-minus-Republican margin from four layers: (1) how the district has voted in recent statewide races on today's lines, (2) who is running, (3) the statewide political environment implied by public polls and a midterm prior, and (4) district-level polls and outside ratings used as capped nudges. We then run {S['n_sims']:,} simulations in which errors are shared statewide, by region, and by Hispanic voter share, with fat tails, to turn margins into probabilities and chamber-control odds.</p>
<h2 id="layer1">Layer 1 · District baseline</h2>
<p>The Texas Legislative Council publishes statewide election returns aggregated to the current House (PLANH2316) and Senate (PLANS2168) district lines, which avoids any precinct crosswalk. We confirmed with the Council that the 2025 mid-decade redistricting changed only the congressional map, so 2020, 2022 and 2024 results apply directly. A district's lean is its margin minus the statewide margin in the same race, blended across: {races}. The district's own legislative results in 2022 and 2024 (contested races only, measured against that year's average contested legislative margin) are blended in at {b['legislative_lean_weight']:.0%} after being shrunk halfway toward the statewide lean, because legislative results carry candidate effects.</p>
<h2 id="layer2">Layer 2 · Candidates</h2>
<ul><li><b>Incumbency:</b> {c['incumbency_bonus']['house']} points (House) / {c['incumbency_bonus']['senate']} (Senate); first-term incumbents get {1-c['freshman_incumbent_discount']:.0%} of that.</li>
<li><b>Open seats</b> get no incumbency bonus and extra simulation variance (+{S['open_seat_extra_sd']} points s.d.).</li>
<li><b>Prior performance:</b> {c['performance_carryover']:.0%} of a returning candidate's past over- or under-performance against the district's expectation carries forward (capped at ±12 points before scaling). A non-incumbent who was the party's nominee here before gets {c['prior_nominee_bonus']} points. These are our proxies for candidate quality.</li>
<li><b>Campaign finance:</b> Texas Ethics Commission cover-sheet totals of contributions reported since January 2025, with a ${c['finance']['floor_dollars']:,} floor added to both sides to suppress noise; effect = {c['finance']['points_per_log_ratio']} × log(D/R), capped at ±{c['finance']['cap_points']} points. Candidates with no matched filing are treated as raising only the floor.</li>
<li><b>Uncontested races</b> (one name on the ballot) are called with certainty; write-ins are ignored.</li>
<li><b>Third-party and independent candidates</b> are modelled explicitly. When one major party is absent, the minor candidate is assumed to capture {c['third_party']['orphan_capture']:.0%} of the absent party's baseline voters plus a {c['third_party']['base_share']}-point base, with extra variance ({c['third_party']['extra_sd_when_major_absent']} points s.d.), so such seats are never simply marked unopposed. When both major parties run, minor candidates do not change the D−R margin.</li></ul>
<h2 id="environment">Layer 3 · Statewide environment</h2>
<p><b>There is no Texas legislative generic ballot poll.</b> Instead the expected statewide margin for a generic legislative race is built from five indicators, each converted to an implied Texas generic margin: Texas generic/congressional-preference questions (weight {e['indicators']['tx_generic']['weight']}); the Texas U.S. Senate race (weight {e['indicators']['tx_sen']['weight']}, adjusted {e['indicators']['tx_sen']['adjust']:+} points for the Republican nominee's past under-performance of the ticket); the governor race (weight {e['indicators']['tx_gov']['weight']}, adjusted {e['indicators']['tx_gov']['adjust']:+} to strip the incumbent governor's personal edge); the national generic ballot plus Texas's {e['texas_lean_vs_nation']} lean versus the nation (weight {e['indicators']['us_generic']['weight']}); and Abbott net approval (weight {e['indicators']['tx_abbott_approval']['weight']}). Each poll is weighted by recency (half-life {e['poll_half_life_days']} days), sample size (square root, capped at {e['sample_size_cap']:,}), pollster quality (the last public FiveThirtyEight pollster ratings) and partisanship (sponsored or internal polls get {e['partisan_poll_weight']:.0%} weight and are shifted {e['partisan_poll_shift']} points away from the sponsor's side). Polls older than {e['max_poll_age_days']} days are dropped.</p>
<p>The poll-based margin is then combined with a <b>structural midterm prior</b>: the 2024 presidential margin shifted {e['midterm_prior']['swing_toward_out_party']} points toward the party out of the White House, with weight {e['midterm_prior']['weight_when_polls_full']} when polling is plentiful. Because Texas polls overstated Democrats by about 3.5 points in both backtest years (below), a correction of {e.get('poll_bias_correction', 0)} points is applied to the 2026 poll-based margin; the backtests do not use this correction. Current values: poll-based margin {fmtm(env.get('poll_based_margin'))}{' (raw ' + fmtm(env.get('poll_based_margin_raw')) + ')' if env.get('poll_based_margin_raw') is not None else ''}, prior {fmtm(env['midterm_prior_margin'])}, expected statewide margin <b>{fmtm(env['expected_statewide_margin'])}</b>.</p>
<div data-render="pollList"></div>
<h2 id="layer4">Layer 4 · District polls and outside ratings</h2>
<p>Public district-level polls are averaged with the same recency weighting; internal polls get {L['internal_poll_weight']:.0%} weight and are shifted {L['internal_poll_shift']} points against the sponsor. The poll average replaces at most {L['district_poll_weight_cap']:.0%} of the model's view. Outside ratings (State Navigate, CNalysis, Sabato's Crystal Ball, Ballotpedia battleground lists, and DLCC/RSLC/caucus target lists) are converted to implied margins (Safe ±{L['rating_implied_margin']['Safe']}, Likely ±{L['rating_implied_margin']['Likely']}, Lean ±{L['rating_implied_margin']['Lean']}, Tilt ±{L['rating_implied_margin']['Tilt']}, Toss-up 0) and blended in as <b>capped priors</b>: total ratings weight is capped at {L['ratings_total_weight_cap']:.0%} and the shift at {L['ratings_max_shift_points']} points, so ratings can nudge but never dictate a seat. Target lists only pull a seat slightly toward toss-up and add variance.</p>
<h2 id="simulation">Simulation</h2>
<p>{S['n_sims']:,} Monte Carlo runs. Each run draws a statewide error from a Student-t distribution ({S['statewide_error']['student_t_df']} degrees of freedom, scaled to s.d. {S['statewide_error']['sd']} points) so large polling misses are possible; a regional error (s.d. {S['regional_error_sd']}) shared by seats in the same part of Texas; a Hispanic-share factor (s.d. {S['hispanic_factor_sd']}, scaled by each district's Spanish-surname voter registration share) capturing the correlated shifts seen in 2020 and 2024; and an independent district error (s.d. {S['district_error_sd']['house']} House / {S['district_error_sd']['senate']} Senate, larger for open seats, seats with no recent contested result, and one-major-party races). Senate seats not on the ballot are fixed to their current holders.</p>
<h2 id="outputs">Outputs</h2><p>Per-seat win probabilities and 80% margin intervals, seat distributions, chamber-control probabilities, tipping-point frequencies, a flip list, and the sensitivity table below.</p>
<h2 id="sensitivity">Sensitivity: how much each outside source moves the forecast</h2><div data-render="sensTable"></div>
<h2 id="backtest">Backtest</h2><p>The same pipeline was run for the 2022 and 2024 Texas legislative elections using only statewide results from earlier cycles, that year's candidates and incumbency, and that year's pre-election polls. Not available historically and therefore excluded: {html.escape(bt_excl)}. Brier scores are for contested two-party races (0 = perfect, 0.25 = coin flip). The positive margin bias in both years is the pro-Democratic polling error that motivates the correction above.</p><div data-render="backtestTable"></div>
<h2 id="compare">How this differs from State Navigate and other outlets</h2>
<p>State Navigate, CNalysis and Sabato publish categorical ratings informed by expert judgement; the DLCC and RSLC publish target lists that reflect spending priorities. This site publishes probabilities and margin ranges from a transparent, reproducible model, uses their ratings only as capped nudges, models minor-party-only races explicitly, applies a documented Texas polling-bias correction, and backtests itself. It has no access to private polling or field reports, which is where expert raters often have an edge.</p>{sn_html}
<h2 id="markets">Prediction-market cross-check</h2>{mk_html}
<h2 id="data">Data status for this run</h2><ul>{status}</ul>
<h2 id="sources">Sources</h2><p>Every raw file carries its source URL and retrieval date in a manifest. Public sources only; nothing is hand-edited downstream.</p><div class="tablewrap"><table><thead><tr><th>Group</th><th>Source</th><th>Retrieved</th></tr></thead><tbody>{src_html}</tbody></table></div>
</div>"""

if __name__ == "__main__":
    main()
