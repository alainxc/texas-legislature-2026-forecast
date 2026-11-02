#!/usr/bin/env python
"""fetch_tec.py - Texas Ethics Commission campaign-finance receipts for
Texas House / Texas Senate filers (2026 cycle candidate-strength input).

Runnable with no arguments. Writes into <project>/data/raw/tec/.

Steps
1. Download the TEC bulk "Campaign Finance CSV Database" zip
   (https://prd.tecprd.ethicsefile.com/public/cf/public/TEC_CF_CSV.zip,
   linked from https://www.ethics.state.tx.us/search/cf/) into
   data/raw/tec/download/ unless an identical-size copy is already there.
   Nothing in download/ is ever executed.
2. Read filers.csv (filer index) fully, and stream cover.csv (cover-sheet
   totals, ~200 MB) in chunks. The giant contribs_*/expend_* files are never
   opened.
3. Keep every filer whose office sought / held is STATEREP or STATESEN.
4. Aggregate cover-sheet totals per filer for reports whose period starts on
   or after 2025-01-01 (the 2026 cycle), plus the latest cash on hand.
5. Write candidate_finance_2026.csv, the raw filtered subsets that were
   parsed, and manifest.json.

Deterministic: same input zip -> same outputs. The download timestamp is
persisted in download/download_meta.json so re-runs that skip the download
keep the original retrieval time.
"""
import csv
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
import zipfile

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT_DIR = os.path.join(PROJECT, "data", "raw", "tec")
DL_DIR = os.path.join(OUT_DIR, "download")
DOC_DIR = os.path.join(OUT_DIR, "docs")

ZIP_URL = "https://prd.tecprd.ethicsefile.com/public/cf/public/TEC_CF_CSV.zip"
INDEX_URL = "https://www.ethics.state.tx.us/search/cf/"
DOC_URLS = {
    "CFS-ReadMe.txt": "https://www.ethics.state.tx.us/data/search/cf/CFS-ReadMe.txt",
    "CFS-Codes.txt": "https://www.ethics.state.tx.us/data/search/cf/CFS-Codes.txt",
    "CampaignFinanceCSVFileFormat.pdf": "https://www.ethics.state.tx.us/data/search/cf/CampaignFinanceCSVFileFormat.pdf",
}
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

LEG_OFFICES = {"STATEREP": "State Representative", "STATESEN": "State Senator"}
CYCLE_START = "20250101"
EIGHT_DAY_DUE = "20261026"  # 8-day pre-general report due date (general 2026-11-03)

COVER_COLS = [
    "formTypeCd", "reportInfoIdent", "receivedDt", "infoOnlyFlag", "filerIdent",
    "filerTypeCd", "filerName", "reportTypeCd1", "reportTypeCd2", "reportTypeCd3",
    "dueDt", "filedDt", "periodStartDt", "periodEndDt", "totalContribAmount",
    "totalExpendAmount", "loanBalanceAmount", "contribsMaintainedAmount",
    "electionDt", "electionTypeCd", "noActivityFlag", "politicalPartyCd",
    "filerSeekOfficeCd", "filerSeekOfficeDistrict", "filerHoldOfficeCd",
    "filerHoldOfficeDistrict",
]
FILER_COLS = [
    "filerIdent", "filerTypeCd", "filerName", "filerPersentTypeCd",
    "filerNameOrganization", "filerNameLast", "filerNameSuffixCd",
    "filerNameFirst", "filerNameShort", "filerStreetCity",
    "ctaSeekOfficeCd", "ctaSeekOfficeDistrict", "contestSeekOfficeCd",
    "contestSeekOfficeDistrict", "filerHoldOfficeCd", "filerHoldOfficeDistrict",
    "filerFilerpersStatusCd", "filerEffStartDt", "filerEffStopDt",
    "treasEffStartDt",
]


def now_iso():
    return dt.datetime.now().strftime("%Y-%m-%dT%H:%M")


def head_content_length(url):
    try:
        out = subprocess.run(
            ["curl", "-sIL", "-A", UA, url], capture_output=True, text=True,
            timeout=120, check=False).stdout
        sizes = re.findall(r"(?i)^content-length:\s*(\d+)", out, flags=re.M)
        return int(sizes[-1]) if sizes else None
    except Exception:
        return None


def download(url, dest, timeout=1800):
    """curl with resume; returns True on success."""
    r = subprocess.run(
        ["curl", "-sS", "-L", "-A", UA, "-C", "-", "-o", dest, url],
        timeout=timeout, check=False)
    return r.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 0


def ensure_zip():
    os.makedirs(DL_DIR, exist_ok=True)
    zpath = os.path.join(DL_DIR, "TEC_CF_CSV.zip")
    meta_path = os.path.join(DL_DIR, "download_meta.json")
    remote = head_content_length(ZIP_URL)
    have = os.path.getsize(zpath) if os.path.exists(zpath) else 0
    need = not (have > 0 and (remote is None or remote == have) and os.path.exists(meta_path))
    if need:
        if have and remote and remote != have:
            os.remove(zpath)  # size changed upstream: fresh download
        print(f"Downloading {ZIP_URL} ({remote} bytes) ...", flush=True)
        if not download(ZIP_URL, zpath):
            sys.exit("ERROR: bulk zip download failed")
        meta = {"url": ZIP_URL, "retrieved_at": now_iso(),
                "size_bytes": os.path.getsize(zpath),
                "remote_content_length": remote}
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)
    with open(meta_path) as f:
        meta = json.load(f)
    return zpath, meta


def ensure_docs():
    os.makedirs(DOC_DIR, exist_ok=True)
    entries = []
    for name, url in DOC_URLS.items():
        p = os.path.join(DOC_DIR, name)
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            download(url, p, timeout=300)
        entries.append({"file": f"docs/{name}", "url": url,
                        "retrieved_at": dt.datetime.fromtimestamp(
                            os.path.getmtime(p)).strftime("%Y-%m-%dT%H:%M"),
                        "description": "TEC CSV record layout / code documentation"})
    p = os.path.join(DOC_DIR, "search_cf_page.html")
    if not os.path.exists(p):
        download(INDEX_URL, p, timeout=120)
    entries.append({"file": "docs/search_cf_page.html", "url": INDEX_URL,
                    "retrieved_at": dt.datetime.fromtimestamp(
                        os.path.getmtime(p)).strftime("%Y-%m-%dT%H:%M"),
                    "description": "TEC campaign finance search page that links the bulk CSV zip"})
    return entries


def valid_date(s, received=None):
    """TEC dates are yyyyMMdd strings; some are typos (e.g. 29920630)."""
    if not s or len(s) != 8 or not s.isdigit():
        return False
    try:
        d = dt.datetime.strptime(s, "%Y%m%d").date()
    except ValueError:
        return False
    if d.year < 1990 or d > dt.date.today() + dt.timedelta(days=400):
        return False
    if received and valid_date(received):
        r = dt.datetime.strptime(received, "%Y%m%d").date()
        if d > r + dt.timedelta(days=60):  # period cannot end long after receipt
            return False
    return True


def norm_name(last, first, full):
    """'last name, first name' lowercase, no punctuation."""
    if last:
        s = f"{last}, {first or ''}".strip().rstrip(",")
    else:
        s = re.sub(r"\s*\([^)]*\)", "", full or "")  # drop '(Mr.)' etc.
    s = s.lower()
    s = re.sub(r"[^a-z0-9, ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*,\s*", ", ", s)
    return s


def to_num(x):
    try:
        return float(x) if x not in ("", None) else 0.0
    except ValueError:
        return 0.0


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    zpath, zmeta = ensure_zip()
    manifest = [{
        "file": "download/TEC_CF_CSV.zip", "url": ZIP_URL,
        "retrieved_at": zmeta["retrieved_at"],
        "size_bytes": zmeta["size_bytes"],
        "description": "TEC bulk Campaign Finance CSV Database (all filers, all years). "
                       "Linked from " + INDEX_URL + ". Only filers.csv and cover.csv are read.",
    }]
    manifest += ensure_docs()
    # Small TEC Excel list of candidates with treasurer appointments (office sought, no party);
    # kept for reference only - not used in the aggregate.
    cta_url = "https://www.ethics.state.tx.us/data/search/cf/CTA_Office_Sought.xlsx"
    cta_path = os.path.join(DL_DIR, "CTA_Office_Sought.xlsx")
    if not os.path.exists(cta_path) or os.path.getsize(cta_path) == 0:
        download(cta_url, cta_path, timeout=300)
    if os.path.exists(cta_path):
        manifest.append({"file": "download/CTA_Office_Sought.xlsx", "url": cta_url,
                         "retrieved_at": dt.datetime.fromtimestamp(
                             os.path.getmtime(cta_path)).strftime("%Y-%m-%dT%H:%M"),
                         "description": "TEC list of candidates/officeholders with treasurer appointment "
                                        "and CTA office sought (reference only; no party field)."})

    z = zipfile.ZipFile(zpath)
    zip_members = {i.filename: {"size": i.file_size,
                                "date": "%04d-%02d-%02d" % i.date_time[:3]}
                   for i in z.infolist()}

    # ---- filers ----------------------------------------------------------
    filers = pd.read_csv(z.open("filers.csv"), dtype=str, keep_default_na=False,
                         usecols=FILER_COLS, low_memory=False)
    is_leg = (filers.ctaSeekOfficeCd.isin(LEG_OFFICES)
              | filers.contestSeekOfficeCd.isin(LEG_OFFICES)
              | filers.filerHoldOfficeCd.isin(LEG_OFFICES))
    leg = filers[is_leg].copy()
    # filers.csv repeats some filerIdent values (one row per treasurer record);
    # keep one row per filer, preferring the row with the most legislative office codes.
    leg["_score"] = (leg.ctaSeekOfficeCd.isin(LEG_OFFICES).astype(int)
                     + leg.contestSeekOfficeCd.isin(LEG_OFFICES).astype(int)
                     + leg.filerHoldOfficeCd.isin(LEG_OFFICES).astype(int))
    leg["_row"] = range(len(leg))
    leg = (leg.sort_values(["filerIdent", "_score", "_row"])
              .drop_duplicates("filerIdent", keep="last")
              .drop(columns=["_score", "_row"]))
    leg_ids = set(leg.filerIdent)
    leg.to_csv(os.path.join(OUT_DIR, "filers_legislative_raw.csv"), index=False)
    manifest.append({"file": "filers_legislative_raw.csv", "url": ZIP_URL,
                     "retrieved_at": zmeta["retrieved_at"],
                     "description": "Raw rows of filers.csv (from the bulk zip) whose CTA/contest/held "
                                    "office is STATEREP or STATESEN; selected columns."})

    # ---- cover sheets (streamed) ----------------------------------------
    parts = []
    for chunk in pd.read_csv(z.open("cover.csv"), dtype=str, keep_default_na=False,
                             usecols=COVER_COLS, chunksize=250_000):
        parts.append(chunk[chunk.filerIdent.isin(leg_ids)])
    cover = pd.concat(parts, ignore_index=True)
    cover.to_csv(os.path.join(OUT_DIR, "cover_legislative_raw.csv"), index=False)
    manifest.append({"file": "cover_legislative_raw.csv", "url": ZIP_URL,
                     "retrieved_at": zmeta["retrieved_at"],
                     "description": "Raw rows of cover.csv (cover-sheet totals) for the legislative "
                                    "filers above, all years; selected columns."})

    # Clean: drop superseded reports (infoOnlyFlag=Y), invalid dates; dedupe
    cover["ok_dates"] = [valid_date(s) and valid_date(e, r)
                         for s, e, r in zip(cover.periodStartDt, cover.periodEndDt, cover.receivedDt)]
    # Speaker-race reports (formTypeCd SPK) carry no totals; they would only inflate counts.
    valid = cover[(cover.infoOnlyFlag != "Y") & cover.ok_dates & (cover.formTypeCd != "SPK")].copy()
    valid = valid.sort_values(["filerIdent", "periodEndDt", "receivedDt", "reportInfoIdent"])
    valid = valid.drop_duplicates(
        subset=["filerIdent", "reportTypeCd1", "periodStartDt", "periodEndDt"], keep="last")
    for c in ("totalContribAmount", "totalExpendAmount", "contribsMaintainedAmount", "loanBalanceAmount"):
        valid[c + "_n"] = valid[c].map(to_num)

    cyc = valid[valid.periodStartDt >= CYCLE_START]
    agg = cyc.groupby("filerIdent").agg(
        reports_count=("reportInfoIdent", "size"),
        total_contributions_2025_2026=("totalContribAmount_n", "sum"),
        total_expenditures_2025_2026=("totalExpendAmount_n", "sum"),
    )
    cyc_sorted = cyc.sort_values(["filerIdent", "periodEndDt", "receivedDt"])
    has_8day = (cyc_sorted.assign(e8=(cyc_sorted.reportTypeCd1 == "E08DAYBEF")
                                  & (cyc_sorted.dueDt >= "20261001"))
                .groupby("filerIdent").e8.any())
    latest_all = (valid[valid.contribsMaintainedAmount != ""]
                  .sort_values(["filerIdent", "periodEndDt", "receivedDt"])
                  .groupby("filerIdent").tail(1).set_index("filerIdent"))
    # latest 2025-2026 report with a declared office sought (detects legislators
    # running for Governor, AG, judge, etc. - their money is not House/Senate money)
    latest_cyc = (cyc_sorted.groupby("filerIdent").tail(1).set_index("filerIdent"))
    # Party: rare on COH cover sheets; take any non-blank value on cycle reports
    party = (cyc[cyc.politicalPartyCd != ""].sort_values(["filerIdent", "periodEndDt"])
             .groupby("filerIdent").politicalPartyCd.last())

    # ---- assemble ---------------------------------------------------------
    rows = []
    for r in leg.itertuples(index=False):
        fid = r.filerIdent
        la = latest_all.loc[fid] if fid in latest_all.index else None
        # office sought: latest report's declared office if legislative, else filer index
        office_cd, district, src = "", "", ""
        lc = latest_cyc.loc[fid] if fid in latest_cyc.index else None
        other_office = (lc is not None and lc.filerSeekOfficeCd not in ("", "NONE")
                        and lc.filerSeekOfficeCd not in LEG_OFFICES)
        if other_office:
            office_cd, district, src = lc.filerSeekOfficeCd, lc.filerSeekOfficeDistrict, "latest_report_seek_other"
        elif la is not None and la.filerSeekOfficeCd in LEG_OFFICES:
            office_cd, district, src = la.filerSeekOfficeCd, la.filerSeekOfficeDistrict, "latest_report_seek"
        elif r.contestSeekOfficeCd in LEG_OFFICES:
            office_cd, district, src = r.contestSeekOfficeCd, r.contestSeekOfficeDistrict, "filers_contest"
        elif r.ctaSeekOfficeCd in LEG_OFFICES:
            office_cd, district, src = r.ctaSeekOfficeCd, r.ctaSeekOfficeDistrict, "filers_cta"
        elif r.filerHoldOfficeCd in LEG_OFFICES:
            office_cd, district, src = r.filerHoldOfficeCd, r.filerHoldOfficeDistrict, "filers_held_only"
        a = agg.loc[fid] if fid in agg.index else None
        rows.append({
            "filer_id": fid,
            "filer_name": r.filerName,
            "filer_name_norm": norm_name(r.filerNameLast, r.filerNameFirst, r.filerName),
            "name_last": r.filerNameLast,
            "name_first": r.filerNameFirst,
            "name_nickname": r.filerNameShort,
            "filer_type": r.filerTypeCd,
            "office_sought": LEG_OFFICES.get(office_cd, office_cd),
            "seeking_other_office_2026": bool(other_office),
            "latest_cycle_report_seek_office_cd": lc.filerSeekOfficeCd if lc is not None else "",
            "latest_cycle_report_seek_district": lc.filerSeekOfficeDistrict if lc is not None else "",
            "district": re.sub(r"^0+(?=\d)", "", district.strip()),
            "office_source": src,
            "office_held": LEG_OFFICES.get(r.filerHoldOfficeCd, r.filerHoldOfficeCd),
            "district_held": re.sub(r"^0+(?=\d)", "", r.filerHoldOfficeDistrict.strip()),
            "filer_status": r.filerFilerpersStatusCd,
            "party_if_available": party.get(fid, ""),
            "reports_count": int(a.reports_count) if a is not None else 0,
            "total_contributions_2025_2026": round(float(a.total_contributions_2025_2026), 2) if a is not None else 0.0,
            "total_expenditures_2025_2026": round(float(a.total_expenditures_2025_2026), 2) if a is not None else 0.0,
            "latest_cash_on_hand": round(float(la.contribsMaintainedAmount_n), 2) if la is not None else "",
            "latest_loan_balance": round(float(la.loanBalanceAmount_n), 2) if la is not None else "",
            "latest_report_period_start": la.periodStartDt if la is not None else "",
            "latest_report_period_end": la.periodEndDt if la is not None else "",
            "latest_report_type": la.reportTypeCd1 if la is not None else "",
            "latest_report_received": la.receivedDt if la is not None else "",
            "has_8day_pre_general_2026": bool(has_8day.get(fid, False)),
            "city": r.filerStreetCity,
        })
    out = pd.DataFrame(rows).sort_values(["office_sought", "district", "filer_name_norm", "filer_id"])
    for c in ("latest_report_period_start", "latest_report_period_end", "latest_report_received"):
        out[c] = out[c].map(lambda s: f"{s[:4]}-{s[4:6]}-{s[6:]}" if len(s) == 8 else s)
    out_path = os.path.join(OUT_DIR, "candidate_finance_2026.csv")
    out.to_csv(out_path, index=False, quoting=csv.QUOTE_MINIMAL)
    manifest.append({"file": "candidate_finance_2026.csv", "url": ZIP_URL,
                     "retrieved_at": zmeta["retrieved_at"],
                     "description": "Per-filer aggregate for Texas House/Senate filers: 2025-2026 "
                                    "contribution/expenditure totals from cover sheets (period start >= "
                                    "2025-01-01, superseded reports and invalid dates excluded, deduped by "
                                    "report type+period), latest cash on hand (contribsMaintainedAmount)."})

    # ---- stats for NOTES / report ------------------------------------------
    active = out[out.reports_count > 0]
    e8 = cyc[(cyc.reportTypeCd1 == "E08DAYBEF") & (cyc.dueDt >= "20261001")]
    stats = {
        "zip_url": ZIP_URL, "zip_size_bytes": zmeta["size_bytes"],
        "zip_retrieved_at": zmeta["retrieved_at"],
        "zip_member_dates": {k: v for k, v in zip_members.items() if k in ("filers.csv", "cover.csv")},
        "filers_total": int(len(filers)), "filers_legislative": int(len(leg)),
        "filers_legislative_by_type": leg.filerTypeCd.value_counts().to_dict(),
        "filers_with_2025_2026_reports": int(len(active)),
        "filers_statehouse_with_reports": int((active.office_sought == "State Representative").sum()),
        "filers_statesen_with_reports": int((active.office_sought == "State Senator").sum()),
        "filers_seeking_other_office_2026": int(active.seeking_other_office_2026.sum()),
        "other_offices_sought": active[active.seeking_other_office_2026].office_sought.value_counts().to_dict(),
        "filers_with_8day_pre_general_flag": int(active.has_8day_pre_general_2026.sum()),
        "cover_rows_legislative_all_years": int(len(cover)),
        "cover_rows_dropped_superseded": int((cover.infoOnlyFlag == "Y").sum()),
        "cover_rows_dropped_bad_dates": int((~cover.ok_dates).sum()),
        "cycle_reports_2025_2026": int(len(cyc)),
        "cycle_report_types": cyc.reportTypeCd1.value_counts().to_dict(),
        "latest_period_end_in_data": cyc.periodEndDt.max(),
        "latest_received_in_data": cyc.receivedDt.max(),
        "eight_day_pre_general_2026_reports": int(len(e8)),
        "eight_day_pre_general_2026_filers": int(e8.filerIdent.nunique()),
        "eight_day_due_dates": sorted(e8.dueDt.unique().tolist()),
        "eight_day_period_end_dates": sorted(e8.periodEndDt.unique().tolist()),
        "party_available_count": int((out.party_if_available != "").sum()),
        "generated_at": now_iso(),
    }
    with open(os.path.join(OUT_DIR, "run_stats.json"), "w") as f:
        json.dump(stats, f, indent=2)
    manifest.append({"file": "run_stats.json", "url": ZIP_URL,
                     "retrieved_at": zmeta["retrieved_at"],
                     "description": "Summary statistics of the fetch_tec.py run (coverage, counts)."})
    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(json.dumps(stats, indent=2))
    print(f"wrote {out_path}: {len(out)} rows")


if __name__ == "__main__":
    main()
