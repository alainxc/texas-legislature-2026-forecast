#!/usr/bin/env python
"""fetch_ratings.py -- external race ratings / target lists for the 2026 Texas House & Senate.

Runs with no arguments. Writes into <project>/data/raw/ratings/:
  ratings.csv          district-level ratings and target-list flags
  chamber_ratings.csv  chamber-level calls
  district_polls.csv   district-level general-election polls (none with numbers found; see NOTES.md)
  manifest.json        one entry per saved file
  raw/                 every raw page parsed (HTML), so parsing can be re-run offline

Sources (all public pages, fetched with a desktop User-Agent):
  * State Navigate 2026 Texas forecast pages (public HTML). The pages carry server-side
    pre-rendered seat cells (<span class="iv-prerender-seat-cell" data-district=.. data-rating=..
    data-win-probability=.. data-projected-margin=..>) for every district, which we parse.
    (CNalysis rebranded as State Navigate; cnalysis.com redirects to statenavigate.org.)
  * State Navigate Texas state page: chamber-control probabilities + model date.
  * Sabato's Crystal Ball state-legislative handicapping by Louis Jacobson, as republished on
    rasmussenreports.com (centerforpolitics.org returns HTTP 403 to non-browser clients).
  * Ballotpedia: State legislative battleground chambers, 2026 (table) + TX House/Senate 2026 pages.
  * DLCC Texas target page (dlcc.org/texas) and DLCC 2025-2026 target map page.
  * Texas House Democratic Campaign Committee targeted-races page.
  * RSLC "2026 Texas Candidate Spotlight" press release.
"""
import csv
import datetime as dt
import html
import json
import os
import re
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(PROJECT, "data", "raw", "ratings")
RAW = os.path.join(OUT, "raw")
os.makedirs(RAW, exist_ok=True)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})

MANIFEST = []
NOW = dt.datetime.now().strftime("%Y-%m-%dT%H:%M")


def fetch(url, fname, desc, referer=None):
    """GET url, save body to raw/<fname>, record in manifest. Returns text or None."""
    path = os.path.join(RAW, fname)
    headers = {"Referer": referer} if referer else {}
    try:
        r = SESSION.get(url, headers=headers, timeout=60, allow_redirects=True)
        status = r.status_code
        body = r.text
    except Exception as e:  # noqa: BLE001
        status, body = None, ""
        print(f"  ! {url}: {e}", file=sys.stderr)
    if body:
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
    MANIFEST.append({
        "file": os.path.relpath(path, OUT), "url": url, "retrieved_at": NOW,
        "http_status": status, "description": desc,
    })
    print(f"  {status} {len(body):>8}  {url}")
    time.sleep(0.5)
    return body if status == 200 else None


def clean_name(name):
    """Keep only the trailing candidate name from a text fragment such as
    'Austin. Website Follow Follow Follow Julio Salinas' or 'Rowlett. Denise Villalobos'."""
    toks = name.strip().split()
    cut = 0
    for i, t in enumerate(toks):
        if t in ("Follow", "Website") or (t.endswith(".") and t not in ("Jr.", "Sr.", "Dr.", "Mr.", "Ms.")
                                          and not re.fullmatch(r"[A-Z]\.", t)):
            cut = i + 1
    return " ".join(toks[cut:]).strip()


def strip_tags(h):
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", h, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", html.unescape(t))


# ----------------------------------------------------------------------------
# rating normalisation
STD = ["Safe D", "Likely D", "Lean D", "Tilt D", "Toss-up", "Tilt R", "Lean R", "Likely R", "Safe R"]


def std_statenavigate(raw):
    """Map State Navigate labels to the project's 9-point scale.
    State Navigate uses: solid, very likely, likely, lean, tilt, toss-up, uncontested, no election.
    'very likely' and 'likely' both map to Likely (the raw label is kept in rating_raw);
    'uncontested' maps to Safe; 'no election' (seat not up in 2026) returns None.
    """
    r = raw.strip().lower()
    if r == "toss-up":
        return "Toss-up"
    m = re.match(r"(solid|very likely|likely|lean|tilt|uncontested|no election) ([dr])$", r)
    if not m:
        return ""
    word, party = m.groups()
    p = party.upper()
    if word == "no election":
        return None
    return {"solid": "Safe", "uncontested": "Safe", "very likely": "Likely", "likely": "Likely",
            "lean": "Lean", "tilt": "Tilt"}[word] + " " + p


def std_crystalball(raw):
    r = raw.strip().lower()
    party = "R" if "republican" in r else "D" if "democrat" in r else ""
    if "toss" in r:
        return "Toss-up"
    for k, v in [("safe", "Safe"), ("likely", "Likely"), ("lean", "Lean"), ("tilt", "Tilt")]:
        if k in r:
            return f"{v} {party}"
    return ""


# ----------------------------------------------------------------------------
ratings_rows = []
chamber_rows = []
poll_rows = []


def add_rating(chamber, district, source, raw, std, as_of, url, **extra):
    row = {"chamber": chamber, "district": district, "source": source, "rating_raw": raw,
           "rating_std": std, "as_of_date": as_of, "source_url": url, "retrieved_at": NOW}
    row.update(extra)
    ratings_rows.append(row)


def add_chamber(chamber, source, raw, std, as_of, url, note=""):
    chamber_rows.append({"chamber": chamber, "source": source, "rating_raw": raw, "rating_std": std,
                         "as_of_date": as_of, "source_url": url, "retrieved_at": NOW, "note": note})


# ----------------------------------------------------------------------------
print("== State Navigate")
SN_HOME = "https://statenavigate.org/states/tx/"
sn_home = fetch(SN_HOME, "statenavigate_tx_home.html",
                "State Navigate Texas state page (chamber control odds + model date)")
sn_model_date = ""
if sn_home:
    t = strip_tags(sn_home)
    m = re.search(r"latest (\d{4}-\d{2}-\d{2}) model", t)
    sn_model_date = m.group(1) if m else ""
    for cham, label in [("H", "State House"), ("S", "State Senate")]:
        m = re.search(label + r" (>?\d+%) ([DR]) Chamber control", t)
        if m:
            pct, party = m.groups()
            add_chamber(cham, "State Navigate (model)", f"{pct} {party} chamber control", "",
                        sn_model_date, SN_HOME,
                        "Model probability of chamber control; not a categorical rating")

for cham, slug in [("H", "lower"), ("S", "upper")]:
    url = f"https://projects.statenavigate.com/25-26/states/tx/forecast-{slug}.html"
    body = fetch(url, f"statenavigate_tx_forecast_{slug}.html",
                 f"State Navigate 2026 Texas {'House' if cham == 'H' else 'Senate'} forecast page "
                 "(pre-rendered per-district rating cells)")
    if not body:
        continue
    cells = re.findall(r'<span class="iv-prerender-seat-cell[^"]*"([^>]*)>', body)
    n = 0
    for cell in cells:
        d = dict(re.findall(r'data-([a-z-]+)="([^"]*)"', cell))
        raw = d.get("rating", "")
        std = std_statenavigate(raw)
        if std is None:  # Senate seat not up in 2026
            continue
        add_rating(cham, d.get("district", ""), "State Navigate", raw, std, sn_model_date, url,
                   win_prob_leading=d.get("win-probability", ""),
                   proj_margin_leading=d.get("projected-margin", ""),
                   leading_party=d.get("leading-party", ""),
                   incumbent_party=d.get("incumbent-party", ""),
                   incumbent=d.get("incumbent", ""))
        n += 1
    print(f"  parsed {n} {slug} seat cells (of {len(cells)})")

# ----------------------------------------------------------------------------
print("== Sabato's Crystal Ball (Jacobson) via Rasmussen Reports republication")
CB_URL = ("https://www.rasmussenreports.com/public_content/political_commentary/"
          "commentary_by_louis_jacobson/handicapping_the_2026_state_legislative_map_a_first_look")
cb = fetch(CB_URL, "crystalball_jacobson_state_leg_first_look.html",
           "Louis Jacobson / Sabato's Crystal Ball 'Handicapping the 2026 State Legislative Map: "
           "A First Look' (republished by Rasmussen Reports)")
# Also record that the primary site blocks automated clients
fetch("https://centerforpolitics.org/crystalball/", "centerforpolitics_crystalball_home.html",
      "Crystal Ball home (expected HTTP 403 bot-block; kept as evidence)")
if cb:
    t = strip_tags(cb)
    m = re.search(r"((?:January|February|March|April|May|June|July|August|September|October|"
                  r"November|December) \d{1,2}, 20\d\d)", t)
    cb_date = dt.datetime.strptime(m.group(1), "%B %d, %Y").strftime("%Y-%m-%d") if m else ""
    m = re.search(r"TEXAS Senate: [^S]*?(Safe|Likely|Leans|Lean|Toss-up)[ -]?(Republican|Democratic)?"
                  r".*?House: [^S]*?(Safe|Likely|Leans|Lean|Toss-up)[ -]?(Republican|Democratic)?", t)
    if m:
        sen_raw = " ".join(x for x in m.groups()[:2] if x)
        hou_raw = " ".join(x for x in m.groups()[2:] if x)
        add_chamber("S", "Sabato's Crystal Ball", sen_raw, std_crystalball(sen_raw), cb_date, CB_URL)
        add_chamber("H", "Sabato's Crystal Ball", hou_raw, std_crystalball(hou_raw), cb_date, CB_URL)
        print(f"  Texas: Senate={sen_raw}; House={hou_raw} ({cb_date})")

# ----------------------------------------------------------------------------
print("== Ballotpedia")
BP_BG = "https://ballotpedia.org/State_legislative_battleground_chambers,_2026"
bp = fetch(BP_BG, "ballotpedia_battleground_chambers_2026.html",
           "Ballotpedia: State legislative battleground chambers, 2026")
if bp:
    tables = re.findall(r"<table.*?</table>", bp, flags=re.S)
    listed = set()
    for tb in tables:
        if "battleground chambers, 2026" not in tb:
            continue
        for r in re.findall(r"<tr.*?</tr>", tb, flags=re.S):
            cells = [strip_tags(c).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.S)]
            if cells and cells[0] not in ("Chamber", "State legislative battleground chambers, 2026"):
                listed.add(cells[0])
    for cham, name in [("H", "Texas House of Representatives"), ("S", "Texas State Senate")]:
        is_bg = any(name in x for x in listed)
        add_chamber(cham, "Ballotpedia battleground chambers", "Battleground" if is_bg else "Not a battleground chamber",
                    "", "", BP_BG, f"{len(listed)} chambers listed as battlegrounds")
    print(f"  {len(listed)} battleground chambers; Texas listed: {[x for x in listed if 'Texas' in x]}")
fetch("https://ballotpedia.org/Texas_House_of_Representatives_elections,_2026",
      "ballotpedia_tx_house_2026.html",
      "Ballotpedia: Texas House of Representatives elections, 2026 (ratings section embeds State Navigate)")
fetch("https://ballotpedia.org/Texas_State_Senate_elections,_2026", "ballotpedia_tx_senate_2026.html",
      "Ballotpedia: Texas State Senate elections, 2026")

# ----------------------------------------------------------------------------
print("== DLCC")
DLCC_TX = "https://www.dlcc.org/texas"
d = fetch(DLCC_TX, "dlcc_texas.html", "DLCC Texas page with 'DLCC Target Races' list")
if d:
    t = strip_tags(d)
    i = t.find("DLCC Target Races")
    seg = t[i:i + 3000] if i >= 0 else ""
    seen = set()
    for m in re.finditer(r"Texas (HD|SD)-(\d{1,3}) ([A-Z][^T]*?)(?= Texas (?:HD|SD)-|\s*DLCC Target Candidate|$)", seg):
        kind, num, name = m.groups()
        key = (kind, num)
        if key in seen:
            continue
        seen.add(key)
        add_rating("H" if kind == "HD" else "S", str(int(num)), "DLCC target races", "DLCC Target Race",
                   "Target-D", "", DLCC_TX, candidate=clean_name(name))
    print(f"  {len(seen)} DLCC Texas target races")
tm = fetch("https://www.dlcc.org/the-dlcc-target-map-2025-2026/", "dlcc_target_map_2025_2026.html",
           "DLCC 2025-2026 target map page")
if tm:
    t = strip_tags(tm)
    m = re.search(r"Texas ([A-Z][^.]*\.)", t)
    add_chamber("H", "DLCC target map", m.group(1).strip() if m else "Texas listed", "Target-D", "",
                "https://www.dlcc.org/the-dlcc-target-map-2025-2026/", "Texas on DLCC 2026 target map")

# ----------------------------------------------------------------------------
print("== Texas HDCC")
HDCC = "https://texashdcc.com/targeted-races/"
hd = fetch(HDCC, "texashdcc_targeted_races.html", "Texas House Democratic Campaign Committee targeted races")
if hd:
    t = strip_tags(hd)
    seen = set()
    for m in re.finditer(r"([A-Z][\w\.'’“” ]{2,60}?) for Texas House, District (\d{1,3})", t):
        name, num = m.groups()
        name = clean_name(name)
        if num not in seen:
            seen.add(num)
            add_rating("H", num, "Texas HDCC targeted races", "HDCC Targeted Race (challenger)", "Target-D", "", HDCC,
                       candidate=name)
    for m in re.finditer(r"([A-Z][\w\.'’ ]{2,40}?) State Representative, District (\d{1,3})", t):
        name, num = m.groups()
        name = clean_name(name)
        if num not in seen:
            seen.add(num)
            add_rating("H", num, "Texas HDCC targeted races", "HDCC Targeted Race (incumbent)", "Target-D", "", HDCC,
                       candidate=name)
    print(f"  {len(seen)} HDCC target districts")

# ----------------------------------------------------------------------------
print("== RSLC")
RSLC = ("https://rslc.gop/rslc-launches-2026-texas-candidate-spotlight-series-announces-first-round-spotlights/")
rs = fetch(RSLC, "rslc_2026_texas_candidate_spotlight.html",
           "RSLC press release: 2026 Texas Candidate Spotlight series (first round)")
if rs:
    m = re.search(r'"datePublished":"(\d{4}-\d{2}-\d{2})', rs)
    rs_date = m.group(1) if m else ""
    if not rs_date:
        m = re.search(r"((?:January|February|March|April|May|June|July|August|September|October|November|"
                      r"December) \d{1,2}, 20\d\d)", strip_tags(rs))
        rs_date = dt.datetime.strptime(m.group(1), "%B %d, %Y").strftime("%Y-%m-%d") if m else ""
    t = strip_tags(rs)
    n = 0
    for m in re.finditer(r"((?:[A-Z][\w'\.]+ ){1,3}[A-Z][\w'\.]+) — Texas (House|Senate) District (\d{1,3})", t):
        name, ch, num = m.groups()
        add_rating("H" if ch == "House" else "S", num, "RSLC Texas candidate spotlight",
                   "RSLC 2026 Texas Candidate Spotlight", "Target-R", rs_date, RSLC, candidate=clean_name(name))
        n += 1
    print(f"  {n} RSLC spotlight districts ({rs_date})")
fetch("https://rslc.gop/?s=Texas", "rslc_search_texas.html", "RSLC site search for Texas (no formal target list page exists)")

# ----------------------------------------------------------------------------
# District-level general-election polls. Searches of news and the Texas Tribune polls tracker found
# no 2026 Texas House / Senate district general-election poll with published toplines. One lead
# (a GOP internal of SD-9, Sept 10-15 2026, n=600, +/-3) is recorded with blank numbers; its only
# write-up (mediaite.com) returns HTTP 403 to automated clients, so toplines could not be verified.
poll_rows.append({
    "chamber": "S", "district": "9", "pollster": "", "sponsor": "Republican internal (sponsor not verified)",
    "internal": "true", "start_date": "2026-09-10", "end_date": "2026-09-15", "sample_size": "600",
    "dem_pct": "", "rep_pct": "",
    "source_url": "https://www.mediaite.com/politics/internal-gop-poll-shows-republicans-getting-annihilated-in-trump-17-texas-district/",
    "notes": "Toplines not retrievable (HTTP 403); reported only as 'Republicans trailing badly'. Verify before use.",
})

# ----------------------------------------------------------------------------
print("== write outputs")
rating_cols = ["chamber", "district", "source", "rating_raw", "rating_std", "as_of_date", "source_url",
               "retrieved_at", "win_prob_leading", "proj_margin_leading", "leading_party", "incumbent_party",
               "incumbent", "candidate"]
ratings_rows.sort(key=lambda r: (r["source"], r["chamber"], int(re.sub(r"\D", "", r["district"]) or 0)))
with open(os.path.join(OUT, "ratings.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=rating_cols, extrasaction="ignore")
    w.writeheader()
    for r in ratings_rows:
        w.writerow({c: r.get(c, "") for c in rating_cols})
with open(os.path.join(OUT, "chamber_ratings.csv"), "w", newline="", encoding="utf-8") as f:
    cols = ["chamber", "source", "rating_raw", "rating_std", "as_of_date", "source_url", "retrieved_at", "note"]
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(chamber_rows)
with open(os.path.join(OUT, "district_polls.csv"), "w", newline="", encoding="utf-8") as f:
    cols = ["chamber", "district", "pollster", "sponsor", "internal", "start_date", "end_date", "sample_size",
            "dem_pct", "rep_pct", "source_url", "notes"]
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader()
    w.writerows(poll_rows)
for name, desc in [("ratings.csv", "Parsed district ratings + target-list flags"),
                   ("chamber_ratings.csv", "Parsed chamber-level calls"),
                   ("district_polls.csv", "District-level polls (see NOTES.md)")]:
    MANIFEST.append({"file": name, "url": "", "retrieved_at": NOW, "description": desc})
with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(MANIFEST, f, indent=1)
print(f"ratings.csv: {len(ratings_rows)} rows; chamber_ratings.csv: {len(chamber_rows)}; "
      f"district_polls.csv: {len(poll_rows)}")
