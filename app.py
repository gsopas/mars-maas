import time
from typing import Dict, Any
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

MAAS_BASE = "https://api.maas2.apollorion.com"  # latest: "/", specific sol: "/{sol}"

app = FastAPI(title="Curiosity MAAS Weather API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# Tiny in-memory cache to avoid hammering MAAS
CACHE: Dict[str, Dict[str, Any]] = {}
TTL = 15 * 60  # 15 minutes

def _get_cached(key: str):
    row = CACHE.get(key)
    if not row: return None
    if time.time() - row["t"] > TTL:
        CACHE.pop(key, None)
        return None
    return row["v"]

def _set_cached(key: str, value: Any):
    CACHE[key] = {"t": time.time(), "v": value}

def _fetch_maas(path: str):
    url = f"{MAAS_BASE}{path}"
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Upstream MAAS error: {e}")

def _normalize_maas(d: dict) -> dict:
    # MAAS fields: sol, terrestrial_date, min_temp, max_temp, pressure, season, sunrise, sunset, etc.
    # Values are strings; keep them but expose a few convenience casts.
    def to_float(x):
        try:
            return float(x)
        except Exception:
            return None

    return {
        "source": "curiosity_rems_maas",
        "sol": d.get("sol"),
        "earth_date": d.get("terrestrial_date"),  # YYYY-MM-DD
        "season": d.get("season"),
        "temperature_c": {
            "min": to_float(d.get("min_temp")),
            "max": to_float(d.get("max_temp")),
            "min_gts": to_float(d.get("min_gts_temp")),
            "max_gts": to_float(d.get("max_gts_temp")),
        },
        "pressure_pa": to_float(d.get("pressure")),
        "pressure_qual": d.get("pressure_string"),
        "sunrise_local": d.get("sunrise"),
        "sunset_local": d.get("sunset"),
        "uv_index": d.get("local_uv_irradiance_index"),
        "atmo_opacity": d.get("atmo_opacity")
    }

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/weather/latest")
def weather_latest():
    key = "latest"
    cached = _get_cached(key)
    if cached: return cached
    data = _fetch_maas("/")
    out = _normalize_maas(data)
    _set_cached(key, out)
    return out

@app.get("/weather/{sol}")
def weather_by_sol(sol: int):
    key = f"sol:{sol}"
    cached = _get_cached(key)
    if cached: return cached
    data = _fetch_maas(f"/{sol}")
    if not data or (isinstance(data, dict) and data.get("error")):
        raise HTTPException(status_code=404, detail=f"No data for sol {sol}")
    out = _normalize_maas(data)
    _set_cached(key, out)
    return out

