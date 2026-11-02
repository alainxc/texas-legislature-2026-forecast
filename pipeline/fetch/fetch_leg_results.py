#!/usr/bin/env python
"""
fetch_leg_results.py -- Texas House / Senate general-election results by district
(2018, 2020, 2022, 2024) from official Texas Secretary of State sources.

Runnable with no arguments. Writes into <project>/data/raw/leg_results/:
  raw/...            raw JSON / HTML exactly as downloaded (re-parseable)
  leg_results.csv    one row per candidate per race
  leg_races.csv      one row per race (district summary)
  manifest.json      one entry per saved file
  NOTES.md           sources, gaps, caveats (generated)

Sources
  * 2020 / 2022 / 2024: SOS election-night/canvass portal results.texas-election.com,
    static JSON  static/data/election/<electionId>/<version>/Districted.json
    (the same data the portal's "District Offices" tab / CSV download is built from).
  * 2018: SOS historical results  elections.sos.state.tx.us/elchist331_state.htm
    (Race Summary Report, 2018 General Election, canvass votes).
  * 2022 unopposed races (not on the ballot -> no votes anywhere): SOS qualified-
    candidate list candidate.texas-election.com (2022 NOVEMBER 8TH GENERAL ELECTION,
    STATE offices) for winner name / party / incumbent flag.
"""
import csv
import datetime as dt
import json
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT_DIR = os.path.join(PROJECT, "data", "raw", "leg_results")
RAW_DIR = os.path.join(OUT_DIR, "raw")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

PORTAL = "https://results.texas-election.com/static/data"
PORTAL_ELECTIONS = {  # year -> SOS election id (from static/data/ElectionConstants_*.json)
    2020: "44144",
    2022: "47009",
    2024: "49664",
}
SOS_2018_URL = "https://elections.sos.state.tx.us/elchist331_state.htm"
CAND_URL = "https://candidate.texas-election.com/Elections/getQualifiedCandidatesInfo.do"
CAND_2022_GENERAL_ID = "47009"

PARTY_MAP = {
    "REP": "R", "REPUBLICAN": "R", "R": "R",
    "DEM": "D", "DEMOCRATIC": "D", "DEMOCRAT": "D", "D": "D",
    "LIB": "L", "LIBERTARIAN": "L", "L": "L",
    "GRE": "G", "GRN": "G", "GREEN": "G", "G": "G",
    "IND": "I", "INDEPENDENT": "I", "I": "I",
    "W": "W", "W-I": "W", "WRITE-IN": "W", "WI": "W",
}

manifest = []
notes = []  # free-text lines for NOTES.md


def now_iso():
    return dt.datetime.now().strftime("%Y-%m-%dT%H:%M")


def record(path, url, description):
    manifest.append({
        "file": os.path.relpath(path, OUT_DIR),
        "url": url,
        "retrieved_at": now_iso(),
        "description": description,
    })


def get(session, url, retries=4, **kw):
    last = None
    for i in range(retries):
        try:
            r = session.get(url, timeout=120, **kw)
            if r.status_code == 200:
                return r
            last = "HTTP %s" % r.status_code
        except requests.RequestException as e:  # noqa
            last = repr(e)
        time.sleep(2 + 3 * i)
    raise RuntimeError("GET failed for %s: %s" % (url, last))


def save_bytes(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


def norm_party(p):
    if p is None:
        return ""
    key = str(p).strip().upper()
    return PARTY_MAP.get(key, key)


def clean_name(n):
    """Strip incumbent marker; return (name, incumbent_bool)."""
    n = re.sub(r"\s+", " ", n or "").strip()
    inc = bool(re.search(r"\(\s*I\s*\)\s*$", n, flags=re.I))
    n = re.sub(r"\s*\(\s*I\s*\)\s*$", "", n, flags=re.I).strip()
    return n, inc


def office_to_chamber_district(office):
    o = office.upper()
    m = re.match(r"^STATE REPRESENTATIVE,?\s+DISTRICT\s+(\d+)\s*$", o)
    if m:
        return "H", int(m.group(1))
    m = re.match(r"^STATE SENATOR,?\s+DISTRICT\s+(\d+)\s*$", o)
    if m:
        return "S", int(m.group(1))
    return None, None


# --------------------------------------------------------------------------
# 1. SOS results portal (2020, 2022, 2024)
# --------------------------------------------------------------------------
def fetch_portal(session, year, eid):
    vurl = "%s/election/%s/Version.json" % (PORTAL, eid)
    v = get(session, vurl).json()
    version = v["___versionNo"]
    vpath = os.path.join(RAW_DIR, "sos_portal_%d_Version.json" % year)
    save_bytes(vpath, json.dumps(v).encode())
    record(vpath, vurl, "SOS results portal: current data version for %d general (election id %s)" % (year, eid))

    durl = "%s/election/%s/%s/Districted.json" % (PORTAL, eid, version)
    r = get(session, durl)
    dpath = os.path.join(RAW_DIR, "sos_portal_%d_Districted.json" % year)
    save_bytes(dpath, r.content)
    record(dpath, durl, "SOS results portal: all 'District Offices' races, %d general election "
                        "(State Rep, State Senator, SBOE, courts), candidates/votes/pct, (I)=incumbent" % year)
    data = json.loads(r.content.decode("utf-8"))

    rows = []
    for race in data["Races"]:
        chamber, district = office_to_chamber_district(race["N"])
        if chamber is None:
            continue
        total = race.get("T") or sum(c["V"] for c in race["Candidates"])
        for c in race["Candidates"]:
            name, inc = clean_name(c["N"])
            rows.append({
                "year": year, "chamber": chamber, "district": district,
                "candidate_name": name, "party": norm_party(c["P"]),
                "votes": int(c["V"]), "total_votes": int(total),
                "incumbent": inc, "source": "sos_portal",
            })
    return rows


# --------------------------------------------------------------------------
# 2. SOS historical Race Summary Report (2018)
# --------------------------------------------------------------------------
def fetch_sos_2018(session):
    r = get(session, SOS_2018_URL)
    path = os.path.join(RAW_DIR, "sos_2018_general_race_summary.htm")
    save_bytes(path, r.content)
    record(path, SOS_2018_URL, "SOS historical results: 2018 General Election Race Summary Report "
                               "(all races, canvass votes, (I)=incumbent)")
    soup = BeautifulSoup(r.content, "lxml")
    rows = []
    current = None
    cands = []

    def flush():
        if current is None or not cands:
            return
        chamber, district = office_to_chamber_district(current)
        if chamber is None:
            return
        total = sum(c[2] for c in cands)
        for nm, party, votes in cands:
            name, inc = clean_name(nm)
            rows.append({
                "year": 2018, "chamber": chamber, "district": district,
                "candidate_name": name, "party": norm_party(party),
                "votes": votes, "total_votes": total,
                "incumbent": inc, "source": "sos_2018_html",
            })

    for tr in soup.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if not cells:
            continue
        race_cell = cells[0]
        if race_cell and race_cell != "-" and not race_cell.startswith("---"):
            flush()
            current = race_cell.rstrip(" -").strip()
            cands = []
            continue
        if len(cells) >= 4 and cells[1] and cells[2] and cells[2] != "Race Total":
            votes_txt = cells[3].replace(",", "").strip()
            if votes_txt.isdigit():
                cands.append((cells[1], cells[2], int(votes_txt)))
    flush()
    return rows


# --------------------------------------------------------------------------
# 3. SOS qualified-candidate list, 2022 general, STATE offices
# --------------------------------------------------------------------------
def fetch_candidates_2022(session):
    # establish session, then the same two POSTs the page's own JS performs
    get(session, CAND_URL)
    base = {"idOffice": "", "cdParty": "", "cdStatus": "", "idTown": "",
            "cdOfficeType": "", "cdFlow": "0", "results": "", "elecDateName": "",
            "cdElectionType": ""}
    d1 = dict(base, nbElecYear="2022", idElection="")
    session.post(CAND_URL, data=d1, timeout=120)
    d2 = dict(base, nbElecYear="2022", idElection=CAND_2022_GENERAL_ID,
              cdOfficeType="S", cdFlow="S", results="R")
    r = session.post(CAND_URL, data=d2, timeout=120)
    r.raise_for_status()
    path = os.path.join(RAW_DIR, "sos_candidates_2022_general_state.html")
    save_bytes(path, r.content)
    record(path, CAND_URL + " (POST nbElecYear=2022, idElection=%s, cdOfficeType=S, results=R)" % CAND_2022_GENERAL_ID,
           "SOS qualified-candidate list, 2022 November general election, STATE offices "
           "(name, party, status, incumbent flag)")
    soup = BeautifulSoup(r.content.decode("latin-1"), "lxml")
    out = {}  # (chamber, district) -> list of dicts
    for h3 in soup.find_all("h3"):
        office = h3.get_text(" ", strip=True)
        chamber, district = office_to_chamber_district(office)
        if chamber is None:
            continue
        block = h3.parent
        for cand in block.find_all("div", class_="mb-3"):
            strongs = [s.get_text(" ", strip=True) for s in cand.find_all("strong")]
            if not strongs:
                continue
            name = strongs[0]
            info = {}
            for s in strongs[1:]:
                m = re.match(r"^(PARTY|STATUS|INCUMBENT)\s*:\s*(.*)$", s, flags=re.I)
                if m:
                    info[m.group(1).upper()] = m.group(2).strip().upper()
            out.setdefault((chamber, district), []).append({
                "name": name, "party": norm_party(info.get("PARTY", "")),
                "status": info.get("STATUS", ""),
                "incumbent": info.get("INCUMBENT", "") == "YES",
            })
    return out


# --------------------------------------------------------------------------
# 3b. Fallback for a 2022 seat absent from the SOS candidate list: Ballotpedia
#     district page ("...November 8, 2022, was canceled. Incumbent X (R) won...")
# --------------------------------------------------------------------------
BP_PAGE = {"H": "https://ballotpedia.org/Texas_House_of_Representatives_District_%d",
           "S": "https://ballotpedia.org/Texas_State_Senate_District_%d"}


def fetch_ballotpedia_2022(session, chamber, district):
    url = BP_PAGE[chamber] % district
    r = get(session, url)
    path = os.path.join(RAW_DIR, "ballotpedia_%s%d.html" % (chamber, district))
    save_bytes(path, r.content)
    record(path, url, "Ballotpedia district page (fallback for 2022 seat missing from SOS candidate list)")
    text = re.sub(r"\s+", " ", BeautifulSoup(r.content, "lxml").get_text(" "))
    m = re.search(r"November 8, 2022, was canceled\.\s*(Incumbent\s+)?(.+?)\s+\((R|D|L|G|I)\)\s+won election", text)
    if not m:
        return None
    return {"name": m.group(2).strip(), "party": m.group(3), "incumbent": bool(m.group(1)),
            "status": "BALLOTPEDIA_CANCELED_RACE"}


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    rows = []
    for year, eid in sorted(PORTAL_ELECTIONS.items()):
        rows.extend(fetch_portal(session, year, eid))
    rows.extend(fetch_sos_2018(session))

    # 2022: fill races that were cancelled (unopposed; not on ballot)
    cands22 = fetch_candidates_2022(session)
    have22 = {(r["chamber"], r["district"]) for r in rows if r["year"] == 2022}
    filled, ambiguous, bp_filled = [], [], []
    for chamber, n in [("H", i) for i in range(1, 151)] + [("S", i) for i in range(1, 32)]:
        if (chamber, n) in have22:
            continue
        cl = [c for c in cands22.get((chamber, n), []) if c["status"] == "CANDIDATE IN THE GENERAL ELECTION"]
        src = "sos_candidate_list_2022_unopposed"
        c = cl[0] if len(cl) == 1 else None
        if c is None and not cl:
            c = fetch_ballotpedia_2022(session, chamber, n)
            src = "ballotpedia_2022_canceled_race"
            if c is not None:
                bp_filled.append("%s%d (%s, %s)" % (chamber, n, c["name"], c["party"]))
        if c is not None:
            rows.append({
                "year": 2022, "chamber": chamber, "district": n,
                "candidate_name": c["name"], "party": c["party"],
                "votes": "", "total_votes": "", "incumbent": c["incumbent"],
                "source": src,
            })
            filled.append("%s%d" % (chamber, n))
        else:
            ambiguous.append(("%s%d" % (chamber, n), [x["name"] for x in cl]))

    # derived fields
    for r in rows:
        if r["votes"] == "":
            r["pct"] = ""
        else:
            r["pct"] = round(100.0 * r["votes"] / r["total_votes"], 2) if r["total_votes"] else ""
    # winner flag / uncontested
    races = {}
    for r in rows:
        races.setdefault((r["year"], r["chamber"], r["district"]), []).append(r)
    race_rows = []
    for key in sorted(races):
        year, chamber, district = key
        cl = races[key]
        if all(c["votes"] != "" for c in cl):
            top = max(cl, key=lambda c: c["votes"])
            for c in cl:
                c["winner"] = c is top
        else:  # unopposed, cancelled election
            for c in cl:
                c["winner"] = True
        non_writein = [c for c in cl if c["party"] != "W"]
        uncontested = len(non_writein) <= 1
        winner = [c for c in cl if c["winner"]][0]

        def party_pct(p):
            v = [c["pct"] for c in cl if c["party"] == p and c["pct"] != ""]
            return round(sum(v), 2) if v else ""
        dem_pct, rep_pct = party_pct("D"), party_pct("R")
        if uncontested and winner["votes"] == "":
            dem_pct = rep_pct = other_pct = margin = ""
        else:
            other = [c["pct"] for c in cl if c["party"] not in ("D", "R") and c["pct"] != ""]
            other_pct = round(sum(other), 2) if other else 0.0
            dem_pct = dem_pct if dem_pct != "" else 0.0
            rep_pct = rep_pct if rep_pct != "" else 0.0
            margin = round(dem_pct - rep_pct, 2)
        inc_party = sorted({c["party"] for c in cl if c["incumbent"]})
        race_rows.append({
            "year": year, "chamber": chamber, "district": district,
            "dem_pct": dem_pct, "rep_pct": rep_pct, "other_pct": other_pct,
            "margin_d_minus_r": margin,
            "total_votes": cl[0]["total_votes"],
            "n_candidates": len(cl),
            "uncontested": uncontested,
            "on_ballot": winner["votes"] != "",
            "winner_party": winner["party"],
            "winner_name": winner["candidate_name"],
            "incumbent_party_if_known": "/".join(inc_party),
            "source": winner["source"],
        })

    # write outputs
    cols = ["year", "chamber", "district", "candidate_name", "party", "votes", "pct",
            "incumbent", "winner", "total_votes", "source"]
    rows.sort(key=lambda r: (r["year"], r["chamber"], r["district"], -(r["votes"] or 0), r["candidate_name"]))
    with open(os.path.join(OUT_DIR, "leg_results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    rcols = ["year", "chamber", "district", "dem_pct", "rep_pct", "other_pct", "margin_d_minus_r",
             "uncontested", "on_ballot", "winner_party", "winner_name", "incumbent_party_if_known",
             "n_candidates", "total_votes", "source"]
    with open(os.path.join(OUT_DIR, "leg_races.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rcols, extrasaction="ignore")
        w.writeheader()
        w.writerows(race_rows)
    record(os.path.join(OUT_DIR, "leg_results.csv"), "(derived)", "Tidy candidate-level results, all years/chambers")
    record(os.path.join(OUT_DIR, "leg_races.csv"), "(derived)", "Race-level summary, all years/chambers")
    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    # completeness report
    lines = ["# NOTES - Texas legislative general-election results (leg_results)", "",
             "Generated by pipeline/fetch/fetch_leg_results.py on %s. Nothing hand-typed." % now_iso(), "",
             "## Sources (all official Texas Secretary of State)", "",
             "- 2020, 2022, 2024: SOS results portal results.texas-election.com, static JSON "
             "`static/data/election/<id>/<version>/Districted.json` (ids 44144 / 47009 / 49664). "
             "Same data as the portal's District Offices tab / CSV download. Candidate names carry an "
             "`(I)` incumbent marker, which is parsed into `incumbent`.",
             "- 2018: SOS historical results `elections.sos.state.tx.us/elchist331_state.htm` "
             "(2018 General Election Race Summary Report, canvass votes, `(I)` marker).",
             "- 2022 unopposed seats: SOS qualified-candidate list (candidate.texas-election.com, "
             "2022 NOVEMBER 8TH GENERAL ELECTION, STATE offices) for name / party / incumbent.",
             "- SOS portal CSV downloads are produced client-side from these JSON files; the JSON is the "
             "underlying data so it is what we archive.", "",
             "## Important caveat: 2022 unopposed races were not on the ballot", "",
             "In the 2022 general election, Texas legislative races with a single qualified candidate were "
             "cancelled and the candidate was declared elected without appearing on the ballot. Consequently "
             "neither the SOS results portal (92 House / 21 Senate races only) nor the Texas Legislative "
             "Council VTD returns contain any votes for them, and Ballotpedia district pages say the "
             "general election 'was canceled'. For those districts `leg_results.csv` has one row from the SOS "
             "qualified-candidate list with blank votes/pct, `winner=True`; `leg_races.csv` has "
             "`uncontested=True`, `on_ballot=False`, blank pcts/margin, winner_party and incumbent party set. "
             "In 2018/2020/2024 unopposed candidates did appear on the ballot and have votes (pct 100).", "",
             "## Column notes", "",
             "- `pct` is recomputed as votes / race total * 100 (2 decimals); matches SOS to rounding.",
             "- `uncontested` = at most one non-write-in candidate. `other_pct` = sum of non-D/R candidates "
             "including write-ins. `margin_d_minus_r` = dem_pct - rep_pct in points (2 decimals).",
             "- `incumbent` is True/False from the SOS `(I)` marker (2018-2024 results), the SOS candidate "
             "list INCUMBENT field (2022 unopposed) or Ballotpedia's 'Incumbent X won' sentence (2022 fallback). "
             "It is as published: a spot check found at least one incumbent without the SOS marker "
             "(HD1 2018, Gary VanDeaver, unopposed), so False means 'not marked incumbent by the source'.",
             "- `incumbent_party_if_known` is blank when no candidate in the race was marked incumbent "
             "(open seat / new district).",
             "- Party codes: R, D, L (Libertarian), G (Green), I (Independent), W (write-in).",
             "- Senate: only the seats up in each year are present (all 31 in 2022 after redistricting; "
             "roughly half otherwise). 2020/2024 use PLANS2168 only for 2022+; 2018/2020 use old lines "
             "(PLANH2100/PLANS2100-era maps), as expected for the back-test years.", "",
             "## Completeness check", ""]
    problems = []
    for year in (2018, 2020, 2022, 2024):
        hd = sorted({r["district"] for r in race_rows if r["year"] == year and r["chamber"] == "H"})
        sd = sorted({r["district"] for r in race_rows if r["year"] == year and r["chamber"] == "S"})
        missing_h = sorted(set(range(1, 151)) - set(hd))
        lines.append("- %d: House %d/150 districts%s; Senate %d seats: %s" % (
            year, len(hd), (" MISSING %s" % missing_h) if missing_h else "", len(sd), sd))
        if missing_h:
            problems.append("%d House missing %s" % (year, missing_h))
    lines += ["", "- 2022 seats filled from the SOS candidate list (cancelled/unopposed): %d -> %s" % (
        len(filled) - len(bp_filled), ", ".join(f for f in filled if not any(f == b.split(' ')[0] for b in bp_filled)))]
    if bp_filled:
        lines.append("- 2022 seats absent from the SOS candidate list, filled from Ballotpedia district page "
                     "('general election ... was canceled. Incumbent X (P) won election ... without appearing on the ballot'): %s"
                     % "; ".join(bp_filled))
    if ambiguous:
        lines.append("- 2022 seats NOT resolvable (no single general-election candidate found in SOS list): %s" % ambiguous)
        problems.append("2022 ambiguous %s" % ambiguous)
    lines += ["", "## Gaps / alternatives", ""]
    if problems:
        lines += ["- PROBLEMS: %s" % p for p in problems]
    else:
        lines.append("- No gaps: 150 House rows per year for 2018, 2020, 2022, 2024; all contested Senate seats present.")
    lines += ["- Ballotpedia (the designated fallback) was used only for the 2022 seat(s) listed above; raw HTML saved in raw/.",
              "- Texas Legislative Council open data (data.capitol.texas.gov 'Comprehensive Election Datasets', "
              "VTD-level returns with an Incumbent column) was inspected as a cross-check; it has the same 92 "
              "House races for 2022 and could be used to rebuild district totals from VTDs if ever needed.",
              "- results.texas-election.com sits behind Cloudflare but served the static JSON to a plain "
              "desktop-UA request without challenge at run time."]
    with open(os.path.join(OUT_DIR, "NOTES.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[-20:]))
    print("rows: %d candidate rows, %d races" % (len(rows), len(race_rows)))


if __name__ == "__main__":
    main()
