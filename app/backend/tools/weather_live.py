"""
Live OpenWeatherMap tools — ported from notebooks/lib/tools_weather_live.py.
"""
from __future__ import annotations

import json
from collections import defaultdict
import requests
from langchain.tools import tool
from db.secrets import get_secret

BASE_URL = "https://api.openweathermap.org/data/2.5"


def _owm_get(endpoint: str, params: dict) -> dict:
    resp = requests.get(f"{BASE_URL}/{endpoint}", params={**params, "appid": get_secret("openweathermap", "api_key"), "units": "metric"}, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _wind_desc(speed_ms: float) -> str:
    kph = speed_ms * 3.6
    if kph < 10: return "calm"
    if kph < 20: return "light breeze"
    if kph < 35: return "moderate wind (noticeable)"
    if kph < 50: return "strong wind (hard riding)"
    return "very strong wind (consider indoor)"


def _verdict(temp_c, wind_ms, rain_mm, snow_mm) -> str:
    if snow_mm and snow_mm > 0: return "INDOOR — snow"
    if rain_mm and rain_mm > 2: return "INDOOR — significant rain"
    if wind_ms and wind_ms * 3.6 > 50: return "INDOOR — dangerous wind"
    if temp_c is not None and temp_c < 0: return "CAUTION — below freezing"
    if temp_c is not None and temp_c < 5: return "OUTDOOR OK — dress warmly"
    if temp_c is not None and temp_c > 35: return "CAUTION — very hot, reduce intensity"
    if rain_mm and rain_mm > 0.5: return "OUTDOOR OK — light rain"
    return "GOOD conditions for riding"


@tool
def weather_get_current(city: str) -> str:
    """
    Get current weather for a city: temperature, wind, humidity, precipitation,
    and a riding verdict (GOOD / CAUTION / INDOOR recommendation).
    Use this when the athlete asks about riding outside today or whether to go indoor.
    city: e.g. 'London' or 'London,GB'
    """
    try:
        data = _owm_get("weather", {"q": city})
        main, wind = data.get("main", {}), data.get("wind", {})
        rain, snow = data.get("rain", {}).get("1h", 0), data.get("snow", {}).get("1h", 0)
        temp, wind_ms = main.get("temp"), wind.get("speed")
        return json.dumps({
            "city": data.get("name"),
            "condition": (data.get("weather") or [{}])[0].get("description", "").title(),
            "temperature_c": round(temp, 1) if temp is not None else None,
            "feels_like_c": round(main.get("feels_like"), 1) if main.get("feels_like") else None,
            "humidity_pct": main.get("humidity"),
            "wind_speed_kph": round(wind_ms * 3.6, 1) if wind_ms else None,
            "wind_description": _wind_desc(wind_ms) if wind_ms else None,
            "rain_last_1hr_mm": rain, "snow_last_1hr_mm": snow,
            "riding_verdict": _verdict(temp, wind_ms, rain, snow),
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "city": city})


@tool
def weather_get_forecast(city: str) -> str:
    """
    Get a 5-day weather forecast for a city: daily high/low, conditions, wind,
    rain probability, and riding verdict per day.
    Use this when planning which days this week to ride outside.
    city: e.g. 'London' or 'New York,US'
    """
    try:
        data = _owm_get("forecast", {"q": city, "cnt": 40})
        days: dict = defaultdict(list)
        for item in data.get("list", []):
            days[item.get("dt_txt", "")[:10]].append(item)
        result = []
        for day, items in sorted(days.items())[:5]:
            temps = [i["main"]["temp"] for i in items if "main" in i]
            winds = [i["wind"]["speed"] for i in items if "wind" in i]
            rains = [i.get("rain", {}).get("3h", 0) for i in items]
            snows = [i.get("snow", {}).get("3h", 0) for i in items]
            max_wind = max(winds) if winds else 0
            result.append({
                "date": day,
                "temp_high_c": round(max(temps), 1) if temps else None,
                "temp_low_c": round(min(temps), 1) if temps else None,
                "conditions": max(set(c for i in items for c in [(i.get("weather") or [{}])[0].get("description", "")]), key=lambda x: x) if items else None,
                "max_wind_kph": round(max_wind * 3.6, 1),
                "total_rain_mm": round(sum(rains), 1),
                "precip_prob_pct": round(max((i.get("pop", 0) for i in items), default=0) * 100),
                "riding_verdict": _verdict(max(temps) if temps else None, max_wind, sum(rains), sum(snows)),
            })
        return json.dumps({"city": data.get("city", {}).get("name", city), "forecast": result}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "city": city})


@tool
def weather_get_best_riding_window(city: str) -> str:
    """
    Find the best 3-hour window to ride today based on temperature, wind, and rain.
    Use this when the athlete asks 'when should I ride today?'
    city: e.g. 'London'
    """
    try:
        data = _owm_get("forecast", {"q": city, "cnt": 8})
        slots = []
        for item in data.get("list", []):
            main, wind = item.get("main", {}), item.get("wind", {})
            rain = item.get("rain", {}).get("3h", 0)
            snow = item.get("snow", {}).get("3h", 0)
            temp, wind_ms = main.get("temp"), wind.get("speed", 0)
            pop = item.get("pop", 0)
            score = (30 if rain > 1 else 10 if rain > 0 else 0) + (50 if snow > 0 else 0) + (20 if wind_ms * 3.6 > 40 else 10 if wind_ms * 3.6 > 25 else 0) + (20 if temp is not None and temp < 2 else 0) + (15 if temp is not None and temp > 33 else 0) + pop * 20
            slots.append({"time": item.get("dt_txt"), "temp_c": round(temp, 1) if temp is not None else None, "wind_kph": round(wind_ms * 3.6, 1), "rain_mm": rain, "precip_prob_pct": round(pop * 100), "verdict": _verdict(temp, wind_ms, rain, snow), "score": score})
        best = min(slots, key=lambda x: x["score"]) if slots else None
        return json.dumps({"city": data.get("city", {}).get("name", city), "best_window": best, "all_slots": slots}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e), "city": city})


weather_live_tools = [weather_get_current, weather_get_forecast, weather_get_best_riding_window]
