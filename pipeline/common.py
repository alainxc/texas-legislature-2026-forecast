import math, pathlib, json, datetime, warnings
warnings.filterwarnings("ignore")
import yaml, pandas as pd, numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
PROC.mkdir(parents=True, exist_ok=True)

def load_config():
    return yaml.safe_load((ROOT / "config" / "model_config.yaml").read_text())

def today():
    return datetime.date.today()

# --- inverse Lambert Conformal Conic (TLC shapefile projection) ---
_A, _F = 6378137.0, 1/298.257222101
_E = math.sqrt(2*_F - _F*_F)
_P1, _P2, _P0, _LON0 = map(math.radians, (27.41666666666667, 34.91666666666666, 31.16666666666667, -100.0))
_FE, _FN = 1000000.0, 1000000.0
def _m(p): return math.cos(p)/math.sqrt(1-(_E*math.sin(p))**2)
def _t(p): return math.tan(math.pi/4-p/2)/((1-_E*math.sin(p))/(1+_E*math.sin(p)))**(_E/2)
_N = (math.log(_m(_P1))-math.log(_m(_P2)))/(math.log(_t(_P1))-math.log(_t(_P2)))
_FF = _m(_P1)/(_N*_t(_P1)**_N)
_R0 = _A*_FF*_t(_P0)**_N
def lcc_inverse(x, y):
    x -= _FE; y -= _FN
    r = math.copysign(math.hypot(x, _R0-y), _N)
    t = (r/(_A*_FF))**(1/_N)
    theta = math.atan2(x, _R0-y)
    lon = theta/_N + _LON0
    lat = math.pi/2 - 2*math.atan(t)
    for _ in range(6):
        lat = math.pi/2 - 2*math.atan(t*((1-_E*math.sin(lat))/(1+_E*math.sin(lat)))**(_E/2))
    return math.degrees(lat), math.degrees(lon)

def region_for(lat, lon):
    if lon < -103.0: return "El Paso / Far West"
    if lon < -100.3 and lat > 31.0: return "Panhandle / West"
    if 32.3 <= lat <= 33.5 and -97.7 <= lon <= -96.1: return "Dallas-Fort Worth"
    if 29.2 <= lat <= 30.4 and -96.1 <= lon <= -94.6: return "Houston"
    if 29.9 <= lat <= 31.0 and -98.3 <= lon <= -97.2: return "Austin / Central"
    if 29.0 <= lat <= 29.9 and -99.0 <= lon <= -98.0: return "San Antonio"
    if lat < 29.2 and lon > -101.0: return "South Texas / Border"
    if lon > -96.1 and lat > 30.4: return "East Texas"
    if lat <= 30.4 and lon > -97.2: return "Gulf Coast / Southeast"
    return "Central / Hill Country"

def district_key(chamber, d):
    return f"{'HD' if chamber=='H' else 'SD'}{int(d):03d}"
