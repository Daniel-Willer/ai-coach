"""
RideWithGPS MCP Server
----------------------
Route search, trip history, and elevation profiles from RideWithGPS.

Setup:
  cd mcp/rwgps
  pip install -r requirements.txt
  cp .env.example .env
  python server.py

Get auth_token: ridewithgps.com → Account → API access
Get user_id from your profile URL: ridewithgps.com/users/XXXXXX
"""

import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(Path(__file__).parent / ".env")

mcp = FastMCP("rwgps-coach")

BASE = "https://ridewithgps.com"


def _get(path: str, params: dict | None = None) -> dict | list:
    resp = requests.get(
        f"{BASE}{path}",
        params={**(params or {}), "auth_token": os.environ["RWGPS_AUTH_TOKEN"]},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _difficulty(elev_m, dist_km) -> str:
    if not elev_m or not dist_km or dist_km == 0: return "unknown"
    g = elev_m / dist_km
    return "flat" if g < 5 else "rolling" if g < 15 else "hilly" if g < 30 else "mountainous"


@mcp.tool()
def rwgps_get_recent_trips(count: int = 10) -> str:
    """
    Get recent RideWithGPS trips: name, date, distance, elevation, duration,
    and difficulty. count: 1-25, default 10.
    """
    count = min(max(1, count), 25)
    try:
        user_id = os.environ["RWGPS_USER_ID"]
        data = _get(f"/users/{user_id}/trips.json", {"limit": count})
    except Exception as e:
        return json.dumps({"error": str(e)})

    trips = data.get("results", []) if isinstance(data, dict) else data
    result = []
    for t in trips:
        dk = round((t.get("distance") or 0) / 1000, 1)
        em = round(t.get("elevation_gain") or 0)
        result.append({
            "trip_id":      t.get("id"),
            "name":         t.get("name"),
            "date":         (t.get("departed_at") or "")[:10],
            "distance_km":  dk,
            "elevation_m":  em,
            "duration_min": round((t.get("duration") or 0) / 60, 1),
            "difficulty":   _difficulty(em, dk),
        })
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def rwgps_search_routes(keyword: str = "", max_distance_km: float = 0,
                         min_distance_km: float = 0) -> str:
    """
    Search saved RideWithGPS routes by keyword and/or distance range.
    Returns name, distance, elevation, difficulty, and URL.
    keyword: search term (empty = all routes)
    max_distance_km / min_distance_km: distance filters (0 = no limit)
    """
    try:
        user_id = os.environ["RWGPS_USER_ID"]
        data = _get(f"/users/{user_id}/routes.json", {"limit": 50})
    except Exception as e:
        return json.dumps({"error": str(e)})

    routes = data.get("results", []) if isinstance(data, dict) else (data or [])
    result = []
    for r in routes:
        dk = round((r.get("distance") or 0) / 1000, 1)
        em = round(r.get("elevation_gain") or 0)
        name = r.get("name") or ""
        if keyword and keyword.lower() not in name.lower(): continue
        if max_distance_km > 0 and dk > max_distance_km: continue
        if min_distance_km > 0 and dk < min_distance_km: continue
        result.append({
            "route_id":    r.get("id"),
            "name":        name,
            "distance_km": dk,
            "elevation_m": em,
            "difficulty":  _difficulty(em, dk),
            "url":         f"https://ridewithgps.com/routes/{r.get('id')}",
        })

    return json.dumps({"total": len(result), "routes": result}, indent=2, default=str)


@mcp.tool()
def rwgps_get_route(route_id: int) -> str:
    """
    Get full details for a RideWithGPS route: description, elevation profile
    summary, surface type, terrain, and locality.
    """
    try:
        data = _get(f"/routes/{route_id}.json")
    except Exception as e:
        return json.dumps({"error": str(e)})

    r = data.get("route", data) if isinstance(data, dict) else {}
    dk = round((r.get("distance") or 0) / 1000, 1)
    em = round(r.get("elevation_gain") or 0)

    return json.dumps({
        "route_id":         r.get("id"),
        "name":             r.get("name"),
        "description":      r.get("description"),
        "distance_km":      dk,
        "elevation_gain_m": em,
        "elevation_loss_m": round(r.get("elevation_loss") or 0),
        "difficulty":       _difficulty(em, dk),
        "surface_type":     r.get("surface_type"),
        "terrain_type":     r.get("terrain_type"),
        "locality":         r.get("locality"),
        "url":              f"https://ridewithgps.com/routes/{route_id}",
    }, indent=2, default=str)


if __name__ == "__main__":
    missing = [k for k in ("RWGPS_AUTH_TOKEN", "RWGPS_USER_ID") if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing env vars: {missing}. Copy .env.example to .env.")
    mcp.run()
