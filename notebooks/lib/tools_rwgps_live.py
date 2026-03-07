# Databricks notebook source
# MAGIC %md
# MAGIC # lib/tools_rwgps_live — Live RideWithGPS Tools
# MAGIC
# MAGIC Pulls routes and recent trips from RideWithGPS for route planning.
# MAGIC Feeds real route data into the agent's suggest_route recommendations.
# MAGIC
# MAGIC **Secret setup (one-time):**
# MAGIC   databricks secrets put --scope rwgps --key auth_token
# MAGIC   databricks secrets put --scope rwgps --key user_id
# MAGIC
# MAGIC Get your auth_token: ridewithgps.com → Account → API access
# MAGIC Get your user_id from your profile URL: ridewithgps.com/users/XXXXXX
# MAGIC
# MAGIC %run'd by 06_coaching_agent.py — do not run standalone.

# COMMAND ----------

import json
import requests
from langchain.tools import tool

BASE_URL = "https://ridewithgps.com"


def _rwgps_get(path: str, params: dict | None = None) -> dict | list:
    auth_token = dbutils.secrets.get(scope="rwgps", key="auth_token")
    resp = requests.get(
        f"{BASE_URL}{path}",
        params={**(params or {}), "auth_token": auth_token},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _difficulty(elevation_m: float | None, distance_km: float | None) -> str:
    if not elevation_m or not distance_km or distance_km == 0:
        return "unknown"
    gain_per_km = elevation_m / distance_km
    if gain_per_km < 5:    return "flat"
    if gain_per_km < 15:   return "rolling"
    if gain_per_km < 30:   return "hilly"
    return "mountainous"


# ── Tools ────────────────────────────────────────────────────────────────────

@tool
def rwgps_get_recent_trips(count: int = 10) -> str:
    """
    Get the athlete's most recent RideWithGPS trips (recorded rides with GPS):
    name, date, distance, elevation, duration, and average speed.
    Use this to see outdoor rides logged in RWGPS, check recent route history,
    or find route_ids for detailed route lookups.
    count: number of trips to return (default 10, max 25)
    """
    count = min(max(1, count), 25)
    try:
        user_id = dbutils.secrets.get(scope="rwgps", key="user_id")
        data = _rwgps_get(f"/users/{user_id}/trips.json", {"limit": count, "offset": 0})
    except Exception as e:
        return json.dumps({"error": str(e)})

    trips = data.get("results", []) if isinstance(data, dict) else data
    result = []
    for t in trips:
        dist_km = round((t.get("distance") or 0) / 1000, 1)
        elev_m  = round(t.get("elevation_gain") or 0)
        result.append({
            "trip_id":      t.get("id"),
            "name":         t.get("name"),
            "date":         (t.get("departed_at") or t.get("created_at") or "")[:10],
            "distance_km":  dist_km,
            "elevation_m":  elev_m,
            "duration_min": round((t.get("duration") or 0) / 60, 1),
            "avg_speed_kph": round(t.get("avg_speed") or 0, 1),
            "difficulty":   _difficulty(elev_m, dist_km),
        })

    return json.dumps(result, indent=2, default=str)


@tool
def rwgps_search_routes(keyword: str = "", max_distance_km: float = 0, min_distance_km: float = 0) -> str:
    """
    Search the athlete's saved RideWithGPS routes by keyword, optionally filtered
    by distance range. Returns route name, distance, elevation, difficulty, and
    a shareable URL. Use this when the athlete asks for route suggestions or
    wants to know what saved routes are available.
    keyword: search term (empty = return all saved routes)
    max_distance_km: filter routes shorter than this (0 = no limit)
    min_distance_km: filter routes longer than this (0 = no limit)
    """
    try:
        user_id = dbutils.secrets.get(scope="rwgps", key="user_id")
        data = _rwgps_get(
            f"/users/{user_id}/routes.json",
            {"offset": 0, "limit": 50}
        )
    except Exception as e:
        return json.dumps({"error": str(e)})

    routes = data.get("results", []) if isinstance(data, dict) else (data or [])

    result = []
    for r in routes:
        dist_km = round((r.get("distance") or 0) / 1000, 1)
        elev_m  = round(r.get("elevation_gain") or 0)
        name    = r.get("name") or ""

        # Filter by keyword
        if keyword and keyword.lower() not in name.lower():
            continue

        # Filter by distance
        if max_distance_km > 0 and dist_km > max_distance_km:
            continue
        if min_distance_km > 0 and dist_km < min_distance_km:
            continue

        result.append({
            "route_id":    r.get("id"),
            "name":        name,
            "distance_km": dist_km,
            "elevation_m": elev_m,
            "difficulty":  _difficulty(elev_m, dist_km),
            "url":         f"https://ridewithgps.com/routes/{r.get('id')}",
            "created_at":  (r.get("created_at") or "")[:10],
        })

    if not result:
        return json.dumps({
            "message": f"No routes found matching keyword='{keyword}', distance={min_distance_km}-{max_distance_km}km",
            "total_routes_checked": len(routes),
        })

    return json.dumps({
        "total_matching": len(result),
        "routes": result,
    }, indent=2, default=str)


@tool
def rwgps_get_route(route_id: int) -> str:
    """
    Get full details for a specific RideWithGPS route: description, elevation
    profile summary (total gain/loss, max grade, steepest segment), surface type,
    and difficulty rating. Use this after rwgps_search_routes to get details
    on a specific route before recommending it to the athlete.
    """
    try:
        data = _rwgps_get(f"/routes/{route_id}.json")
    except Exception as e:
        return json.dumps({"error": str(e), "route_id": route_id})

    route = data.get("route", data) if isinstance(data, dict) else {}

    dist_km = round((route.get("distance") or 0) / 1000, 1)
    elev_m  = round(route.get("elevation_gain") or 0)

    # Track points for elevation profile summary if available
    track = route.get("track_points") or []
    max_grade = None
    if track:
        grades = []
        for i in range(1, len(track)):
            dx = track[i].get("d", 0) - track[i-1].get("d", 0)
            dy = (track[i].get("e") or 0) - (track[i-1].get("e") or 0)
            if dx > 0:
                grades.append((dy / dx) * 100)
        if grades:
            max_grade = round(max(g for g in grades if g > 0), 1) if any(g > 0 for g in grades) else 0

    return json.dumps({
        "route_id":          route.get("id"),
        "name":              route.get("name"),
        "description":       route.get("description"),
        "distance_km":       dist_km,
        "elevation_gain_m":  elev_m,
        "elevation_loss_m":  round(route.get("elevation_loss") or 0),
        "max_grade_pct":     max_grade,
        "difficulty":        _difficulty(elev_m, dist_km),
        "surface_type":      route.get("surface_type"),
        "terrain_type":      route.get("terrain_type"),
        "locality":          route.get("locality"),
        "url":               f"https://ridewithgps.com/routes/{route_id}",
    }, indent=2, default=str)


# Exported list
rwgps_live_tools = [
    rwgps_get_recent_trips,
    rwgps_search_routes,
    rwgps_get_route,
]

print(f"  lib/tools_rwgps_live loaded: {len(rwgps_live_tools)} tools")
