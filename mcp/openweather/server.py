"""
OpenWeatherMap MCP Server
-------------------------
Current conditions, 5-day forecast, and best riding window.

Setup:
  cd mcp/openweather
  pip install -r requirements.txt
  cp .env.example .env
  python server.py

Free API key: openweathermap.org (60 calls/min on free tier)
"""

import json
import os
from collections import defaultdict
from pathlib import Path

import requests
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(Path(__file__).parent / ".env")

mcp = FastMCP("weather-coach")

BASE = "https://api.openweathermap.org/data/2.5"


def _get(endpoint: str, params: dict) -> dict:
    resp = requests.get(
        f"{BASE}/{endpoint}",
        params={**params, "appid": os.environ["OPENWEATHER_API_KEY"], "units": "metric"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _verdict(temp, wind_ms, rain_mm, snow_mm) -> str:
    if snow_mm and snow_mm > 0:   return "INDOOR — snow"
    if rain_mm and rain_mm > 2:   return "INDOOR — heavy rain"
    if wind_ms and wind_ms * 3.6 > 50: return "INDOOR — dangerous wind"
    if temp is not None and temp < 0:  return "CAUTION — below freezing"
    if temp is not None and temp < 5:  return "OUTDOOR OK — full winter kit"
    if temp is not None and temp > 35: return "CAUTION — extreme heat"
    if rain_mm and rain_mm > 0.5: return "OUTDOOR OK — light rain"
    return "GOOD conditions"


@mcp.tool()
def weather_get_current(city: str) -> str:
    """
    Get current weather for a city: temperature, feels-like, wind, rain,
    humidity, and a riding verdict. Use 'City,CountryCode' for precision
    (e.g. 'London,GB').
    """
    try:
        d = _get("weather", {"q": city})
    except Exception as e:
        return json.dumps({"error": str(e)})

    main, wind = d.get("main", {}), d.get("wind", {})
    rain = d.get("rain", {}).get("1h", 0)
    snow = d.get("snow", {}).get("1h", 0)
    temp = main.get("temp")
    ws   = wind.get("speed")

    return json.dumps({
        "city":          d.get("name"),
        "condition":     (d.get("weather") or [{}])[0].get("description", "").title(),
        "temp_c":        round(temp, 1) if temp is not None else None,
        "feels_like_c":  round(main.get("feels_like"), 1) if main.get("feels_like") else None,
        "humidity_pct":  main.get("humidity"),
        "wind_kph":      round(ws * 3.6, 1) if ws else None,
        "gust_kph":      round(wind.get("gust", 0) * 3.6, 1) if wind.get("gust") else None,
        "rain_1hr_mm":   rain,
        "snow_1hr_mm":   snow,
        "riding_verdict": _verdict(temp, ws, rain, snow),
    }, indent=2)


@mcp.tool()
def weather_get_forecast(city: str) -> str:
    """
    Get a 5-day weather forecast by day: high/low temp, conditions, max wind,
    total rain, precip probability, and riding verdict per day.
    """
    try:
        d = _get("forecast", {"q": city, "cnt": 40})
    except Exception as e:
        return json.dumps({"error": str(e)})

    days: dict = defaultdict(list)
    for item in d.get("list", []):
        days[item.get("dt_txt", "")[:10]].append(item)

    result = []
    for day, items in sorted(days.items())[:5]:
        temps = [i["main"]["temp"] for i in items if "main" in i]
        winds = [i["wind"]["speed"] for i in items if "wind" in i]
        rain  = sum(i.get("rain", {}).get("3h", 0) for i in items)
        snow  = sum(i.get("snow", {}).get("3h", 0) for i in items)
        pop   = max(i.get("pop", 0) for i in items)
        conds = [i["weather"][0]["description"] for i in items if i.get("weather")]

        mw = max(winds) if winds else 0
        result.append({
            "date":            day,
            "high_c":          round(max(temps), 1) if temps else None,
            "low_c":           round(min(temps), 1) if temps else None,
            "condition":       max(set(conds), key=conds.count) if conds else None,
            "max_wind_kph":    round(mw * 3.6, 1),
            "rain_mm":         round(rain, 1),
            "precip_prob_pct": round(pop * 100),
            "riding_verdict":  _verdict(max(temps) if temps else None, mw, rain, snow),
        })

    return json.dumps({"city": d.get("city", {}).get("name", city), "forecast": result}, indent=2)


@mcp.tool()
def weather_get_best_riding_window(city: str) -> str:
    """
    Find the best 3-hour window to ride today based on conditions.
    Returns the optimal time slot with temperature, wind, and rain.
    """
    try:
        d = _get("forecast", {"q": city, "cnt": 8})
    except Exception as e:
        return json.dumps({"error": str(e)})

    slots = []
    for item in d.get("list", []):
        temp   = (item.get("main") or {}).get("temp")
        ws     = (item.get("wind") or {}).get("speed", 0)
        rain   = item.get("rain", {}).get("3h", 0)
        snow   = item.get("snow", {}).get("3h", 0)
        pop    = item.get("pop", 0)
        score  = rain * 15 + snow * 50 + max(0, ws * 3.6 - 25) * 0.5 + pop * 20
        if temp is not None and temp < 2:  score += 20
        if temp is not None and temp > 33: score += 15
        slots.append({
            "time":    item.get("dt_txt", "")[:16],
            "temp_c":  round(temp, 1) if temp is not None else None,
            "wind_kph": round(ws * 3.6, 1),
            "rain_mm": rain,
            "precip_prob_pct": round(pop * 100),
            "condition": (item.get("weather") or [{}])[0].get("description", "").title(),
            "score":   round(score, 1),
            "verdict": _verdict(temp, ws, rain, snow),
        })

    best = min(slots, key=lambda x: x["score"]) if slots else None
    return json.dumps({"city": d.get("city", {}).get("name", city),
                       "best_window": best, "all_slots": slots}, indent=2)


if __name__ == "__main__":
    if not os.environ.get("OPENWEATHER_API_KEY"):
        raise RuntimeError("Missing OPENWEATHER_API_KEY. Copy .env.example to .env.")
    mcp.run()
