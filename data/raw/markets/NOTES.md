# NOTES: prediction markets on 2026 Texas legislature control

Produced by `pipeline/fetch/fetch_markets.py` (no arguments; venv python). Raw API JSON in `raw/`;
`manifest.json` lists every file. Prices are snapshots at `as_of` (UTC) in markets.csv.

## What exists (markets.csv, 5 rows)

### Kalshi (public API, api.elections.kalshi.com)
- `KXTXHOUSE-26` "Who will win the Texas House of Representatives?" -- R last 0.76 (bid 0.75 / ask 0.76),
  D last 0.24 (bid 0.22 / ask 0.23); volume ~4.7k / 6.5k contracts. Rules: "If the Republican Party wins the
  Texas House of Representatives in 2026 ... resolves to Yes". The title is the state chamber's name (Kalshi's
  U.S. House Texas delegation market is the separate series KXTXHOUSEDEMSEATS, "2026 U.S. House of
  Representatives elections in Texas"), but the rules text does not say "state" explicitly; confirm before use.
- `KXGOPSTATESUPERMAJ-26NOV03-TXS` "Will the number of Texas Senate seats held by Republicans be at least 21
  after the November 3, 2026 general election?" -- bid 0.01 / ask 0.09, last 0.00, zero volume (illiquid).
- No Kalshi market on Texas Senate control exists. `KXDEMSTATESUPERMAJ` has no Texas market.
- `KXSTATELEGTX` ("Texas Legislature race winner?") holds 330 per-district markets, but every one is for the
  2028 cycle (tickers `KXSTATELEGTX-28NOV07-...`, close 2029-11-07) and none has traded. There are no
  2026 district-level Texas legislative markets on Kalshi.

### Polymarket (Gamma API)
- Event `which-party-will-win-the-texas-state-senate-in-2026` ("Which party will win the Texas State Senate in
  2026?"): Republican control Yes 0.958, Democratic control Yes 0.036; event volume ~$5.9k; ends 2026-11-04.
  Placeholder outcomes (Party A-F, "another party") with zero volume are dropped.
- No Polymarket market on Texas State House control or on any Texas legislative district exists. Searches
  ("Texas State House", "Texas House of Representatives", "Texas legislature") return only U.S. House (TX-xx)
  and statewide markets; direct slug probes for a state-House event return nothing (see `run_notes.txt`).
  Polymarket's `/events?closed=false` listing paginates only to offset 2000 (HTTP 422 beyond), so the
  slug-and-search approach is used instead of a full scan.

## Not invented
There is no market anywhere found on "Texas legislature" (both chambers) control or on individual 2026
Texas House / Senate districts; only the three chamber-level markets above.
