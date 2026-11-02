#!/usr/bin/env python
"""fetch_markets.py -- prediction-market prices on 2026 Texas House / Senate / legislature control.

Runs with no arguments. Writes into <project>/data/raw/markets/:
  markets.csv    platform, market_title, outcome, yes_price, volume, as_of, url (+ bid/ask/ticker extras)
  manifest.json  one entry per saved file
  raw/           raw API JSON for every call

Sources (public, unauthenticated APIs):
  * Kalshi  https://api.elections.kalshi.com/trade-api/v2  (series list, markets by series)
  * Polymarket Gamma  https://gamma-api.polymarket.com  (public-search, events by slug)
"""
import csv
import datetime as dt
import json
import os
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(PROJECT, "data", "raw", "markets")
RAW = os.path.join(OUT, "raw")
os.makedirs(RAW, exist_ok=True)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "application/json"})
NOW_ISO = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
NOW = dt.datetime.now().strftime("%Y-%m-%dT%H:%M")
MANIFEST = []
rows = []
notes = []

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"


def get_json(url, fname, desc, params=None):
    path = os.path.join(RAW, fname)
    try:
        r = S.get(url, params=params, timeout=60)
        status = r.status_code
        data = r.json() if r.content else None
    except Exception as e:  # noqa: BLE001
        print(f"  ! {url}: {e}", file=sys.stderr)
        status, data = None, None
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    MANIFEST.append({"file": os.path.relpath(path, OUT), "url": r.url if status else url,
                     "retrieved_at": NOW, "http_status": status, "description": desc})
    print(f"  {status}  {url} {params or ''}")
    time.sleep(0.4)
    return data if status == 200 else None


def add(platform, title, outcome, yes_price, volume, url, **extra):
    row = {"platform": platform, "market_title": title, "outcome": outcome, "yes_price": yes_price,
           "volume": volume, "as_of": NOW_ISO, "url": url}
    row.update(extra)
    rows.append(row)


# ----------------------------------------------------------------------------
print("== Kalshi")
series = get_json(f"{KALSHI}/series", "kalshi_series.json", "Kalshi: all series (scan titles for Texas legislature)",
                  params={"limit": 1000})
tx_leg_series = []
if series:
    for s in series.get("series", []):
        t = (s.get("title", "") + " " + s.get("ticker", "")).lower()
        if ("texas" in t or s.get("ticker", "").startswith("KXTX") or "statelegtx" in t) and \
           any(k in t for k in ["house", "legislat", "senate seats", "supermaj"]):
            tx_leg_series.append(s["ticker"])
    print(f"  candidate series: {tx_leg_series}")

# Series we know carry Texas *state legislature* markets, plus whatever the scan finds.
for st in sorted(set(["KXTXHOUSE", "KXGOPSTATESUPERMAJ", "KXDEMSTATESUPERMAJ", "KXSTATELEGTX"] + tx_leg_series)):
    data = get_json(f"{KALSHI}/markets", f"kalshi_markets_{st}.json", f"Kalshi markets for series {st}",
                    params={"series_ticker": st, "limit": 1000})
    if not data:
        continue
    mk = data.get("markets", [])
    kept = 0
    for m in mk:
        title = m.get("title", "")
        sub = m.get("yes_sub_title", "") or ""
        tl = (title + " " + sub).lower()
        # Keep only Texas STATE legislature markets for the 2026 cycle.
        if st == "KXTXHOUSE":
            ok = True  # "Who will win the Texas House of Representatives?" (state chamber; rules say Texas House 2026)
        elif st in ("KXGOPSTATESUPERMAJ", "KXDEMSTATESUPERMAJ"):
            ok = "texas" in tl
        elif st == "KXSTATELEGTX":
            ok = "2026" in title
        else:
            ok = "texas" in tl and ("house" in tl or "senate" in tl or "legislat" in tl) \
                and "u.s." not in tl and "congress" not in tl
        if not ok:
            continue
        kept += 1
        add("Kalshi", title, sub or m.get("ticker", ""),
            m.get("last_price_dollars", ""), m.get("volume_fp", ""),
            f"https://kalshi.com/markets/{st.lower()}",
            yes_bid=m.get("yes_bid_dollars", ""), yes_ask=m.get("yes_ask_dollars", ""),
            open_interest=m.get("open_interest_fp", ""), ticker=m.get("ticker", ""),
            status=m.get("status", ""), close_time=m.get("close_time", ""),
            rules=m.get("rules_primary", ""))
    print(f"  {st}: {len(mk)} markets, kept {kept}")
    if st == "KXSTATELEGTX" and kept == 0 and mk:
        yrs = sorted({m["ticker"].split("-")[1][:2] for m in mk if "-" in m["ticker"]})
        notes.append(f"Kalshi series KXSTATELEGTX ('Texas Legislature race winner?') has {len(mk)} district markets "
                     f"but all are for cycle 20{'/20'.join(yrs)}; no 2026 district-level Texas markets exist.")

# ----------------------------------------------------------------------------
print("== Polymarket")
found_slugs = set()
for q in ["Texas State Senate", "Texas State House", "Texas House of Representatives", "Texas legislature",
          "which party will win the texas"]:
    d = get_json(f"{GAMMA}/public-search", f"polymarket_search_{q.replace(' ', '_')}.json",
                 f"Polymarket public-search q='{q}'", params={"q": q, "limit_per_type": 30})
    if not d:
        continue
    for e in d.get("events", []) or []:
        t = (e.get("title", "") + " " + e.get("slug", "")).lower()
        if "texas" in t and any(k in t for k in ["state senate", "state house", "legislature", "texas house in",
                                                  "texas senate in"]) and not e.get("closed"):
            found_slugs.add(e["slug"])
# Known slug (direct lookup is stable even if search ranking changes)
found_slugs.add("which-party-will-win-the-texas-state-senate-in-2026")
for slug in ["which-party-will-win-the-texas-state-house-in-2026", "which-party-will-win-the-texas-house-in-2026"]:
    d = get_json(f"{GAMMA}/events", f"polymarket_event_{slug}.json", f"Polymarket event lookup slug={slug} (probe)",
                 params={"slug": slug})
    if d:
        found_slugs.add(slug)
    else:
        notes.append(f"Polymarket: no event with slug '{slug}' (no Texas State House control market found).")
print(f"  slugs: {sorted(found_slugs)}")
for slug in sorted(found_slugs):
    d = get_json(f"{GAMMA}/events", f"polymarket_event_{slug}.json", f"Polymarket event {slug}", params={"slug": slug})
    if not d:
        continue
    e = d[0]
    for m in e.get("markets", []):
        q = m.get("question", "")
        # skip unnamed placeholder outcomes (Party A..F / another party) with zero volume
        if ("Party " in q and "Democratic" not in q and "Republican" not in q) or q.startswith("Will another party"):
            if float(m.get("volume") or 0) == 0:
                continue
        try:
            outcomes = json.loads(m.get("outcomes") or "[]")
            prices = json.loads(m.get("outcomePrices") or "[]")
        except Exception:  # noqa: BLE001
            outcomes, prices = [], []
        yes_price = prices[outcomes.index("Yes")] if "Yes" in outcomes and prices else (prices[0] if prices else "")
        add("Polymarket", e.get("title", ""), q, yes_price, m.get("volume", ""),
            f"https://polymarket.com/event/{slug}", liquidity=m.get("liquidity", ""),
            ticker=m.get("slug", ""), status="closed" if m.get("closed") else "open",
            close_time=e.get("endDate", ""), event_volume=e.get("volume", ""))

# ----------------------------------------------------------------------------
print("== write")
cols = ["platform", "market_title", "outcome", "yes_price", "volume", "as_of", "url",
        "yes_bid", "yes_ask", "open_interest", "liquidity", "ticker", "status", "close_time", "event_volume", "rules"]
with open(os.path.join(OUT, "markets.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in cols})
MANIFEST.append({"file": "markets.csv", "url": "", "retrieved_at": NOW,
                 "description": "Parsed prediction-market prices for 2026 Texas legislature control"})
MANIFEST.append({"file": "run_notes.txt", "url": "", "retrieved_at": NOW,
                 "description": "Machine-written notes on markets that were searched for but do not exist"})
with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(MANIFEST, f, indent=1)
with open(os.path.join(OUT, "run_notes.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(notes) + "\n")
print(f"markets.csv: {len(rows)} rows")
for n in notes:
    print("  note:", n)
