#!/usr/bin/env python
"""fetch_polls.py -- statewide-environment polling layer for the TX Legislature 2026 forecast.

Runnable with no arguments. Re-downloads every raw source into data/raw/polls/, parses it,
and writes polls.csv, pollster_ratings.csv and manifest.json there. Deterministic: every
source URL is pinned (Wikipedia live pages for the current cycle; a pinned Wayback Machine
snapshot for the retired FiveThirtyEight generic-ballot CSV used for the 2022/2024 backtest).

Races written (column `race`):
  current cycle: tx_gov, tx_sen, tx_generic, tx_abbott_approval, us_generic
  backtest:      tx_gov_2022, tx_pres_2024, tx_sen_2024, us_generic_2022, us_generic_2024,
                 tx_abbott_approval_2022
"""
import json
import os
import re
import sys
import time
from datetime import datetime, date
from io import StringIO

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(PROJECT, "data", "raw", "polls")
os.makedirs(OUT, exist_ok=True)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})

RETRIEVED_AT = datetime.now().strftime("%Y-%m-%dT%H:%M")
MANIFEST = []

COLUMNS = ["race", "pollster", "sponsor", "partisan", "start_date", "end_date", "sample_size",
           "population", "dem_pct", "rep_pct", "other_pct", "approve_pct", "disapprove_pct",
           "dem_candidate", "rep_candidate", "source_url", "retrieved_at", "internal"]

WIKI = "https://en.wikipedia.org/wiki/"
SOURCES = {
    # current cycle
    "wiki_2026_tx_gov.html": WIKI + "2026_Texas_gubernatorial_election",
    "wiki_2026_tx_sen.html": WIKI + "2026_United_States_Senate_election_in_Texas",
    "wiki_2026_tx_house.html": WIKI + "2026_United_States_House_of_Representatives_elections_in_Texas",
    "wiki_2026_us_house.html": WIKI + "2026_United_States_House_of_Representatives_elections",
    "wiki_2026_us_elections.html": WIKI + "2026_United_States_elections",
    "tpp_abbott_job_approval_trend.html": "https://texaspolitics.utexas.edu/set/greg-abbott-job-approval-trend",
    "tpp_abbott_approval_october_2026.html": "https://texaspolitics.utexas.edu/set/greg-abbott-approval-october-2026",
    "tpp_2026_gov_tracker.html": "https://texaspolitics.utexas.edu/blog/texas-2026-gubernatorial-poll-tracker",
    "tpp_2026_sen_tracker.html": "https://texaspolitics.utexas.edu/blog/texas-2026-u-s-senate-poll-tracker",
    "270towin_2026_tx_gov.html": "https://www.270towin.com/2026-governor-polls/texas",
    "270towin_2026_tx_sen.html": "https://www.270towin.com/2026-senate-polls/texas",
    # backtest
    "wiki_2022_tx_gov.html": WIKI + "2022_Texas_gubernatorial_election",
    "wiki_2024_tx_pres.html": WIKI + "2024_United_States_presidential_election_in_Texas",
    "wiki_2024_tx_sen.html": WIKI + "2024_United_States_Senate_election_in_Texas",
    # FiveThirtyEight retired its polls site in 2025; this is a pinned Wayback snapshot of the
    # last public generic_ballot_polls_historical.csv (covers 2018-2024 cycles, wide dem/rep).
    "fte_generic_ballot_polls_historical_wayback20250305.csv":
        "https://web.archive.org/web/20250305204633id_/https://projects.fivethirtyeight.com/polls/data/generic_ballot_polls_historical.csv",
    # pollster quality ratings (latest public FiveThirtyEight table, GitHub master)
    "pollster_ratings.csv":
        "https://raw.githubusercontent.com/fivethirtyeight/data/master/pollster-ratings/pollster-ratings-combined.csv",
}
DESCRIPTIONS = {
    "wiki_2026_tx_gov.html": "Wikipedia: 2026 Texas gubernatorial election (general-election polling tables)",
    "wiki_2026_tx_sen.html": "Wikipedia: 2026 US Senate election in Texas (general-election polling tables)",
    "wiki_2026_tx_house.html": "Wikipedia: 2026 US House elections in Texas (statewide generic-ballot polling table)",
    "wiki_2026_us_house.html": "Wikipedia: 2026 US House elections (generic ballot aggregates only; saved for traceability)",
    "wiki_2026_us_elections.html": "Wikipedia: 2026 United States elections (national generic congressional ballot poll tables)",
    "tpp_abbott_job_approval_trend.html": "Texas Politics Project: Greg Abbott job approval trend (Highcharts data embedded in page)",
    "tpp_abbott_approval_october_2026.html": "Texas Politics Project: Abbott approval, October 2026 poll set page",
    "tpp_2026_gov_tracker.html": "Texas Politics Project 2026 gubernatorial poll tracker (cross-check only, not parsed into polls.csv)",
    "tpp_2026_sen_tracker.html": "Texas Politics Project 2026 US Senate poll tracker (cross-check only, not parsed into polls.csv)",
    "270towin_2026_tx_gov.html": "270toWin Texas governor 2026 polls (cross-check only, last ~10 polls)",
    "270towin_2026_tx_sen.html": "270toWin Texas Senate 2026 polls (cross-check only, last ~10 polls)",
    "wiki_2022_tx_gov.html": "Wikipedia: 2022 Texas gubernatorial election (Abbott vs O'Rourke polling)",
    "wiki_2024_tx_pres.html": "Wikipedia: 2024 US presidential election in Texas (Trump vs Harris / Trump vs Biden polling)",
    "wiki_2024_tx_sen.html": "Wikipedia: 2024 US Senate election in Texas (Cruz vs Allred polling)",
    "fte_generic_ballot_polls_historical_wayback20250305.csv":
        "FiveThirtyEight generic_ballot_polls_historical.csv, Wayback Machine snapshot 2025-03-05 (2022 and 2024 national generic ballot)",
    "pollster_ratings.csv": "FiveThirtyEight pollster-ratings-combined.csv (numeric_grade, POLLSCORE, transparency, bias)",
    "polls.csv": "Tidy polling dataset produced by this script",
}


def fetch(fname, url, retries=5):
    """Download url to OUT/fname. Backs off on HTTP 429 (web.archive.org rate-limits).
    If every attempt fails but a copy from a previous run exists, that copy is kept and the
    manifest says so, so the parse step still runs on a traceable raw file."""
    path = os.path.join(OUT, fname)
    last = None
    for attempt in range(retries):
        try:
            r = SESSION.get(url, timeout=90)
            if r.status_code == 200 and len(r.content) > 1000:
                with open(path, "wb") as f:
                    f.write(r.content)
                MANIFEST.append({"file": fname, "url": url, "retrieved_at": RETRIEVED_AT,
                                 "description": DESCRIPTIONS.get(fname, ""), "http_status": r.status_code,
                                 "bytes": len(r.content)})
                print(f"fetched {fname} ({len(r.content)} bytes)")
                return path
            last = f"HTTP {r.status_code}, {len(r.content)} bytes"
            wait = 15 * (attempt + 1) if r.status_code == 429 else 3 * (attempt + 1)
            try:
                wait = max(wait, int(r.headers.get("Retry-After", "0")))
            except ValueError:
                pass
        except Exception as e:  # noqa
            last = repr(e)
            wait = 3 * (attempt + 1)
        time.sleep(wait)
    if os.path.exists(path):
        print(f"WARNING {fname}: download failed ({last}); keeping copy from a previous run", file=sys.stderr)
        MANIFEST.append({"file": fname, "url": url, "retrieved_at": RETRIEVED_AT,
                         "description": DESCRIPTIONS.get(fname, ""), "error": last,
                         "cached_from_previous_run": True,
                         "file_mtime": datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%dT%H:%M")})
        return path
    print(f"FAILED {fname}: {last}", file=sys.stderr)
    MANIFEST.append({"file": fname, "url": url, "retrieved_at": RETRIEVED_AT,
                     "description": DESCRIPTIONS.get(fname, ""), "error": last})
    return None


# ----------------------------------------------------------------------------- helpers
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9

DASHES = "–—−‐‑-"


def clean(s):
    """Strip Wikipedia footnote markers like [12], [a], [AB] and normalise whitespace."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    s = str(s)
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = s.replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def parse_dates(txt):
    """Parse Wikipedia 'Date(s) administered' strings into (start_iso, end_iso).

    Handles: 'October 27 – November 1, 2026', 'October 27–30, 2026', 'May 26, 2026',
    'December 26, 2025 – January 3, 2026', 'Sept. 19 – Oct. 1, 2025'."""
    t = clean(txt)
    if not t:
        return "", ""
    t = re.sub(f"[{DASHES}]", "-", t).replace(".", "")
    t = re.sub(r"\s*-\s*", "-", t)
    m = re.match(r"^([A-Za-z]+) (\d{1,2}),? (\d{4})-([A-Za-z]+) (\d{1,2}),? (\d{4})$", t)
    if m:
        a, b, c, d, e, f = m.groups()
        return _iso(c, a, b), _iso(f, d, e)
    m = re.match(r"^([A-Za-z]+) (\d{1,2})-([A-Za-z]+) (\d{1,2}),? (\d{4})$", t)
    if m:
        a, b, d, e, y = m.groups()
        s, e_ = _iso(y, a, b), _iso(y, d, e)
        if s and e_ and s > e_:  # year rollover, e.g. December 28 - January 2, 2026
            s = _iso(str(int(y) - 1), a, b)
        return s, e_
    m = re.match(r"^([A-Za-z]+) (\d{1,2})-(\d{1,2}),? (\d{4})$", t)
    if m:
        a, b, c, y = m.groups()
        return _iso(y, a, b), _iso(y, a, c)
    m = re.match(r"^([A-Za-z]+) (\d{1,2}),? (\d{4})$", t)
    if m:
        a, b, y = m.groups()
        return _iso(y, a, b), _iso(y, a, b)
    return "", ""


def _iso(y, mon, d):
    mi = MONTHS.get(mon.lower())
    if not mi:
        return ""
    try:
        return date(int(y), mi, int(d)).isoformat()
    except ValueError:
        return ""


def parse_sample(txt):
    t = clean(txt)
    m = re.search(r"([\d,]+)\s*\((LV|RV|A|V)\)", t)
    if m:
        return m.group(1).replace(",", ""), m.group(2)
    m = re.search(r"([\d,]{3,})", t)
    return (m.group(1).replace(",", "") if m else ""), ""


def pct(txt):
    t = clean(txt).replace("%", "")
    m = re.match(r"^-?\d+(\.\d+)?$", t)
    return float(t) if m else None


def split_pollster(raw):
    """'Pollster (R)[12][A]' -> (pollster, sponsor, partisan, internal).

    Wikipedia writes sponsor/pollster as 'Sponsor/Pollster' (e.g. 'New York Times/Siena').
    We keep the LAST slash-segment as the pollster and the rest as sponsor. The (D)/(R)
    marker denotes a partisan/campaign-sponsored poll -> partisan and internal=true."""
    t = clean(raw)
    partisan = ""
    m = re.search(r"\((D|R)\)\s*$", t)
    if m:
        partisan = m.group(1)
        t = t[:m.start()].strip()
    parts = [p.strip() for p in re.split(r"\s*/\s*", t) if p.strip()]
    if len(parts) >= 2:
        pollster, sponsor = parts[-1], "/".join(parts[:-1])
    else:
        pollster, sponsor = t, ""
    return pollster, sponsor, partisan, "true" if partisan else "false"


def section_html(html, section_id, stop="<h2"):
    i = html.find('id="%s"' % section_id)
    if i < 0:
        return ""
    seg = html[i:]
    j = seg.find(stop, 10)
    return seg[:j] if j > 0 else seg


def find_col(cols, pattern):
    for c in cols:
        if re.search(pattern, clean(c), re.I):
            return c
    return None


def wiki_tables(html, section_id, race, dem_pat, rep_pat, dem_candidate, rep_candidate,
                source_url, exclude_pat=None, require_all=None):
    """Parse every poll table in a section whose header has a D and an R column.

    Non-candidate numeric columns (third parties, Other, Undecided) are summed into other_pct;
    other_pct is blank when none of them is numeric."""
    seg = section_html(html, section_id)
    if not seg:
        print(f"WARNING: section {section_id} not found for {race}", file=sys.stderr)
        return []
    try:
        tables = pd.read_html(StringIO(seg))
    except ValueError:
        return []
    rows = []
    for t in tables:
        cols = [c if isinstance(c, str) else (" ".join(map(str, c)) if isinstance(c, tuple) else str(c))
                for c in t.columns]
        t.columns = cols
        src = find_col(cols, r"^Poll source")
        dcol = find_col(cols, dem_pat)
        rcol = find_col(cols, rep_pat)
        datec = find_col(cols, r"^Date")
        if not (src and dcol and rcol and datec):
            continue
        if exclude_pat and find_col(cols, exclude_pat):
            continue
        if require_all and not all(find_col(cols, p) for p in require_all):
            continue
        samplec = find_col(cols, r"^Sample size")
        skip = {src, dcol, rcol, datec, samplec, find_col(cols, r"^Margin of error")}
        others = [c for c in cols if c not in skip]
        for _, r in t.iterrows():
            start, end = parse_dates(r[datec])
            d, rp = pct(r[dcol]), pct(r[rcol])
            if not start or d is None or rp is None:
                continue  # separator rows (primary dates, events) or footnote-only cells
            pollster, sponsor, partisan, internal = split_pollster(r[src])
            if not pollster:
                continue
            n, pop = parse_sample(r[samplec]) if samplec else ("", "")
            oth = [pct(r[c]) for c in others]
            oth = [o for o in oth if o is not None]
            rows.append(dict(race=race, pollster=pollster, sponsor=sponsor, partisan=partisan,
                             start_date=start, end_date=end, sample_size=n, population=pop,
                             dem_pct=d, rep_pct=rp, other_pct=(round(sum(oth), 1) if oth else ""),
                             approve_pct="", disapprove_pct="",
                             dem_candidate=dem_candidate, rep_candidate=rep_candidate,
                             source_url=source_url, retrieved_at=RETRIEVED_AT, internal=internal))
    return rows


def read(fname):
    p = os.path.join(OUT, fname)
    if not os.path.exists(p):
        return ""
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


# ----------------------------------------------------------------------------- main
def main():
    for fname, url in SOURCES.items():
        fetch(fname, url)

    rows = []

    # (a) 2026 Texas governor: Abbott (R) vs Gina Hinojosa (D). Hypothetical pre-primary
    # matchups (e.g. Abbott vs Chris Bell) are excluded by requiring the Hinojosa column.
    u = SOURCES["wiki_2026_tx_gov.html"]
    h = read("wiki_2026_tx_gov.html")
    rows += wiki_tables(h, "Polling_3", "tx_gov", r"Gina Hinojosa", r"Greg Abbott",
                        "Gina Hinojosa", "Greg Abbott", u)
    # Texas generic ballot question that Wikipedia filed on the gov/sen pages (Aug 2025)
    rows += wiki_tables(h, "Polling_3", "tx_generic", r"^Generic Democrat", r"^Generic Republican",
                        "Generic Democrat", "Generic Republican", u)

    # (b) 2026 Texas US Senate: Ken Paxton (R, won May 26 2026 runoff over Cornyn) vs
    # James Talarico (D, won March 3 2026 primary). Hypothetical Cornyn/Hunt/Crockett/Allred
    # matchups are excluded by requiring both nominee columns.
    u = SOURCES["wiki_2026_tx_sen.html"]
    h = read("wiki_2026_tx_sen.html")
    rows += wiki_tables(h, "Polling_4", "tx_sen", r"James Talarico", r"Ken Paxton",
                        "James Talarico", "Ken Paxton", u)
    rows += wiki_tables(h, "Polling_4", "tx_generic", r"^Generic Democrat", r"^Generic Republican",
                        "Generic Democrat", "Generic Republican", u)

    # (c) Texas statewide generic congressional ballot (2026 US House elections in Texas page)
    u = SOURCES["wiki_2026_tx_house.html"]
    h = read("wiki_2026_tx_house.html")
    rows += wiki_tables(h, "Statewide_polling", "tx_generic", r"^Democratic", r"^Republican",
                        "Generic Democrat", "Generic Republican", u)

    # (e) national generic congressional ballot 2026 (Wikipedia keeps the full poll list on
    # the "2026 United States elections" page, section "Polling"; two tables: 2026 and 2025)
    u = SOURCES["wiki_2026_us_elections.html"]
    h = read("wiki_2026_us_elections.html")
    rows += wiki_tables(h, "Polling", "us_generic", r"^Democratic", r"^Republican",
                        "Generic Democrat", "Generic Republican", u)

    # (d) Abbott job approval: Texas Politics Project trend (Highcharts JSON embedded in page).
    # The page has several charts with the same title; the first in document order is the
    # overall electorate, the following ones are party subgroups.
    u = SOURCES["tpp_abbott_job_approval_trend.html"]
    h = read("tpp_abbott_job_approval_trend.html")
    tpp_rows = []
    for m in re.finditer(r'config\d+ = (\{"chart".*?\});\s*var chart', h, re.S):
        try:
            cfg = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if cfg.get("title", {}).get("text") == "Greg Abbott Job Approval Trend":
            tpp_rows = cfg["data"]["rows"]
            break
    # Field dates / sample sizes for TPP waves are taken from any "University of Texas/Texas
    # Politics Project" poll row in ANY table of the saved Wikipedia pages (including
    # hypothetical-matchup tables), matched on the year-month of the field end date. Waves
    # without a match keep blank dates; the wave label is always kept in `sponsor`.
    tpp_dates = {}
    for fname in [f for f in SOURCES if f.startswith("wiki_")]:
        page = read(fname)
        try:
            tables = pd.read_html(StringIO(page), match="Texas Politics Project")
        except ValueError:
            continue
        for t in tables:
            cols = [c if isinstance(c, str) else (" ".join(map(str, c)) if isinstance(c, tuple) else str(c))
                    for c in t.columns]
            t.columns = cols
            src, datec, samplec = (find_col(cols, r"^Poll source"), find_col(cols, r"^Date"),
                                   find_col(cols, r"^Sample size"))
            if not (src and datec):
                continue
            for _, r in t.iterrows():
                if "Texas Politics Project" not in clean(r[src]):
                    continue
                start, end = parse_dates(r[datec])
                if not end:
                    continue
                n, pop = parse_sample(r[samplec]) if samplec else ("", "")
                tpp_dates.setdefault(end[:7], (start, end, n, pop))
    for wave in tpp_rows[1:]:
        label, app, dis = wave[0], pct(wave[1]), pct(wave[2])
        m = re.match(r"([A-Za-z]+)\.? (\d{4})", label)
        if not m or app is None:
            continue
        mi, y = MONTHS.get(m.group(1).lower()), int(m.group(2))
        if not mi:
            continue
        if 2021 <= y <= 2022 and (y, mi) <= (2022, 11):
            race = "tx_abbott_approval_2022"
        elif y >= 2025:
            race = "tx_abbott_approval"
        else:
            continue
        ym = f"{y}-{mi:02d}"
        # Only the field dates are carried over. Wikipedia often lists a subsample (e.g. a
        # primary electorate or LV screen) for these polls, which is not the approval base,
        # so sample_size/population are left blank rather than guessed.
        start, end, _n, _pop = tpp_dates.get(ym, ("", "", "", ""))
        rows.append(dict(race=race, pollster="Texas Politics Project", sponsor=f"University of Texas at Austin (wave: {label})",
                         partisan="", start_date=start, end_date=end, sample_size="", population="",
                         dem_pct="", rep_pct="", other_pct="", approve_pct=app, disapprove_pct=dis,
                         dem_candidate="", rep_candidate="Greg Abbott", source_url=u,
                         retrieved_at=RETRIEVED_AT, internal="false"))

    # ---------------- backtest races
    u = SOURCES["wiki_2022_tx_gov.html"]
    h = read("wiki_2022_tx_gov.html")
    rows += wiki_tables(h, "Polling_3", "tx_gov_2022", r"Beto O'Rourke", r"Greg Abbott",
                        "Beto O'Rourke", "Greg Abbott", u, exclude_pat=r"McConaughey")

    u = SOURCES["wiki_2024_tx_pres.html"]
    h = read("wiki_2024_tx_pres.html")
    rows += wiki_tables(h, "Polling", "tx_pres_2024", r"Kamala Harris", r"Donald Trump",
                        "Kamala Harris", "Donald Trump", u)
    rows += wiki_tables(h, "Polling", "tx_pres_2024", r"Joe Biden", r"Donald Trump",
                        "Joe Biden", "Donald Trump", u)

    u = SOURCES["wiki_2024_tx_sen.html"]
    h = read("wiki_2024_tx_sen.html")
    rows += wiki_tables(h, "Polling_3", "tx_sen_2024", r"Colin Allred", r"Ted Cruz",
                        "Colin Allred", "Ted Cruz", u)

    # national generic ballot 2022 / 2024 from the FiveThirtyEight historical CSV (wide format)
    fte = os.path.join(OUT, "fte_generic_ballot_polls_historical_wayback20250305.csv")
    if os.path.exists(fte):
        d = pd.read_csv(fte, low_memory=False)
        d = d[d["cycle"].isin([2022, 2024])].copy()
        for c in ["start_date", "end_date", "election_date"]:
            d[c] = pd.to_datetime(d[c], format="%m/%d/%y", errors="coerce")
        d = d[d["end_date"] <= d["election_date"]]
        for _, r in d.iterrows():
            if pd.isna(r["dem"]) or pd.isna(r["rep"]):
                continue
            part = {"DEM": "D", "REP": "R"}.get(str(r["partisan"]).upper(), "")
            internal = "true" if (r["internal"] is True or str(r["internal"]).lower() == "true" or part) else "false"
            n = "" if pd.isna(r["sample_size"]) else str(int(r["sample_size"]))
            pop = str(r["population"]).upper() if not pd.isna(r["population"]) else ""
            ind = r["ind"] if not pd.isna(r["ind"]) else None
            rows.append(dict(race=f"us_generic_{int(r['cycle'])}", pollster=r["pollster"],
                             sponsor=("" if pd.isna(r["sponsors"]) else r["sponsors"]), partisan=part,
                             start_date=r["start_date"].date().isoformat(), end_date=r["end_date"].date().isoformat(),
                             sample_size=n, population=pop, dem_pct=r["dem"], rep_pct=r["rep"],
                             other_pct=(ind if ind is not None else ""), approve_pct="", disapprove_pct="",
                             dem_candidate="Generic Democrat", rep_candidate="Generic Republican",
                             source_url=SOURCES["fte_generic_ballot_polls_historical_wayback20250305.csv"],
                             retrieved_at=RETRIEVED_AT, internal=internal))

    df = pd.DataFrame(rows, columns=COLUMNS)
    key = ["race", "pollster", "sponsor", "start_date", "end_date", "sample_size", "population",
           "dem_pct", "rep_pct", "approve_pct", "dem_candidate"]
    before = len(df)
    df = df.drop_duplicates(subset=key)  # same poll filed on two Wikipedia pages
    df = df.sort_values(["race", "end_date", "pollster"], ascending=[True, False, True]).reset_index(drop=True)
    df.to_csv(os.path.join(OUT, "polls.csv"), index=False)
    print(f"wrote polls.csv: {len(df)} rows ({before - len(df)} duplicates dropped)")
    print(df.groupby("race").agg(n=("race", "size"), first=("end_date", "min"), last=("end_date", "max")).to_string())

    MANIFEST.append({"file": "polls.csv", "url": "(derived from files above)", "retrieved_at": RETRIEVED_AT,
                     "description": DESCRIPTIONS["polls.csv"], "rows": int(len(df))})
    with open(os.path.join(OUT, "manifest.json"), "w") as f:
        json.dump(MANIFEST, f, indent=1)


if __name__ == "__main__":
    main()
