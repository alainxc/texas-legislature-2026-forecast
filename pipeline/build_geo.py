"""Convert TLC district shapefiles to compact simplified GeoJSON-like JSON for the SVG maps.
Coordinates stay in the TLC Lambert Conformal Conic projection (already a good map projection
for Texas) and are rescaled to a 0..1000 viewBox. Simplified with Douglas-Peucker."""
import json, pathlib, math, warnings
warnings.filterwarnings("ignore")
import shapefile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = {"house": ROOT/"data/raw/tlc/shp_h/PLANH2316/PLANH2316", "senate": ROOT/"data/raw/tlc/shp_s/PLANS2168/PLANS2168"}
OUT = ROOT/"data/processed"; OUT.mkdir(parents=True, exist_ok=True)

def dp(points, tol):
    if len(points) < 3: return points
    def perp(p, a, b):
        ax, ay = a; bx, by = b; px, py = p
        dx, dy = bx-ax, by-ay
        if dx == dy == 0: return math.hypot(px-ax, py-ay)
        t = max(0, min(1, ((px-ax)*dx+(py-ay)*dy)/(dx*dx+dy*dy)))
        return math.hypot(px-(ax+t*dx), py-(ay+t*dy))
    stack = [(0, len(points)-1)]; keep = [False]*len(points); keep[0]=keep[-1]=True
    while stack:
        s, e = stack.pop()
        md, mi = 0, -1
        for i in range(s+1, e):
            d = perp(points[i], points[s], points[e])
            if d > md: md, mi = d, i
        if md > tol:
            keep[mi] = True; stack += [(s, mi), (mi, e)]
    return [p for p, k in zip(points, keep) if k]

def ring_area(r):
    return 0.5*abs(sum(r[i][0]*r[(i+1)%len(r)][1]-r[(i+1)%len(r)][0]*r[i][1] for i in range(len(r))))

def main():
    # common bbox across both chambers (Texas outline) so both maps share a frame
    readers = {k: shapefile.Reader(str(v)) for k, v in SRC.items()}
    bb = readers["house"].bbox
    xmin, ymin, xmax, ymax = bb
    scale = 1000.0/max(xmax-xmin, ymax-ymin)
    def tx(p): return (round((p[0]-xmin)*scale, 1), round((ymax-p[1])*scale, 1))
    for key, r in readers.items():
        tol = 800 if key == "house" else 1200   # metres in projected units
        feats = []
        for sr in r.iterShapeRecords():
            d = int(sr.record[0]); s = sr.shape
            parts = list(s.parts)+[len(s.points)]
            rings = []
            for i in range(len(parts)-1):
                ring = s.points[parts[i]:parts[i+1]]
                if ring_area(ring) < 2.5e6 and i > 0: continue   # drop tiny islands (<2.5 km2)
                simp = dp(ring, tol)
                if len(simp) >= 4: rings.append([tx(p) for p in simp])
            cx = sum(p[0] for p in s.points)/len(s.points); cy = sum(p[1] for p in s.points)/len(s.points)
            feats.append(dict(id=d, rings=rings, c=tx((cx, cy))))
        npts = sum(len(rg) for f in feats for rg in f["rings"])
        (OUT/f"{key}_geo.json").write_text(json.dumps(dict(viewBox=[0, 0, 1000, round((ymax-ymin)*scale)], features=feats), separators=(",", ":")))
        print(key, len(feats), "districts", npts, "points", (OUT/f"{key}_geo.json").stat().st_size//1024, "KB")

if __name__ == "__main__":
    main()
