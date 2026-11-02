"""Fetch Texas Legislative Council (Capitol Data Portal) Report 206 'Election Analysis'
spreadsheets: statewide-race general election returns aggregated to current legislative
district lines (PLANH2316 = Texas House, PLANS2168 = Texas Senate), plus district shapefiles.
Outputs: data/raw/tlc/tlc_district_returns.csv, tlc_district_turnout.csv, manifest.json
"""
import json, os, re, sys, datetime, pathlib, warnings
warnings.filterwarnings("ignore")
import pandas as pd, requests

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "tlc"
OUT.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"}
B = "https://data.capitol.texas.gov/dataset"
HD = "71af633c-21bf-42cf-ad48-4fe95593a897"   # PLANH2316 dataset id
SD = "70836384-f10c-423d-a36e-748d7e000872"   # PLANS2168 dataset id
PORTAL = {"H": "https://data.capitol.texas.gov/dataset/planh2316", "S": "https://data.capitol.texas.gov/dataset/plans2168"}

FILES = [
 # chamber, year, filename, url
 ("H", 2024, "planh2316_r206_election24g_v2.xls", f"{B}/{HD}/resource/30c0c5b7-c512-4a94-af01-afdcff39baf5/download/planh2316_r206_election24g.xls"),
 ("H", 2022, "planh2316_r206_election22g.xls",    f"{B}/{HD}/resource/2a562276-2ea9-4083-a702-b82105ac6a9d/download/planh2316_r206_election22g.xls"),
 ("H", 2020, "planh2316_r206_election20g.xls",    f"{B}/{HD}/resource/ee2b3b92-2c8f-4b55-bcca-136cf4db5ad7/download/planh2316r206_20g.xls"),
 ("H", 2018, "planh2316_r206_election18g.xls",    f"{B}/{HD}/resource/536fb105-b68a-42bc-bdc9-6c7a3cd7935b/download/planh2316r206_18g.xls"),
 ("S", 2024, "plans2168_r206_election24g.xls",    f"{B}/{SD}/resource/e3eda2c0-627e-4c29-b1bd-35c55f594800/download/plans2168_r206_election24g.xls"),
 ("S", 2022, "plans2168_r206_election22g.xls",    f"{B}/{SD}/resource/f423a696-46b8-457b-a65d-624207fe5246/download/plans2168_r206_election22g.xls"),
 ("S", 2020, "plans2168_r206_election20g.xls",    f"{B}/{SD}/resource/5f554ff3-9ca5-47ea-912f-8e58d74cb94b/download/plans2168r206_20g.xls"),
 ("S", 2018, "plans2168_r206_election18g.xls",    f"{B}/{SD}/resource/d358daa3-0a43-4c63-bc24-a9f35c8feceb/download/plans2168r206_18g.xls"),
]
SHAPES = [
 ("H", "planh2316.zip", f"{B}/{HD}/resource/a4d3230f-47f2-4253-85f3-51a6c3c9ad0a/download/planh2316.zip"),
 ("S", "plans2168.zip", f"{B}/{SD}/resource/8247dbc6-b942-4a29-813c-1ebc603a7236/download/plans2168.zip"),
]

def fetch(url, path, force=False):
    if path.exists() and path.stat().st_size > 1000 and not force:
        return False
    r = requests.get(url, headers=UA, timeout=120); r.raise_for_status()
    path.write_bytes(r.content); return True

def parse_r206(path, chamber, year):
    xl = pd.ExcelFile(path, engine="xlrd")
    turnout_rows, ret_rows = [], []
    # Sheet1: registration / turnout
    s1 = xl.parse(xl.sheet_names[0], header=None)
    for i in range(len(s1)):
        v = s1.iloc[i].tolist()
        vals = [x for x in v if str(x) != "nan"]
        if len(vals) >= 5 and re.fullmatch(r"\d+", str(vals[0]).strip()):
            turnout_rows.append(dict(chamber=chamber, year=year, district=int(vals[0]), registered=float(vals[1]),
                                     ssvr_share=float(vals[2]), turnout=float(vals[3]), turnout_rate=float(vals[4])))
    # Sheet2: race returns
    s2 = xl.parse(xl.sheet_names[1], header=None)
    # find header rows: the row containing 'District' in col 0 and race labels
    hdr = None
    for i in range(len(s2)):
        if any(str(v).strip().lower() == "district" for v in s2.iloc[i].tolist()):
            hdr = i; break
    if hdr is None:
        raise RuntimeError(f"no header in {path}")
    race_row, cand_row = s2.iloc[hdr], s2.iloc[hdr + 1]
    cols = []  # (votes_col, race, candidate, party)
    race = None
    for c in range(1, s2.shape[1]):
        rv = race_row.iat[c]
        if str(rv) != "nan" and str(rv).strip():
            race = str(rv).strip()
        cv = cand_row.iat[c]
        if str(cv) != "nan" and str(cv).strip():
            lab = str(cv).strip()
            m = re.match(r"^(.*)-([A-Z]{1,3})$", lab)
            cand, party = (m.group(1).strip(), m.group(2)) if m else (lab, "")
            cols.append((c, race, cand, party))
    for i in range(hdr + 2, len(s2)):
        rowvals = [str(v).strip() for v in s2.iloc[i].tolist() if str(v) != "nan"]
        d = rowvals[0] if rowvals else ""
        if not re.fullmatch(r"\d+", d):
            continue
        for c, race, cand, party in cols:
            v, p = s2.iat[i, c], s2.iat[i, c + 1]
            if str(v) == "nan": continue
            ret_rows.append(dict(chamber=chamber, year=year, district=int(d), race=race, candidate=cand,
                                 party=party, votes=float(v), pct=float(p) if str(p) != "nan" else None))
    return turnout_rows, ret_rows

def main():
    now = datetime.datetime.now().isoformat(timespec="minutes")
    manifest = []
    T, R = [], []
    for chamber, year, fn, url in FILES:
        p = OUT / fn
        new = fetch(url, p)
        manifest.append(dict(file=fn, url=url, retrieved_at=now if new else "cached", portal_page=PORTAL[chamber],
                             description=f"TLC Report 206 Election Analysis, {year} general election, by {'House' if chamber=='H' else 'Senate'} district"))
        t, r = parse_r206(p, chamber, year)
        T += t; R += r
        print(f"{chamber} {year}: {len(t)} districts, {len(r)} return cells, races={sorted(set(x['race'] for x in r))}")
    for chamber, fn, url in SHAPES:
        p = OUT / fn; new = fetch(url, p)
        manifest.append(dict(file=fn, url=url, retrieved_at=now if new else "cached", portal_page=PORTAL[chamber], description="District shapefile (NAD83 Lambert Conformal Conic)"))
        import zipfile
        d = OUT / ("shp_h" if chamber == "H" else "shp_s"); d.mkdir(exist_ok=True)
        zipfile.ZipFile(p).extractall(d)
    pd.DataFrame(T).to_csv(OUT / "tlc_district_turnout.csv", index=False)
    pd.DataFrame(R).to_csv(OUT / "tlc_district_returns.csv", index=False)
    mp = OUT / "manifest.json"
    old = json.loads(mp.read_text()) if mp.exists() else []
    keep = {m["file"]: m for m in old}
    for m in manifest:
        if m["retrieved_at"] == "cached" and m["file"] in keep: m["retrieved_at"] = keep[m["file"]]["retrieved_at"]
        elif m["retrieved_at"] == "cached": m["retrieved_at"] = now
        keep[m["file"]] = m
    mp.write_text(json.dumps(list(keep.values()), indent=1))

if __name__ == "__main__":
    main()
