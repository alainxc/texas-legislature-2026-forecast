#!/usr/bin/env python
"""
fetch_senate_candidates.py  --  Texas Senate 2026 general election: seats up,
candidates, chamber composition / special elections, and map confirmation.

Runs with no arguments. Writes into <project>/data/raw/ballotpedia/ :
  senate_*.html / senate_*.txt           raw pages that were parsed (re-parsable)
  senate_seats_up_2026.json              which of the 31 districts are on the Nov 3, 2026 ballot
  senate_candidates_2026.csv             one row per general-election candidate
  senate_districts_2026.csv              one row per seat up
  senate_control_2026.json               current composition + 2025-2026 special elections
  maps_confirmation.json                 PLANS2168 / PLANH2316 still in force for 2026
  manifest.json                          merged (entries for files written here are replaced;
                                         entries written by other scripts are kept)

Public sources only. Nothing is hard-coded except URLs and the regexes needed to
parse the pages; every list of districts / names is derived from the saved pages.
"""
import csv
import datetime as dt
import html as htmllib
import json
import os
import re
import sys
import time
import unicodedata

import requests
from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(PROJECT, "data", "raw", "ballotpedia")
os.makedirs(OUT, exist_ok=True)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})

SOURCES = {
    # key: (url, local filename, description)
    "bp_sen2026": ("https://ballotpedia.org/Texas_State_Senate_elections,_2026",
                   "senate_ballotpedia_elections_2026.html",
                   "Ballotpedia: Texas State Senate elections, 2026 (general/primary candidate tables, open seats)"),
    "bp_sen2024": ("https://ballotpedia.org/Texas_State_Senate_elections,_2024",
                   "senate_ballotpedia_elections_2024.html",
                   "Ballotpedia: Texas State Senate elections, 2024 (complement check: seats NOT up in 2026)"),
    "bp_senate": ("https://ballotpedia.org/Texas_State_Senate",
                  "senate_ballotpedia_chamber.html",
                  "Ballotpedia: Texas State Senate chamber page (current members, partisan composition, vacancies)"),
    "bp_spec2025": ("https://ballotpedia.org/Texas_state_legislative_special_elections,_2025",
                    "senate_ballotpedia_special_elections_2025.html",
                    "Ballotpedia: Texas state legislative special elections, 2025"),
    "bp_spec2026": ("https://ballotpedia.org/Texas_state_legislative_special_elections,_2026",
                    "senate_ballotpedia_special_elections_2026.html",
                    "Ballotpedia: Texas state legislative special elections, 2026"),
    "bp_redist2020": ("https://ballotpedia.org/Redistricting_in_Texas_after_the_2020_census",
                      "senate_ballotpedia_redistricting_2020_census.html",
                      "Ballotpedia: Redistricting in Texas after the 2020 census (2023 re-enactment of 2021 legislative maps)"),
    "bp_redist2026": ("https://ballotpedia.org/Redistricting_in_Texas_ahead_of_the_2026_elections",
                      "senate_ballotpedia_redistricting_ahead_of_2026.html",
                      "Ballotpedia: Redistricting in Texas ahead of the 2026 elections (2025 mid-decade congressional redraw)"),
    "tlc_home": ("https://redistricting.capitol.texas.gov/",
                 "senate_tlc_redistricting_home.html",
                 "Texas Legislative Council redistricting site: statement of plans in effect for the 2026 elections"),
    "trib_lots": ("https://www.texastribune.org/2023/01/11/texas-senate-2023-terms/",
                  "senate_texastribune_2023_term_lottery.html",
                  "Texas Tribune, Jan 11 2023: full list of senators drawing 2-year vs 4-year terms after redistricting"),
    "lrl_88": ("https://lrl.texas.gov/legeLeaders/members/membersearch.cfm?leg=88&chamber=S",
               "senate_lrl_members_88th.html",
               "Legislative Reference Library: Senate members of the 88th Legislature (name -> district map for the 2023 lottery)"),
    "lrl_89": ("https://lrl.texas.gov/legeLeaders/members/membersearch.cfm?leg=89&chamber=S",
               "senate_lrl_members_89th.html",
               "Legislative Reference Library: Senate members of the 89th Legislature with term years (official cross-check)"),
    "sos_portal": ("https://candidate.texas-election.com/Elections/getQualifiedCandidatesInfo.do",
                   "senate_sos_candidate_portal_2026_probe.html",
                   "Texas SOS qualified-candidate portal, POST nbElecYear=2026 (probe; portal lists no 2026 elections)"),
}

NOW = dt.datetime.now().strftime("%Y-%m-%dT%H:%M")
manifest_entries = []


def save_raw(key, content, note=None):
    url, fname, desc = SOURCES[key]
    path = os.path.join(OUT, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    manifest_entries.append({"file": fname, "url": url, "retrieved_at": NOW,
                             "description": desc + (f" [{note}]" if note else "")})
    return path


def fetch(key, method="GET", data=None):
    url, fname, desc = SOURCES[key]
    last = None
    for attempt in range(3):
        try:
            r = SESSION.request(method, url, data=data, timeout=60)
            r.raise_for_status()
            r.encoding = r.encoding or "utf-8"
            save_raw(key, r.text)
            return r.text
        except Exception as e:  # noqa
            last = e
            time.sleep(2 + 2 * attempt)
    print(f"WARNING: could not fetch {url}: {last}", file=sys.stderr)
    return None


def add_output(fname, url, desc):
    manifest_entries.append({"file": fname, "url": url, "retrieved_at": NOW, "description": desc})


def text_of(node):
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def plain_text(html):
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
    t = htmllib.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"[ \t\xa0]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n", t)


def norm_name(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r'["\'“”‘’]', "", s)
    s = re.sub(r"\b(jr|sr|ii|iii)\b\.?", "", s, flags=re.I)
    return re.sub(r"[^a-z ]", "", s.lower()).strip()


def party_code(raw):
    r = (raw or "").lower()
    if "democrat" in r:
        return "D"
    if "republican" in r:
        return "R"
    if "libertarian" in r:
        return "L"
    if "green" in r:
        return "G"
    if "independent" in r or "nonpartisan" in r or "no party" in r:
        return "I"
    return "Other" if r else ""


# --------------------------------------------------------------------------- 1
# Ballotpedia 2026 general-election table
def parse_general_table(html, heading="Texas State Senate general election, 2026"):
    soup = BeautifulSoup(html, "lxml")
    # heading appears as "... general election, 2026" (2026 page) or "... general election 2024" (2024 page)
    pat = re.compile(re.escape(heading).replace(",\\ ", ",?\\s*").replace("\\ ", "\\s+"))
    table = None
    for tb in soup.find_all("table"):
        cap = tb.get_text(" ", strip=True)[:120]
        if pat.search(cap) and tb.find("a", href=re.compile(r"Texas_State_Senate_District_\d+")):
            table = tb
            break
    if table is None:
        raise RuntimeError(f"general election table not found for heading {heading!r}")
    cands, districts = [], []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 2:
            continue
        m = re.search(r"District (\d+)", text_of(tds[0]))
        if not m or not tds[0].find("a", href=re.compile(r"Texas_State_Senate_District_\d+")):
            continue
        d = int(m.group(1))
        districts.append(d)
        col_party = {1: "Democratic", 2: "Republican", 3: "Other"}
        for idx, td in enumerate(tds[1:], start=1):
            colparty = col_party.get(idx, "Other")
            # candidates who made the ballot
            for span in td.find_all("span", class_="candidate"):
                a = span.find("a", href=re.compile(r"^https://ballotpedia\.org/(?!.*#)"))
                if not a:
                    continue
                name = text_of(a)
                stxt = text_of(span)
                inc = "(i)" in stxt
                praw = colparty
                if colparty == "Other":
                    pm = re.search(r"\(([^()]*(?:Party|Independent|Libertarian|Green|Write-in)[^()]*)\)", stxt)
                    praw = pm.group(1).strip() if pm else "Other"
                cands.append(dict(district=d, candidate_name=name, party=party_code(praw), party_raw=praw,
                                  incumbent=inc, withdrew=False, did_not_make_ballot=False,
                                  ballotpedia_url=a["href"]))
            # "Did not make the ballot:" / "Withdrew:" blocks
            for div in td.find_all("div"):
                dtxt = text_of(div)
                flag_dnmb = "did not make the ballot" in dtxt.lower()
                flag_wd = "withdr" in dtxt.lower()
                if not (flag_dnmb or flag_wd):
                    continue
                for a in div.find_all("a", href=re.compile(r"^https://ballotpedia\.org/")):
                    name = text_of(a)
                    tail = a.next_sibling
                    tail_txt = ""
                    while tail is not None and getattr(tail, "name", None) != "a":
                        tail_txt += tail if isinstance(tail, str) else tail.get_text(" ")
                        if getattr(tail, "name", None) == "br":
                            break
                        tail = tail.next_sibling
                    pm = re.search(r"\(([^()]+)\)", tail_txt)
                    praw = pm.group(1).strip() if pm else colparty
                    cands.append(dict(district=d, candidate_name=name, party=party_code(praw), party_raw=praw,
                                      incumbent="(i)" in tail_txt, withdrew=flag_wd,
                                      did_not_make_ballot=flag_dnmb, ballotpedia_url=a["href"]))
    return sorted(set(districts)), cands


def parse_composition(html):
    """'Partisan composition, Texas State Senate As of ... Democratic 12 Republican 18 Other 0 Vacancies 1 Total 31'"""
    t = re.sub(r"\s+", " ", plain_text(html))
    m = re.search(r"Partisan composition, Texas State Senate As of ([A-Za-z]+ \d{4}).*?Democratic (\d+) Republican (\d+) "
                  r"Other (\d+) Vacanc(?:y|ies) (\d+) Total (\d+)", t)
    if not m:
        return None
    return {"as_of": m.group(1), "D": int(m.group(2)), "R": int(m.group(3)), "other": int(m.group(4)),
            "vacant": int(m.group(5)), "total": int(m.group(6))}


def parse_members(html):
    """Ballotpedia chamber page 'Leadership and members' table -> {district: (name, party, assumed)}"""
    soup = BeautifulSoup(html, "lxml")
    members = {}
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue
        m = re.match(r"Texas State Senate District (\d+)$", text_of(tds[0]))
        if not m:
            continue
        d = int(m.group(1))
        name = text_of(tds[1])
        party = text_of(tds[2]) if len(tds) > 2 else ""
        assumed = text_of(tds[3]) if len(tds) > 3 else ""
        if name.lower() == "vacant":
            members[d] = {"name": "", "party": "", "assumed_office": "", "vacant": True}
        else:
            members[d] = {"name": name, "party": party, "assumed_office": assumed, "vacant": False}
    return members


def parse_retiring(html):
    """'Retiring incumbents' table (Name / Party / Office) on the Ballotpedia elections page."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    h = soup.find(id="Retiring_incumbents")
    if not h:
        return out
    tb = h.find_next("table")
    if not tb:
        return out
    for tr in tb.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        m = re.search(r"Senate District (\d+)", text_of(tds[2]))
        if m:
            out.append({"name": text_of(tds[0]), "party": party_code(text_of(tds[1])), "district": int(m.group(1))})
    return out


# --------------------------------------------------------------------------- 2
# Special elections (Ballotpedia yearly pages)
def parse_special_elections(html, year_page):
    """Each Senate special election sits in a collapsible table whose first <th> links
    'Texas State Senate District N'; the preceding <h3> is the election date; results are
    in div.votebox blocks (latest round first)."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.find_all("a", string=re.compile(r"^Texas State Senate District \d+$")):
        th = a.find_parent("th")
        if th is None:
            continue
        table = th.find_parent("table")
        d = int(re.search(r"(\d+)", a.get_text()).group(1))
        h3 = table.find_previous("h3")
        seg_txt = re.sub(r"\s+", " ", table.get_text(" ", strip=True))
        rec = {"district": d, "source_page": year_page, "section_date": text_of(h3) if h3 else ""}
        dm = re.search(r"special election for Texas State Senate District \d+ (?:was|has been) called for ([A-Z][a-z]+ \d+, \d{4})", seg_txt)
        rec["election_date"] = dm.group(1) if dm else ""
        rm = re.search(r"runoff took place on ([A-Z][a-z]+ \d+, \d{4})", seg_txt)
        rec["runoff_date"] = rm.group(1) if rm else ""
        vm = re.search(r"The seat became vacant (.*?)\.?\s*(?=\[\d+\]|General election|General runoff|Special general)", seg_txt)
        rec["vacancy_reason"] = vm.group(1).strip().rstrip(".") if vm else ""
        rounds = []
        for vb in table.find_all("div", class_="votebox"):
            title = text_of(vb.find("h5")) if vb.find("h5") else ""
            rows = []
            for tr in vb.find_all("tr", class_="results_row"):
                cell = tr.find("td", class_="votebox-results-cell--text")
                if not cell:
                    continue
                nm = text_of(cell)
                pm = re.search(r"\(([A-Za-z ]+)\)\s*$", nm)
                party = party_code(pm.group(1)) if pm else ""
                if pm and len(pm.group(1)) <= 2:
                    party = pm.group(1)
                name = re.sub(r"\s*\([A-Za-z ]+\)\s*$", "", nm).strip()
                nums = tr.find_all("td", class_="votebox-results-cell--number")
                pct = text_of(nums[0]) if nums else ""
                votes = text_of(nums[1]) if len(nums) > 1 else ""
                rows.append({"candidate": name, "party": party, "winner": "winner" in (tr.get("class") or []),
                             "pct": float(pct) if re.match(r"^\d+(\.\d+)?$", pct) else None,
                             "votes": int(votes.replace(",", "")) if re.match(r"^[\d,]+$", votes) else None})
            rounds.append({"round": title, "results": rows})
        rec["rounds"] = rounds
        final = rounds[0] if rounds else {"results": []}
        winners = [r for r in final["results"] if r["winner"]]
        if winners and any(r["pct"] is not None for r in final["results"]):
            rec["status"] = "decided"
            rec["winner"] = winners[0]["candidate"]
            rec["winner_party"] = winners[0]["party"]
        elif final["results"]:
            rec["status"] = "pending"
            rec["winner"], rec["winner_party"] = "", ""
            rec["candidates"] = [[r["candidate"], r["party"]] for r in final["results"]]
        else:
            rec["status"], rec["winner"], rec["winner_party"] = "unknown", "", ""
        out.append(rec)
    return out


# --------------------------------------------------------------------------- 3
# Texas Tribune 2023 lottery + LRL name->district
def parse_tribune_lots(html):
    t = htmllib.unescape(html)
    # the article body appears (escaped) inside the republish box too; take the first occurrence
    i = t.find("Two-year terms")
    j = t.find("Four-year terms", i)
    k = t.find("</h3>", j)
    end = re.search(r"<(h2|h3|div class=\"c-story-footer|footer)", t[k + 1:])
    two_seg = t[i:j]
    four_seg = t[j: (k + 1 + end.start()) if end else j + 6000]

    def names(seg):
        return [htmllib.unescape(re.sub(r"\s+", " ", n)).strip()
                for n in re.findall(r'href="https://www\.texastribune\.org/directory/[^"]+"[^>]*>([^<]+)</a>', seg)]
    return names(two_seg), names(four_seg)


def parse_lrl(html):
    """LRL member search table -> list of {name, district, senate_years, party}.
    Row layout: <th scope=row>Name</th>, then td: Notes, District, Chamber, Years, Session, Party, City, Counties."""
    soup = BeautifulSoup(html, "lxml")
    rows = []
    table = soup.find("table", id="tableToSort") or soup
    for tr in table.find_all("tr"):
        th = tr.find("th", scope="row")
        tds = tr.find_all("td")
        if th is None or len(tds) < 6:
            continue
        name = text_of(th.find("div", class_="mobileHide") or th)
        cells = [text_of(td) for td in tds]
        try:
            d = int(re.match(r"(\d+)", cells[1]).group(1))
        except Exception:  # noqa
            continue
        chambers = cells[2].split()
        years = re.findall(r"(\d{4}) - (\d{4})", cells[3])
        parties = re.findall(r"\b([DRIL])\b", cells[5])
        # the Senate stint is the one whose chamber code is 'S' (first entry on Senate searches)
        sen_years = None
        for ch, yr in zip(chambers, years):
            if ch == "S":
                sen_years = yr
                break
        rows.append({"name": name, "district": d, "chamber_first": chambers[0] if chambers else "",
                     "senate_years": sen_years, "party": parties[0] if parties else ""})
    return rows


def match_names_to_districts(names, lrl_rows):
    idx = {}
    for r in lrl_rows:
        idx[norm_name(r["name"])] = r["district"]
        # also last-name + first-token key
        toks = norm_name(r["name"]).split()
        if toks:
            idx.setdefault(toks[-1] + "|" + toks[0], r["district"])
    out = {}
    for n in names:
        nn = norm_name(n)
        d = idx.get(nn)
        if d is None:
            toks = nn.split()
            if toks:
                d = idx.get(toks[-1] + "|" + toks[0])
        if d is None:
            # fuzzy: unique last-name match
            toks = nn.split()
            cands = [r for r in lrl_rows if toks and norm_name(r["name"]).split()[-1] == toks[-1]]
            if len(cands) == 1:
                d = cands[0]["district"]
            elif toks:
                # typo tolerance (e.g. "Cambpell"): compare sorted letters of last name
                key = "".join(sorted(toks[-1]))
                cands = [r for r in lrl_rows if "".join(sorted(norm_name(r["name"]).split()[-1])) == key]
                if len(cands) == 1:
                    d = cands[0]["district"]
        out[n] = d
    return out


# --------------------------------------------------------------------------- 4
def tlc_statement(html):
    t = re.sub(r"\s+", " ", plain_text(html))
    m = re.search(r"The district plans in effect for the 2026 elections.*?(?:future elections\.|\. ){1}", t)
    return m.group(0).strip() if m else ""


def main():
    pages = {}
    for key in ["bp_sen2026", "bp_sen2024", "bp_senate", "bp_spec2025", "bp_spec2026",
                "bp_redist2020", "bp_redist2026", "tlc_home", "trib_lots", "lrl_88", "lrl_89"]:
        pages[key] = fetch(key)
    # SOS portal probe (POST year=2026). Kept for the record: as of retrieval the portal's year list ends at 2025.
    sos_html = fetch("sos_portal", method="POST",
                     data={"nbElecYear": "2026", "idElection": "", "idOffice": "", "cdParty": "",
                           "cdOfficeType": "", "cdStatus": "", "idTown": "", "cdFlow": "", "results": ""})
    sos_elections = []
    if sos_html:
        sos_elections = re.findall(r'<option value="(\d{3,})"[^>]*>([^<]*2026[^<]*)</option>', sos_html)

    # ---------- seats up
    districts_up, cands = parse_general_table(pages["bp_sen2026"])
    districts_2024, _ = parse_general_table(pages["bp_sen2024"], "Texas State Senate general election, 2024")
    two_names, four_names = parse_tribune_lots(pages["trib_lots"])
    lrl88 = parse_lrl(pages["lrl_88"])
    lrl89 = parse_lrl(pages["lrl_89"])
    four_map = match_names_to_districts(four_names, lrl88)
    two_map = match_names_to_districts(two_names, lrl88)
    lottery_four_districts = sorted(d for d in four_map.values() if d)
    lottery_two_districts = sorted(d for d in two_map.values() if d)
    # LRL 89th: senators whose Senate term ends 2026/2027 are the seats on the 2026 ballot
    lrl_term_end = {}
    for r in lrl89:
        if r["senate_years"]:
            lrl_term_end.setdefault(r["district"], set()).add(int(r["senate_years"][1]))
    lrl_up = sorted(d for d, ends in lrl_term_end.items() if any(e in (2026, 2027) for e in ends))
    lrl_not_up = sorted(d for d, ends in lrl_term_end.items() if all(e >= 2028 for e in ends))

    checks = {
        "ballotpedia_2026_table_districts": districts_up,
        "ballotpedia_2024_table_districts": districts_2024,
        "complement_of_2024_equals_2026": sorted(set(range(1, 32)) - set(districts_2024)) == districts_up,
        "tribune_2023_four_year_term_districts": lottery_four_districts,
        "tribune_2023_two_year_term_districts": lottery_two_districts,
        "tribune_four_year_equals_2026": lottery_four_districts == districts_up,
        "tribune_unmatched_names": [n for n, d in {**four_map, **two_map}.items() if not d],
        "lrl_89th_term_ends_2026_or_2027_districts": lrl_up,
        "lrl_89th_term_ends_2028plus_districts": lrl_not_up,
        "lrl_equals_2026": lrl_up == districts_up,
        "sos_portal_2026_elections_listed": sos_elections,
    }
    seats = {
        "election_date": "2026-11-03",
        "n_districts_up": len(districts_up),
        "districts_up": districts_up,
        "districts_not_up": sorted(set(range(1, 32)) - set(districts_up)),
        "source_urls": [SOURCES[k][0] for k in ("bp_sen2026", "bp_sen2024", "trib_lots", "lrl_88", "lrl_89", "bp_spec2025", "bp_spec2026")],
        "cross_checks": checks,
        "notes": (
            "Texas Senate terms were reset after 2021/2023 redistricting: all 31 seats ran in 2022; on Jan 11 2023 senators drew lots "
            "(odd = 4-year term, so up again in 2026; even = 2-year term, up in 2024 and then 2028). The 16 seats on the Nov 3, 2026 "
            "ballot are therefore exactly the 4-year-term draws, NOT an odd/even district split. Ballotpedia's 2026 table, the complement "
            "of Ballotpedia's 2024 table, the Texas Tribune's published lottery list (mapped to districts via LRL 88th-Legislature membership) "
            "and the LRL 89th-Legislature term-end years were compared; see cross_checks. Special-election effects: SD9 (Hancock resigned; "
            "Rehmet (D) won the Jan 31 2026 runoff) and SD4 (Creighton resigned; Ligon (R) won the May 2 2026 special) were already 4-year "
            "seats scheduled for 2026, so their winners are running in the regular 2026 election as incumbents. SD22 (Birdwell resigned "
            "May 29 2026) was also scheduled for 2026; a special election for the unexpired remainder is held concurrently on Nov 3 2026 "
            "with the same two candidates as the regular race. No special election changed the set of seats up. The Texas SOS candidate "
            "portal could not be used as an official cross-check because it lists no 2026 elections (see cross_checks.sos_portal_2026_elections_listed)."
        ),
        "retrieved_at": NOW,
    }
    with open(os.path.join(OUT, "senate_seats_up_2026.json"), "w") as f:
        json.dump(seats, f, indent=2, ensure_ascii=False)
    add_output("senate_seats_up_2026.json", SOURCES["bp_sen2026"][0], "Derived: Texas Senate districts on the Nov 3 2026 ballot with cross-checks")

    # ---------- candidates
    members = parse_members(pages["bp_senate"])
    retiring = parse_retiring(pages["bp_sen2026"])
    with open(os.path.join(OUT, "senate_candidates_2026.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["district", "candidate_name", "party", "party_raw", "incumbent", "withdrew",
                                          "did_not_make_ballot", "ballotpedia_url"])
        w.writeheader()
        for c in sorted(cands, key=lambda x: (x["district"], x["party"], x["candidate_name"])):
            w.writerow({k: (str(v).lower() if isinstance(v, bool) else v) for k, v in c.items()})
    add_output("senate_candidates_2026.csv", SOURCES["bp_sen2026"][0],
               "Parsed from Ballotpedia general-election table: candidates per Senate district (incl. did-not-make-ballot entries)")

    specials = parse_special_elections(pages["bp_spec2025"], SOURCES["bp_spec2025"][0]) + \
        parse_special_elections(pages["bp_spec2026"], SOURCES["bp_spec2026"][0])
    # de-duplicate (the 2026 page repeats the SD9 2025 race)
    seen, specials_dedup = set(), []
    for s in specials:
        k = (s["district"], s["election_date"])
        if k in seen:
            continue
        seen.add(k)
        specials_dedup.append(s)

    rows = []
    for d in districts_up:
        dc = [c for c in cands if c["district"] == d and not c["did_not_make_ballot"] and not c["withdrew"]]
        mem = members.get(d, {})
        inc_on_ballot = [c for c in dc if c["incumbent"]]
        dem = [c for c in dc if c["party"] == "D"]
        rep = [c for c in dc if c["party"] == "R"]
        third = [c for c in dc if c["party"] not in ("D", "R")]
        notes = []
        if mem.get("vacant"):
            notes.append("seat vacant")
        for r in retiring:
            if r["district"] == d:
                notes.append(f"incumbent {r['name']} ({r['party']}) retiring")
        for s in specials_dedup:
            if s["district"] == d:
                if s["status"] == "decided":
                    notes.append(f"special election {s['election_date']}: {s['winner']} ({s['winner_party']}) won; {s['vacancy_reason']}")
                else:
                    notes.append(f"special election {s['election_date']} pending (concurrent with general); {s['vacancy_reason']}")
        dnmb = [c["candidate_name"] + " (" + c["party_raw"] + ")" for c in cands if c["district"] == d and c["did_not_make_ballot"]]
        if dnmb:
            notes.append("did not make ballot: " + "; ".join(dnmb))
        rows.append({
            "district": d,
            "incumbent_name": mem.get("name", ""),
            "incumbent_party": party_code(mem.get("party", "")),
            "open_seat": str(len(inc_on_ballot) == 0).lower(),
            "dem_running": str(len(dem) > 0).lower(),
            "rep_running": str(len(rep) > 0).lower(),
            "n_third_party": len(third),
            "uncontested": str(len(dc) <= 1).lower(),
            "notes": " | ".join(notes),
        })
    with open(os.path.join(OUT, "senate_districts_2026.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    add_output("senate_districts_2026.csv", SOURCES["bp_sen2026"][0],
               "Derived per-seat summary (incumbent from Ballotpedia chamber page; open_seat = no incumbent on the general ballot)")

    # ---------- control
    comp = parse_composition(pages["bp_senate"])
    comp_from_members = {"D": sum(1 for m in members.values() if m["party"].startswith("Democrat")),
                         "R": sum(1 for m in members.values() if m["party"].startswith("Republican")),
                         "vacant": sum(1 for m in members.values() if m["vacant"]),
                         "vacant_districts": sorted(d for d, m in members.items() if m["vacant"])}
    lrl_parties = {}
    for r in lrl89:
        if r["senate_years"] and int(r["senate_years"][1]) >= 2026:
            lrl_parties.setdefault(r["district"], []).append((r["name"], r["party"], r["senate_years"]))
    control = {
        "as_of": NOW,
        "composition_ballotpedia_table": comp,
        "composition_from_member_list": comp_from_members,
        "members": {str(d): members[d] for d in sorted(members)},
        "lrl_89th_senators_with_terms_ending_2026_or_later": {str(d): v for d, v in sorted(lrl_parties.items())},
        "special_elections_2025_2026": specials_dedup,
        "source_urls": [SOURCES[k][0] for k in ("bp_senate", "bp_spec2025", "bp_spec2026", "lrl_89")],
        "notes": "Composition is pre-election (Nov 2026). Vacant seats listed under composition_from_member_list.vacant_districts.",
    }
    with open(os.path.join(OUT, "senate_control_2026.json"), "w") as f:
        json.dump(control, f, indent=2, ensure_ascii=False)
    add_output("senate_control_2026.json", SOURCES["bp_senate"][0], "Derived: current Senate composition, member list, 2025-2026 special elections")

    # ---------- maps
    stmt = tlc_statement(pages["tlc_home"])
    r2026 = re.sub(r"\s+", " ", plain_text(pages["bp_redist2026"]))
    bp_cong_sentence = ""
    m = re.search(r"On August 29, 2025, Gov\. Greg Abbott \(R\) signed a bill enacting a new congressional map[^.]*\.", r2026)
    if m:
        bp_cong_sentence = m.group(0)
    r2020 = re.sub(r"\s+", " ", plain_text(pages["bp_redist2020"]))
    m2 = re.search(r"Texas enacted new legislative district boundaries in June 2023[^.]*\.[^.]*\.", r2020)
    bp_leg_sentence = m2.group(0) if m2 else ""
    # sentences (not nav bullets) on the 2026 redistricting page that talk about a legislative-map redraw
    leg_redraw_sentences = [
        snt.strip() for snt in re.split(r"(?<=[.!?]) ", r2026)
        if "\u2022" not in snt
        and re.search(r"state (senate|house|legislative) (district|map)", snt, re.I)
        and re.search(r"redr|new map|enact|redistrict", snt, re.I)
    ]
    mentions_leg_redraw = len(leg_redraw_sentences) > 0
    maps = {
        "statement": ("Texas's 2025 mid-decade redistricting (89th Legislature, 2nd Called Session) replaced only the congressional plan "
                      "(PlanC2193 -> PlanC2333). The state Senate plan PLANS2168 and state House plan PLANH2316, enacted in 2023 "
                      "(SB 375 / HB 1000) with the same districts as the 2021 plans, remain the plans in effect for the November 3, 2026 elections."),
        "tlc_verbatim": stmt,
        "tlc_plan_ids_found": sorted(set(re.findall(r"Plan[CSHE]\d{4}", stmt))),
        "ballotpedia_2026_redistricting_sentence": bp_cong_sentence,
        "ballotpedia_2026_page_mentions_legislative_redraw": mentions_leg_redraw,
        "ballotpedia_2026_page_legislative_redraw_sentences": leg_redraw_sentences,
        "ballotpedia_2020_census_legislative_sentence": bp_leg_sentence,
        "senate_plan": "PLANS2168",
        "house_plan": "PLANH2316",
        "congressional_plan_2026": "PLANC2333",
        "verified": ("PlanS2168" in stmt and "PlanH2316" in stmt and "2026 elections" in stmt),
        "source_urls": [SOURCES["tlc_home"][0], SOURCES["bp_redist2026"][0], SOURCES["bp_redist2020"][0],
                        "https://dvr.capitol.texas.gov/Senate/0/PLANS2168", "https://dvr.capitol.texas.gov/House/0/PLANH2316"],
        "retrieved_at": NOW,
    }
    with open(os.path.join(OUT, "maps_confirmation.json"), "w") as f:
        json.dump(maps, f, indent=2, ensure_ascii=False)
    add_output("maps_confirmation.json", SOURCES["tlc_home"][0], "Confirmation that PLANS2168/PLANH2316 are the 2026 legislative maps (congressional-only 2025 redraw)")

    # ---------- manifest (merge: keep other scripts' entries, replace ours by filename)
    mpath = os.path.join(OUT, "manifest.json")
    existing = []
    if os.path.exists(mpath):
        try:
            existing = json.load(open(mpath))
        except Exception:  # noqa
            existing = []
    ours = {e["file"] for e in manifest_entries}
    merged = [e for e in existing if e.get("file") not in ours] + manifest_entries
    with open(mpath, "w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    # ---------- console summary
    print("Districts up (Ballotpedia 2026):", districts_up)
    print("Cross-checks:", json.dumps({k: v for k, v in checks.items() if isinstance(v, bool)}, indent=1))
    print("Unmatched lottery names:", checks["tribune_unmatched_names"])
    print("Composition:", comp, comp_from_members)
    print("Specials:", [(s["district"], s["election_date"], s["status"], s["winner"], s["winner_party"]) for s in specials_dedup])
    print("Maps verified:", maps["verified"])
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
