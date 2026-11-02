# NOTES: external ratings and target lists, 2026 Texas House and Senate

Produced by `pipeline/fetch/fetch_ratings.py` (no arguments; venv python). Raw pages are in `raw/`,
one manifest entry per file in `manifest.json`. Retrieved 2026-11-01 (local).

## What was found

### State Navigate (formerly CNalysis) -- district ratings for every seat
- cnalysis.com now redirects to statenavigate.org; State Navigate is the successor brand, so sources 1 and 2
  in the brief are the same source. Texas launched as "Texas Navigate" in 2026.
- District ratings are parsed from the public forecast pages
  `https://projects.statenavigate.com/25-26/states/tx/forecast-lower.html` and `forecast-upper.html`,
  which carry server-side pre-rendered seat cells with `data-rating`, `data-win-probability`,
  `data-projected-margin`, `data-leading-party`, `data-incumbent-party`, `data-incumbent` for all 150 House seats
  and all 31 Senate seats. Ballotpedia's "General election race ratings" section for the Texas House simply
  embeds State Navigate's table (`forecast_embed_26.html?state=tx&chamber=lower`), so Ballotpedia carries no
  independent district ratings.
- 150 House rows and 16 Senate rows written (the 15 Senate seats with `no election` in 2026 are dropped).
- Label mapping (`rating_raw` keeps the original): solid -> Safe; uncontested -> Safe; very likely -> Likely;
  likely -> Likely; lean -> Lean; tilt -> Tilt; toss-up -> Toss-up. State Navigate's scale has one more rung
  than the project's 9-point scale ("very likely" vs "likely"); both collapse to Likely here.
- `as_of_date` = 2026-10-03, the "latest ... model" date shown on the Texas state page. The per-district
  cells carry no date of their own.
- Caveat: the categorical rating and the model win probability are not always consistent (e.g. SD-9 is
  labelled `toss-up` while `win-probability` for the leading Democrat is 0.9275; HD-26 `toss-up` with 0.76 R).
  Both are reported as-is; use win probability as the continuous prior and the label as a cap.
- Chamber control (state page, 2026-10-03 model): State House 80% R, State Senate >99% R
  (chamber_ratings.csv). State Navigate's downloadable CSV endpoint (`api.statenavigate.com/...download.csv`)
  and the embed page could not be fetched from this environment (blocked by local policy), so the HTML
  pre-render is used instead; it contains the same fields.
- No district-level polls are listed on the public Texas pages (State Navigate's own polling program covers
  other states: PA, WI, GA, VT, MN, IA, VA, WV, UT).

### Sabato's Crystal Ball -- chamber-level only
- centerforpolitics.org returns HTTP 403 to non-browser clients (curl and WebFetch both blocked); the raw
  403 page is kept as evidence. The same Louis Jacobson column ("Handicapping the 2026 State Legislative Map:
  A First Look", 2026-01-22) is republished on rasmussenreports.com and was parsed from there:
  Texas Senate: Safe Republican; Texas House: Safe Republican ("GOP control of both chambers should be
  solid, but a blue midterm cycle gives Democrats an opportunity to pick off a few seats").
- A later Crystal Ball update exists (centerforpolitics.org/crystalball/?p=26241, Toss-up count 7) but is
  403-blocked and no republication naming Texas was found. The DLCC press summary of the first column does
  not mention Texas. Treat the Texas rating as of 2026-01-22 and possibly stale.

### Ballotpedia
- "State legislative battleground chambers, 2026" lists 18 chambers; neither Texas chamber is among them
  (chamber_ratings.csv: "Not a battleground chamber"). Ballotpedia's 2026 trifecta-vulnerability page
  (not parsed) calls the Texas trifecta vulnerable via the Senate.
- Texas House / Senate 2026 pages saved (`raw/ballotpedia_tx_*.html`); no Ballotpedia-authored
  battleground-district list exists on them.

### Target lists
- DLCC (dlcc.org/texas, "DLCC Target Races"): HD-34, 37, 41, 52, 67, 70, 74, 94, 108, 112, 118, 121, 133, 138
  and SD-9 (15 races) -> `Target-D`. DLCC target map page lists Texas as "Pick up House seats." No date on page.
- Texas HDCC (texashdcc.com/targeted-races): 17 House districts -> `Target-D`: the DLCC 14 plus HD-55, 61, 63.
  No date on page.
- RSLC: no formal target list page. Its "2026 Texas Candidate Spotlight" release (2026-08-26) names
  HD-118 (Borrego), HD-121 (LaHood), HD-112 (Button), HD-34 (Villalobos) and SD-9 (Wambsganss) -> `Target-R`.
- Texas GOP (texasgop.org) returns HTTP 403 (bot-block). Texas Democratic Party site has no target list.

### District-level polls (district_polls.csv)
- No 2026 Texas House or Senate district general-election poll with published toplines was found in news
  searches, the Texas Tribune polls tracker, or 270toWin (the only district polls indexed are primaries:
  UH Hobby School on HD-9, HD-126, HD-138 Republican primaries).
- One lead: a Republican internal poll of SD-9 (Sept 10-15 2026, n=600 LV, +/-3) reported by Mediaite as
  showing Republicans "trailing badly". Mediaite returns HTTP 403 to automated clients, so pollster and
  toplines could not be verified; the row is included with blank `dem_pct`/`rep_pct` and a `notes` column.
- A `hd108poll.pdf` on static.texastribune.org surfaced in search but is a July 2020 GQR poll (not used).

## Standardisation
`rating_std` uses Safe/Likely/Lean/Tilt D|R, Toss-up, or Target-D / Target-R for target lists. Extra columns
beyond the requested schema: `win_prob_leading`, `proj_margin_leading`, `leading_party`, `incumbent_party`,
`incumbent` (State Navigate) and `candidate` (target lists).
