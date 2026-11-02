#!/usr/bin/env python
"""Fetch and parse Ballotpedia's Texas House of Representatives 2026 general-election
candidate list, current partisan composition, and 2025-2026 special elections.

Runnable with no arguments. Writes into <project>/data/raw/ballotpedia/:
  - Texas_House_of_Representatives_elections_2026.html   (raw)
  - Texas_House_of_Representatives.html                   (raw)
  - Texas_state_legislative_special_elections_2025.html   (raw)
  - Texas_state_legislative_special_elections_2026.html   (raw)
  - house_candidates_2026.csv
  - house_districts_2026.csv
  - house_control_2026.json
  - manifest.json
  - NOTES.md

Raw HTML is re-downloaded on every run; if a download fails and a previously saved
copy exists, the saved copy is used and the failure is recorded in NOTES.md.
"""
import csv
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

from bs4 import BeautifulSoup

PROJECT = Path(__file__).resolve().parents[2]
OUT = PROJECT / "data" / "raw" / "ballotpedia"
OUT.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

PAGES = {
    "elections": ("https://ballotpedia.org/Texas_House_of_Representatives_elections,_2026",
                  "Texas_House_of_Representatives_elections_2026.html"),
    "chamber": ("https://ballotpedia.org/Texas_House_of_Representatives",
                "Texas_House_of_Representatives.html"),
    "specials_2025": ("https://ballotpedia.org/Texas_state_legislative_special_elections,_2025",
                      "Texas_state_legislative_special_elections_2025.html"),
    "specials_2026": ("https://ballotpedia.org/Texas_state_legislative_special_elections,_2026",
                      "Texas_state_legislative_special_elections_2026.html"),
}

N_DISTRICTS = 150
problems = []
manifest = []
now = dt.datetime.now().strftime("%Y-%m-%dT%H:%M")


def fetch(url, fname):
    path = OUT / fname
    try:
        r = subprocess.run(["curl", "-sL", "-A", UA, "--max-time", "60", "-o", str(path),
                            "-w", "%{http_code}", url], capture_output=True, text=True, timeout=90)
        code = r.stdout.strip()
        if code != "200" or path.stat().st_size < 10000:
            raise RuntimeError(f"HTTP {code}, size {path.stat().st_size if path.exists() else 0}")
        manifest.append({"file": fname, "url": url, "retrieved_at": now,
                         "description": "Raw Ballotpedia HTML"})
    except Exception as e:  # noqa: BLE001
        if path.exists() and path.stat().st_size > 10000:
            problems.append(f"Re-fetch of {url} failed ({e}); used previously saved {fname}.")
            manifest.append({"file": fname, "url": url, "retrieved_at": "previous run",
                             "description": "Raw Ballotpedia HTML (cached; refetch failed)"})
        else:
            problems.append(f"Fetch of {url} FAILED ({e}); no cached copy.")
            return None
    return path.read_text(encoding="utf-8", errors="replace")


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


OTHER_PARTY_MAP = [
    (r"libertarian", "L"),
    (r"green", "G"),
    (r"independent|no party|nonpartisan|unaffiliated", "I"),
    (r"democrat", "D"),
    (r"republican", "R"),
]


def map_party(raw):
    low = raw.lower()
    for pat, code in OTHER_PARTY_MAP:
        if re.search(pat, low):
            return code
    return "Other"


def parse_candidate_span(span, column_party):
    """Return dict for one <span class="candidate"> in the general election table."""
    a = None
    for link in span.find_all("a"):
        href = link.get("href", "")
        if "#Campaign_themes" in href or not link.get_text(strip=True):
            continue
        a = link
        break
    text = norm(span.get_text(" ", strip=True))
    if a is None:
        name = re.sub(r"\(.*?\)", "", text).strip()
        url = ""
    else:
        name = norm(a.get_text(" ", strip=True))
        url = a.get("href", "")
        if url.startswith("/"):
            url = "https://ballotpedia.org" + url
    incumbent = bool(re.search(r"\(i\)", text))
    withdrew = bool(re.search(r"withdr|disqualif", text, re.I)) or bool(span.find(["s", "del", "strike"]))
    # party text in parentheses other than (i)
    parens = [p for p in re.findall(r"\(([^()]*)\)", text) if p.strip().lower() != "i"]
    if column_party in ("D", "R"):
        party_raw = {"D": "Democratic", "R": "Republican"}[column_party]
        if parens:
            party_raw = party_raw + " [" + "; ".join(parens) + "]"
        party = column_party
    else:
        party_raw = "; ".join(parens) if parens else "Other (unspecified)"
        party = map_party(party_raw)
    return {"candidate_name": name, "party": party, "party_raw": party_raw,
            "incumbent": incumbent, "withdrew": withdrew, "ballotpedia_url": url}


def parse_general_election(html):
    soup = BeautifulSoup(html, "lxml")
    table = None
    for t in soup.find_all("table", class_="candidateListTablePartisan"):
        head = t.find("h4")
        if head and "general election" in head.get_text().lower():
            table = t
            break
    if table is None:
        problems.append("General election candidate table not found on elections page.")
        return []
    cands = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) != 4:
            continue
        m = re.search(r"District\s+(\d+)", tds[0].get_text(" ", strip=True))
        if not m:
            continue
        district = int(m.group(1))
        for td, col in zip(tds[1:], ("D", "R", "Other")):
            for span in td.find_all("span", class_="candidate"):
                if not span.get_text(strip=True):
                    continue
                row = parse_candidate_span(span, col)
                row["district"] = district
                cands.append(row)
    return cands


def parse_composition(html, label):
    soup = BeautifulSoup(html, "lxml")
    for t in soup.find_all("table"):
        txt = norm(t.get_text(" ", strip=True))
        if txt.startswith("Partisan composition") and "Total" in txt:
            comp = {"source_label": label}
            m = re.search(r"As of ([A-Za-z]+ \d{4})", txt)
            comp["as_of"] = m.group(1) if m else None
            for key, pat in (("democratic", r"Democratic (\d+)"), ("republican", r"Republican (\d+)"),
                             ("other", r"Other (\d+)"), ("vacancies", r"Vacanc\w* (\d+)"),
                             ("total", r"Total (\d+)")):
                mm = re.search(pat, txt)
                comp[key] = int(mm.group(1)) if mm else None
            return comp
    problems.append(f"Partisan composition table not found on {label} page.")
    return None


def parse_vacant_seats(html):
    soup = BeautifulSoup(html, "lxml")
    vacant = []
    for t in soup.find_all("table", class_="bptable"):
        if "Date assumed office" not in t.get_text():
            continue
        for tr in t.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) >= 2 and "Vacant" in tds[1].get_text():
                m = re.search(r"District (\d+)", tds[0].get_text())
                if m:
                    vacant.append(int(m.group(1)))
        break
    return sorted(set(vacant))


def parse_specials(html, year):
    """Return list of special elections (all chambers) from a Ballotpedia specials page."""
    soup = BeautifulSoup(html, "lxml")
    h = soup.find(id="Special_elections")
    out = []
    if not h:
        problems.append(f"Special elections section not found on {year} specials page.")
        return out
    node = h.parent.find_next_sibling()
    date = None
    while node is not None and node.name != "h2":
        if node.name in ("h3", "h4"):
            date = norm(node.get_text(" ", strip=True))
        elif node.name == "table" and "collapsible" in (node.get("class") or []):
            txt = norm(node.get_text(" ", strip=True))
            m = re.match(r"(Texas (?:State Senate|House of Representatives) District \d+)", txt)
            if not m:
                node = node.find_next_sibling()
                continue
            seat = m.group(1)
            chamber = "Senate" if "Senate" in seat else "House"
            dist = int(re.search(r"District (\d+)", seat).group(1))
            vac = re.search(r"The seat became vacant (.*?)\.\s*\[\d+\]", txt)
            # Winners: "X defeated Y in the special general [runoff] election"
            winner = None
            winner_party = None
            status = "pending"
            # prefer runoff result if present (it appears first on the page)
            wm = re.search(r"((?:[A-Z][\w.'\-]*\s){0,4}[A-Z][\w.'\-]+)\s(?:\(([DRLGI])\)\s)?defeated\s", txt)
            if wm:
                winner = wm.group(1).strip()
                status = "decided"
                winner_party = wm.group(2)
                if not winner_party:
                    pm = re.search(re.escape(winner) + r"\s*\(([DRLGI])\)", txt)
                    winner_party = pm.group(1) if pm else None
            runoff = bool(re.search(r"runoff", txt, re.I))
            cands = re.findall(r"([A-Z][A-Za-z.'\- ]+?) \(([DRLGI])\) (?:\d|\[|and|are|is|defeated|$)", txt)
            out.append({
                "year_page": year, "election_date_heading": date, "seat": seat, "chamber": chamber,
                "district": dist, "status": status, "winner": winner, "winner_party": winner_party,
                "runoff": runoff, "vacancy_reason": norm(vac.group(1)) if vac else None,
                "candidates_mentioned": sorted({f"{n.strip()} ({p})" for n, p in cands}),
            })
        node = node.find_next_sibling()
    return out


def main():
    html = {k: fetch(*v) for k, v in PAGES.items()}
    if html["elections"] is None:
        print("FATAL: elections page unavailable", file=sys.stderr)
        write_notes([], [], None, [], [])
        return 1

    cands = parse_general_election(html["elections"])
    for c in cands:
        if c["withdrew"]:
            c["notes"] = "withdrawal/disqualification marker on Ballotpedia"
    cands.sort(key=lambda c: (c["district"], {"D": 0, "R": 1}.get(c["party"], 2), c["candidate_name"]))

    with open(OUT / "house_candidates_2026.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["district", "candidate_name", "party", "party_raw",
                                          "incumbent", "withdrew", "ballotpedia_url"])
        w.writeheader()
        for c in cands:
            w.writerow({k: (str(c[k]).lower() if isinstance(c[k], bool) else c[k]) for k in w.fieldnames})
    manifest.append({"file": "house_candidates_2026.csv", "url": PAGES["elections"][0], "retrieved_at": now,
                     "description": "Parsed general-election candidates, TX House 2026, one row per candidate"})

    vacant = parse_vacant_seats(html["chamber"]) if html["chamber"] else []
    specials = []
    for key, yr in (("specials_2025", 2025), ("specials_2026", 2026)):
        if html[key]:
            specials.extend(parse_specials(html[key], yr))
    # de-duplicate (the 2026 page repeats the SD9 runoff that began in 2025)
    seen = set()
    uniq = []
    for s in specials:
        k = (s["seat"], s["status"], s["winner"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(s)
    specials = uniq
    house_special_pending = {s["district"] for s in specials if s["chamber"] == "House" and s["status"] == "pending"}

    districts = []
    zero = []
    for d in range(1, N_DISTRICTS + 1):
        dc = [c for c in cands if c["district"] == d and not c["withdrew"]]
        inc = [c for c in dc if c["incumbent"]]
        dem = [c for c in dc if c["party"] == "D"]
        rep = [c for c in dc if c["party"] == "R"]
        third = [c for c in dc if c["party"] not in ("D", "R")]
        notes = []
        if not dc:
            zero.append(d)
            notes.append("NO CANDIDATES FOUND on Ballotpedia general-election table")
        if len(inc) > 1:
            notes.append("multiple (i) markers: " + "; ".join(c["candidate_name"] for c in inc))
        if len(dem) > 1:
            notes.append(f"{len(dem)} Democratic candidates listed (runoff not resolved?)")
        if len(rep) > 1:
            notes.append(f"{len(rep)} Republican candidates listed (runoff not resolved?)")
        if d in vacant:
            notes.append("seat currently vacant per Ballotpedia member list")
        if d in house_special_pending:
            notes.append("concurrent special election Nov 3, 2026 for unexpired term")
        n_major = len(dem) + len(rep)
        districts.append({
            "district": d,
            "incumbent_name": inc[0]["candidate_name"] if inc else "",
            "incumbent_party": inc[0]["party"] if inc else "",
            "open_seat": "true" if (dc and not inc) else ("" if not dc else "false"),
            "dem_running": "true" if dem else "false",
            "rep_running": "true" if rep else "false",
            "n_third_party": len(third),
            "uncontested": "true" if (n_major == 1 and len(third) == 0) else "false",
            "notes": "; ".join(notes),
        })
    with open(OUT / "house_districts_2026.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(districts[0].keys()))
        w.writeheader()
        w.writerows(districts)
    manifest.append({"file": "house_districts_2026.csv", "url": PAGES["elections"][0], "retrieved_at": now,
                     "description": "Per-district summary derived from house_candidates_2026.csv"})

    comp_elec = parse_composition(html["elections"], "elections page")
    comp_chamber = parse_composition(html["chamber"], "chamber page") if html["chamber"] else None
    control = {
        "retrieved_at": now,
        "sources": [PAGES["chamber"][0], PAGES["elections"][0], PAGES["specials_2025"][0], PAGES["specials_2026"][0]],
        "partisan_composition": comp_chamber or comp_elec,
        "partisan_composition_elections_page": comp_elec,
        "vacant_house_districts": vacant,
        "speaker": None,
        "special_elections_2025_2026": specials,
    }
    if html["chamber"]:
        m = re.search(r"Speaker of the House:\s*([^<\n]+?)\s*\(([DR])\)", BeautifulSoup(html["chamber"], "lxml").get_text(" "))
        if m:
            control["speaker"] = {"name": norm(m.group(1)), "party": m.group(2)}
    with open(OUT / "house_control_2026.json", "w", encoding="utf-8") as f:
        json.dump(control, f, indent=2)
    manifest.append({"file": "house_control_2026.json", "url": PAGES["chamber"][0], "retrieved_at": now,
                     "description": "Current partisan composition, vacancies, and 2025-2026 TX legislative special elections"})

    with open(OUT / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    write_notes(cands, districts, control, zero, specials)
    # summary to stdout
    print(f"candidates: {len(cands)}; districts with candidates: {N_DISTRICTS - len(zero)}; zero-candidate: {zero}")
    print("contested(D and R):", sum(1 for x in districts if x["dem_running"] == "true" and x["rep_running"] == "true"))
    print("uncontested:", sum(1 for x in districts if x["uncontested"] == "true"))
    print("open seats:", sum(1 for x in districts if x["open_seat"] == "true"))
    print("composition:", control["partisan_composition"])
    return 0


def write_notes(cands, districts, control, zero, specials):
    lines = ["# NOTES: Ballotpedia Texas House 2026 candidate fetch", "",
             f"Generated by pipeline/fetch/fetch_house_candidates.py at {now}.", "",
             "## Source",
             "- Primary: https://ballotpedia.org/Texas_House_of_Representatives_elections,_2026 "
             "(section 'General election', table 'Texas House of Representatives general election, 2026'). "
             "The table is static HTML (no dynamic tabs), so no district-page or SOS fallback was needed.",
             "- Composition/vacancies: https://ballotpedia.org/Texas_House_of_Representatives (partisan composition table and member list).",
             "- Special elections: https://ballotpedia.org/Texas_state_legislative_special_elections,_2025 and ..._2026 "
             "(the elections page itself has no special-elections list).", ""]
    if cands:
        n_d = sum(1 for d in districts if d["dem_running"] == "true")
        n_r = sum(1 for d in districts if d["rep_running"] == "true")
        lines += ["## Counts",
                  f"- Candidates parsed: {len(cands)} across {len({c['district'] for c in cands})} districts.",
                  f"- Districts with a Democrat: {n_d}; with a Republican: {n_r}; "
                  f"with both: {sum(1 for d in districts if d['dem_running']=='true' and d['rep_running']=='true')}.",
                  f"- Uncontested (single major-party candidate, no others): {sum(1 for d in districts if d['uncontested']=='true')}.",
                  f"- Open seats (no (i) candidate): {sum(1 for d in districts if d['open_seat']=='true')}.",
                  f"- Third-party/independent candidates: {sum(1 for c in cands if c['party'] not in ('D','R'))}.",
                  f"- Incumbent markers: {sum(1 for c in cands if c['incumbent'])}.", ""]
    lines += ["## Districts with zero candidates found",
              ("- " + ", ".join(str(z) for z in zero)) if zero else "- None; all 150 districts have at least one candidate.", ""]
    lines += ["## Caveats",
              "- `withdrew`: Ballotpedia's general-election table carries no withdrawal/strikethrough markup; "
              "the column is derived from any 'withdrew/disqualified' text or <s>/<del> tags in the candidate cell "
              f"({sum(1 for c in cands if c['withdrew'])} flagged). Withdrawn candidates that Ballotpedia already removed are simply absent.",
              "- `incumbent` is Ballotpedia's '(i)' marker. Districts currently vacant (see house_control_2026.json) "
              "have no incumbent and are therefore open seats.",
              "- `party` for the 'Other' column is mapped from the parenthetical party text (party_raw); unmapped text -> 'Other'.",
              "- Party composition 'As of' date is Ballotpedia's own label.",
              "- Ballotpedia lists a Democratic candidate in every one of the 150 districts; this matches the table as "
              "published but is worth cross-checking against the Texas SOS certified ballot before relying on it.", ""]
    if control:
        lines += ["## Composition", f"- {json.dumps(control['partisan_composition'])}",
                  f"- Vacant House districts per member list: {control['vacant_house_districts']}", "",
                  "## Special elections (2025-2026, both chambers)"]
        for s in specials:
            lines.append(f"- {s['seat']} ({s['election_date_heading']}): {s['status']}"
                         + (f", winner {s['winner']} ({s['winner_party']})" if s["winner"] else "")
                         + (f"; vacancy: {s['vacancy_reason']}" if s["vacancy_reason"] else ""))
        lines.append("")
    lines += ["## Problems / fallbacks"] + ([f"- {p}" for p in problems] or ["- None."])
    (OUT / "NOTES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
