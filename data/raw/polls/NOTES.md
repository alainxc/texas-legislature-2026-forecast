# Polls layer: NOTES (retrieved 2026-11-01)

Script: `pipeline/fetch/fetch_polls.py` (no arguments; re-downloads every raw file into this
directory, parses, writes `polls.csv`, `pollster_ratings.csv`, `manifest.json`).

## Nominees (from the Wikipedia infoboxes / "Nominee" rows, as of 2026-11-01)
- Governor 2026: Greg Abbott (R, incumbent) vs **Gina Hinojosa** (D). Libertarian: Pat Dixon.
- U.S. Senate 2026: **Ken Paxton** (R; beat John Cornyn in the May 26, 2026 runoff) vs
  **James Talarico** (D; won the March 3, 2026 primary). Libertarian: Ted Brown.

## What is in polls.csv (3,231 rows)

| race | rows | field end dates | source |
|---|---|---|---|
| tx_gov | 74 | 2026-01-12 .. 2026-11-01 | Wikipedia 2026 TX gubernatorial, Abbott vs Hinojosa table |
| tx_sen | 87 | 2025-09-24 .. 2026-11-01 | Wikipedia 2026 US Senate in TX, Paxton vs Talarico table |
| tx_generic | 24 | 2025-08-29 .. 2026-10-21 | Wikipedia 2026 US House in TX "Statewide polling" (22) + Texas Public Opinion Research Aug 2025 generic question filed on the gov/sen pages (2) |
| tx_abbott_approval | 11 | waves Feb 2025 .. Oct 2026 | Texas Politics Project job-approval trend (Highcharts JSON in page) |
| us_generic | 723 | 2024-12-11 .. 2026-10-30 | Wikipedia "2026 United States elections", section Polling (2025 + 2026 tables) |
| tx_gov_2022 | 50 | 2021-06-17 .. 2022-11-05 | Wikipedia 2022 TX gubernatorial, Abbott vs O'Rourke |
| tx_pres_2024 | 94 | 2022-06-10 .. 2024-11-04 | Wikipedia 2024 pres. in TX: Trump vs Harris (53, incl. full-field tables with West/Stein/Oliver) + Trump vs Biden (41, through 2024-07-18, dem_candidate = "Joe Biden") |
| tx_sen_2024 | 59 | 2023-05-17 .. 2024-11-04 | Wikipedia 2024 US Senate in TX, Cruz vs Allred |
| us_generic_2022 | 1,363 | 2020-11-23 .. 2022-11-08 | FiveThirtyEight generic_ballot_polls_historical.csv (Wayback snapshot 2025-03-05) |
| us_generic_2024 | 735 | 2022-11-11 .. 2024-11-03 | same file, cycle 2024 |
| tx_abbott_approval_2022 | 11 | waves Feb 2021 .. Oct 2022 | Texas Politics Project trend, same page |

Columns: race, pollster, sponsor, partisan (D/R/blank), start_date, end_date (ISO), sample_size,
population (LV/RV/A/V as printed), dem_pct, rep_pct, other_pct, approve_pct, disapprove_pct,
dem_candidate, rep_candidate, source_url, retrieved_at, internal (true when the poll carries a
(D)/(R) partisan marker on Wikipedia, or FiveThirtyEight's internal/partisan flag).

## Parsing conventions (so downstream knows what the numbers mean)
- Wikipedia footnote markers (`[12]`, `[a]`, `[AB]`) are stripped. Separator rows (primary dates,
  "Average" rows, events) are dropped because their date/percent cells do not parse.
- `pollster` / `sponsor`: Wikipedia prints "Sponsor/Pollster" (e.g. "New York Times/Siena
  University"). The LAST slash segment is kept as `pollster`, the rest as `sponsor`. This is
  right for most rows but inverted for a few (e.g. "Verasight/VoteHub" -> pollster VoteHub,
  sponsor Verasight; Verasight is the field house). Fix by hand-mapping downstream if needed.
- Wikipedia pollster names differ from FiveThirtyEight rating names ("Siena University" vs
  "Siena College", "Marist University" vs "Marist College", "UT Tyler" vs "University of Texas
  at Tyler Center for Opinion Research"). A name crosswalk is needed before joining
  `pollster_ratings.csv`; ~25 Texas pollsters in tx_gov/tx_sen have no exact-name match and
  several newer firms (Quantus, Kreate, Overton, A2 Insights, ActiVote, Texas Public Opinion
  Research, Texas Southern University, Pulse Decision Science...) are not rated at all.
- `other_pct` = sum of every numeric non-D/R column in the table (third-party candidates +
  Other + Undecided). Blank when none of those cells is numeric. For the Verasight/VoteHub rows
  Wikipedia prints the same number under Other and Undecided, so other_pct double counts there
  (20/12/22/14). For the FiveThirtyEight rows other_pct is the `ind` column, almost always blank.
- Multiple rows per poll are legitimate: LV and RV samples, with/without leaners, full-field vs
  head-to-head (2024 pres). Dedup only removes identical rows that Wikipedia filed on two pages.
- The Texas Public Opinion Research Aug 27-29, 2025 generic-ballot poll appears on both the
  gov page (R 49) and the Senate page (R 48); both transcriptions are kept (2 rows).
- Approval rows: `approve_pct`/`disapprove_pct` are the Texas Politics Project trend values for
  the full sample. The trend page only gives a month label; field dates were matched from
  UT/Texas Politics Project rows on the saved Wikipedia pages (year-month of end date). Dates
  are filled for the five 2026 waves (Feb, Apr, Jun, Aug, Oct 2026) and BLANK for the 2025 and
  2021-2022 waves (no UT/TPP rows on the saved pages). The wave label is always kept in
  `sponsor`. sample_size/population are left blank for approval rows on purpose: Wikipedia
  often lists a subsample (primary electorate or LV screen) for these polls, which is not the
  approval base. Waves Dec 2022 - Dec 2024 are in the raw page but not written (not requested).
- TPP trend page holds several charts with the same title; the first in document order is the
  overall electorate (the others are by party ID). The script takes the first.

## Missing / blocked / substituted
- Wikipedia has NO standalone "Opinion polling for the 20xx United States House of
  Representatives elections" page for 2022, 2024 or 2026 (404; API says missing). For 2026
  the full poll list lives on "2026 United States elections" (used). The 2026 House page only
  has an aggregate table (saved as wiki_2026_us_house.html for traceability, not parsed).
  For 2022/2024 the election-eve revisions of the House pages (oldid 1120816054 / 1256238281)
  contain no generic-ballot table either, so the national generic ballot backtest uses the
  FiveThirtyEight generic_ballot_polls_historical.csv. FiveThirtyEight's polls site was taken
  down in 2025 (projects.fivethirtyeight.com now redirects to an ABC News HTML page), so the
  script pulls a pinned Wayback Machine snapshot
  (web.archive.org/web/20250305204633id_/...). web.archive.org rate-limits (HTTP 429) after a
  few requests; the script backs off (15/30/45/60/75 s) and, if it still fails but a copy from
  a previous run exists, keeps that copy and flags it in manifest.json
  (`cached_from_previous_run: true`). The manifest from the 2026-11-01 run carries that flag.
- RealClearPolling: skipped per instructions (403 for bots). RCP values only appear inside the
  Wikipedia aggregate tables, which are not parsed.
- Morning Consult governor approval (pro.morningconsult.com/trackers/governor-approval-ratings):
  returns a JS shell with no Abbott data in the HTML; not used.
- Silver Bulletin pollster ratings: natesilver.net/p/pollster-ratings is 404; no public CSV
  found. Used FiveThirtyEight `pollster-ratings-combined.csv` from the GitHub data repo
  (540 pollsters, columns numeric_grade, POLLSCORE, wtd_avg_transparency, bias_ppm, ...).
  This table was last updated in 2024-25; newer firms are absent.
- 270toWin (TX gov/sen 2026 pages) and the Texas Politics Project gov/sen poll trackers were
  saved as cross-check raw files only (they list the last ~10 and ~30 polls); Wikipedia is the
  superset, so they are not parsed into polls.csv to avoid duplicates. Spot check: TPP tracker
  and 270toWin toplines agree with the Wikipedia rows (e.g. YouGov Oct 26-29 50/49 gov, 47/51 sen).
- Hypothetical matchups are excluded: 2026 gov Abbott vs Chris Bell (1 poll); 2026 Senate
  Cornyn/Hunt vs Talarico/Crockett/Allred/O'Rourke/Castro tables; 2022 gov three-way polls with
  Matthew McConaughey (I) and Abbott vs Julian Castro / generic opponent; 2024 pres tables
  without Trump or without Harris/Biden (Haley, DeSantis, RFK-only, etc.).
- 2 of 89 rows of the Wikipedia Paxton-Talarico table and 3 of 62 Cruz-Allred rows are
  separator/event rows and were dropped; no poll rows were lost.
- No 2022 Texas generic-ballot or 2022 statewide approval beyond the TPP trend was collected
  (not requested).
