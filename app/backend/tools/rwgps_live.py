"""
Live RideWithGPS tools — ported from notebooks/lib/tools_rwgps_live.py.
"""
from __future__ import annotations

import json
import requests
from langchain.tools import tool
from db.secrets import get_secret

BASE_URL = "https://ridewithgps.com"


def _rwgps_get(path: str, params: dict | None = None) -> dict | list:
    resp = requests.get(f"{BASE_URL}{path}", params={**(params or {}), "auth_token": get_secret("rwgps", "auth_token")}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _difficulty(elev_m, dist_km) -> str:
    if not elev_m or not dist_km or dist_km == 0: return "unknown"
    g = elev_m / dist_km
    return "flat" if g < 5 else "rolling" if g < 15 else "hilly" if g < 30 else "mountainous"


@tool
def rwgps_get_recent_trips(count: int = 10) -> str:
    """
    Get the athlete's most recent RideWithGPS trips: name, date, distance,
    elevation, duration, and average speed.
    Use this to see outdoor rides logged in RWGPS or find route_ids.
    count: number of trips to return (default 10, max 25)
    """
    try:
        count = min(max(1, count), 25)
        user_id = get_secret("rwgps", "user_id")
        data = _rwgps_get(f"/users/{user_id}/trips.json", {"limit": count, "offset": 0})
        trips = data.get("results", []) if isinstance(data, dict) else (data or [])
        return json.dumps([{
            "trip_id": t.get("id"), "name": t.get("name"),
            "date": (t.get("departed_at") or t.get("created_at") or "")[:10],
            "distance_km": round((t.get("distance") or 0) / 1000, 1),
            "elevation_m": round(t.get("elevation_gain") or 0),
            "duration_min": round((t.get("duration") or 0) / 60, 1),
            "difficulty": _difficulty(round(t.get("elevation_gain") or 0), round((t.get("distance") or 0) / 1000, 1)),
        } for t in trips], indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def rwgps_search_routes(keyword: str = "", max_distance_km: float = 0, min_distance_km: float = 0) -> str:
    """
    Search the athlete's saved RideWithGPS routes by keyword and optionally
    filter by distance range. Returns route name, distance, elevation, and URL.
    Use this when the athlete asks for route suggestions or wants to see saved routes.
    keyword: search term (empty = return all); max/min_distance_km: filter by range
    """
    try:
        user_id = get_secret("rwgps", "user_id")
        data = _rwgps_get(f"/users/{user_id}/routes.json", {"offset": 0, "limit": 50})
        routes = data.get("results", []) if isinstance(data, dict) else (data or [])
        result = []
        for r in routes:
            dist_km = round((r.get("distance") or 0) / 1000, 1)
            elev_m = round(r.get("elevation_gain") or 0)
            name = r.get("name") or ""
            if keyword and keyword.lower() not in name.lower(): continue
            if max_distance_km > 0 and dist_km > max_distance_km: continue
            if min_distance_km > 0 and dist_km < min_distance_km: continue
            result.append({"route_id": r.get("id"), "name": name, "distance_km": dist_km, "elevation_m": elev_m, "difficulty": _difficulty(elev_m, dist_km), "url": f"https://ridewithgps.com/routes/{r.get('id')}"})
        return json.dumps({"total_matching": len(result), "routes": result}, indent=2, default=str) if result else json.dumps({"message": f"No routes matching '{keyword}'"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def rwgps_get_route(route_id: int) -> str:
    """
    Get full details for a specific RideWithGPS route: description, elevation
    profile, surface type, and difficulty. Use this after rwgps_search_routes
    to get details on a specific route before recommending it.
    """
    try:
        data = _rwgps_get(f"/routes/{route_id}.json")
        route = data.get("route", data) if isinstance(data, dict) else {}
        dist_km = round((route.get("distance") or 0) / 1000, 1)
        elev_m = round(route.get("elevation_gain") or 0)
        return json.dumps({
            "route_id": route.get("id"), "name": route.get("name"),
            "description": route.get("description"),
            "distance_km": dist_km, "elevation_gain_m": elev_m,
            "difficulty": _difficulty(elev_m, dist_km),
            "surface_type": route.get("surface_type"),
            "locality": route.get("locality"),
            "url": f"https://ridewithgps.com/routes/{route_id}",
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "route_id": route_id})


rwgps_live_tools = [rwgps_get_recent_trips, rwgps_search_routes, rwgps_get_route]
