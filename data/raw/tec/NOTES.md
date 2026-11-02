# TEC campaign finance (Texas House / Senate) - NOTES

Script: `pipeline/fetch/fetch_tec.py` (no arguments; `.venv/bin/python -I pipeline/fetch/fetch_tec.py`).
Output: `data/raw/tec/candidate_finance_2026.csv` (4,084 rows, one per TEC filer ID).

## Source
- Bulk zip: `https://prd.tecprd.ethicsefile.com/public/cf/public/TEC_CF_CSV.zip`,
  1,084,895,166 bytes (1.08 GB), server Last-Modified Sun 01 Nov 2026 11:35 GMT,
  retrieved 2026-11-01T21:08 (local). The page https://www.ethics.state.tx.us/search/cf/
  labels it "Campaign Finance CSV Database (As of 10/31/2026)". The URL in the task brief
  (`https://www.ethics.state.tx.us/data/search/cf/TEC_CF_CSV.zip`) returns 404; the
  `/data/search/cf/` directory index returns an empty 200 page. The zip link is now on the
  search page and hosted on `prd.tecprd.ethicsefile.com`.
- Layout docs saved in `docs/`: CFS-ReadMe.txt, CFS-Codes.txt, CampaignFinanceCSVFileFormat.pdf,
  plus the search page HTML.
- Only `filers.csv` (8.9 MB) and `cover.csv` (197 MB, streamed in 250k-row chunks) are read.
  The 126 contribs_*/expend_* files (9.5 GB uncompressed) are never opened. Nothing in
  `download/` is executed.

## Method
- Legislative filers = any row in filers.csv with STATEREP/STATESEN in ctaSeekOfficeCd,
  contestSeekOfficeCd, or filerHoldOfficeCd (4,127 rows -> 4,084 unique filer IDs; filers.csv
  repeats 43 IDs, one row per treasurer record; the row with the most legislative codes is kept).
- Cover-sheet rows cleaned: drop `infoOnlyFlag = Y` (superseded by a correction, 5,359 rows),
  drop rows with impossible period dates (typos like 29920630; 200 rows), drop Speaker-race
  reports (`formTypeCd = SPK`, which carry no totals), dedupe on
  (filer, reportTypeCd1, periodStartDt, periodEndDt) keeping the latest received (so a
  CORCOH correction replaces the original).
- `total_contributions_2025_2026` / `total_expenditures_2025_2026` = sum of
  `totalContribAmount` / `totalExpendAmount` over cleaned reports with periodStartDt >= 2025-01-01.
  Note: TEC semiannual/pre-election reports are non-overlapping, so summing is correct, but FINAL,
  UNEXPCONT and A15DAYAFT reports are included too (small).
- `latest_cash_on_hand` = `contribsMaintainedAmount` ("total political contributions maintained
  as of the last day of the period") on the latest cleaned report of any year; `latest_loan_balance`
  likewise. `latest_report_period_end` tells you how fresh it is.
- `office_sought`: if the filer's latest 2025-2026 report declares a NON-legislative office
  (e.g. Gina Hinojosa -> GOVERNOR, Mayes Middleton -> ATTYGEN, 27 filers), that raw TEC code is
  placed in `office_sought` and `seeking_other_office_2026 = True`, so a downstream filter
  `office_sought in {State Representative, State Senator}` excludes statewide/judicial money.
  Otherwise the latest report's declared office, then filers.csv contest / CTA / held office
  (see `office_source`).
- `filer_name_norm` = "last, first" lowercase, punctuation removed (suffixes like II/III and
  honorifics dropped since they live in separate TEC fields). `name_last`, `name_first`,
  `name_nickname` are also provided for fuzzy matching.

## Coverage
- 817 filers have at least one 2025-2026 report: 693 State Representative, 97 State Senator,
  27 seeking another office. 156 House districts and 31 Senate districts represented.
- Latest report in the data: period end 2026-10-24 (received through 2026-10-31).
- The 8-day pre-general report (due 2026-10-26, period 2026-09-25 to 2026-10-24) IS included:
  290 legislative filers have it (255 State Representative, 27 State Senator, 8 legislators
  running for another office). Filers whose latest report is the July semiannual (period end 2026-06-30,
  284 filers) are mostly non-nominees (lost primaries, unopposed-modified filers, or
  officeholders not on the 2026 ballot). Late filers for the 8-day report would be missing.

## Missing / caveats
- Party is NOT in filers.csv or cover.csv for candidates; `politicalPartyCd` is populated on
  only 7 of the cycle reports. `party_if_available` is therefore blank for almost everyone.
  Get party from the SOS candidate list / Ballotpedia downstream.
- Totals are cover-sheet declared totals (what the candidate reported), not re-summed from
  itemized schedules. Corrections are handled via infoOnlyFlag; a report filed twice without
  the flag would be deduped by period.
- Modified-reporting candidates (under $500 raised/spent, `500EXCEED`) and no-activity reports
  show zeros, not blanks.
- One filer has the odd office code "T" (raw TEC data); 1,361 legislative filers have no status.
- `CTA_Office_Sought.xlsx` (TEC list of candidates with treasurer appointments) was downloaded for
  reference; it has no party field and was not used.
- The fallback TEC filer search (https://www.ethics.state.tx.us/search/cf/) was not needed.
