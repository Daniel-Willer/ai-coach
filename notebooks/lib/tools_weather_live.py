# Databricks notebook source
# MAGIC %md
# MAGIC # lib/tools_weather_live — Live Weather Tools
# MAGIC
# MAGIC Pulls current conditions and forecast from OpenWeatherMap to inform
# MAGIC route selection, outdoor vs indoor decisions, and pacing advice.
# MAGIC
# MAGIC **Secret setup (one-time):**
# MAGIC   databricks secrets put --scope openweathermap --key api_key
# MAGIC
# MAGIC Get a free API key at openweathermap.org (free tier: 60 calls/min)
# MAGIC
# MAGIC %run'd by 06_coaching_agent.py — do not run standalone.

# COMMAND ----------

import json
import requests
from langchain.tools import tool

BASE_URL = "https://api.openweathermap.org/data/2.5"


def _owm_get(endpoint: str, params: dict) -> dict:
    api_key = dbutils.secrets.get(scope="openweathermap", key="api_key")
    resp = requests.get(
        f"{BASE_URL}/{endpoint}",
        params={**params, "appid": api_key, "units": "metric"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def _wind_description(speed_ms: float) -> str:
    kph = speed_ms * 3.6
    if kph < 10:   return "calm"
    if kph < 20:   return "light breeze (easy riding)"
    if kph < 35:   return "moderate wind (noticeable)"
    if kph < 50:   return "strong wind (hard riding)"
    return "very strong wind (consider indoor)"


def _riding_verdict(temp_c, wind_ms, rain_mm, snow_mm) -> str:
    if snow_mm and snow_mm > 0:
        return "INDOOR — snow on ground"
    if rain_mm and rain_mm > 2:
        return "INDOOR — significant rain"
    if wind_ms and wind_ms * 3.6 > 50:
        return "INDOOR — dangerously strong wind"
    if temp_c is not None and temp_c < 0:
        return "CAUTION — below freezing, ice risk"
    if temp_c is not None and temp_c < 5:
        return "OUTDOOR OK — dress warmly (full winter kit)"
    if temp_c is not None and temp_c > 35:
        return "CAUTION — very hot, hydrate aggressively and reduce intensity"
    if rain_mm and rain_mm > 0.5:
        return "OUTDOOR OK — light rain, use rain jacket"
    return "GOOD conditions for riding"


# ── Tools ────────────────────────────────────────────────────────────────────

@tool
def weather_get_current(city: str) -> str:
    """
    Get current weather conditions for a city: temperature, feels-like,
    wind speed and direction, humidity, precipitation, and a riding verdict
    (good/caution/indoor recommendation).
    Use this when the athlete asks about riding outside today, whether to
    do an outdoor or indoor session, or how to dress for a ride.
    city: city name e.g. 'London' or 'London,GB' for specificity
    """
    try:
        data = _owm_get("weather", {"q": city})
    except Exception as e:
        return json.dumps({"error": str(e), "city": city})

    main   = data.get("main", {})
    wind   = data.get("wind", {})
    rain   = data.get("rain", {})
    snow   = data.get("snow", {})
    clouds = data.get("clouds", {})
    desc   = (data.get("weather") or [{}])[0]

    temp    = main.get("temp")
    wind_ms = wind.get("speed")
    rain_1h = rain.get("1h", 0)
    snow_1h = snow.get("1h", 0)

    return json.dumps({
        "city":            data.get("name"),
        "condition":       desc.get("description", "").title(),
        "temperature_c":   round(temp, 1) if temp is not None else None,
        "feels_like_c":    round(main.get("feels_like"), 1) if main.get("feels_like") else None,
        "humidity_pct":    main.get("humidity"),
        "wind_speed_kph":  round(wind_ms * 3.6, 1) if wind_ms else None,
        "wind_gust_kph":   round(wind.get("gust", 0) * 3.6, 1) if wind.get("gust") else None,
        "wind_dir_deg":    wind.get("deg"),
        "wind_description": _wind_description(wind_ms) if wind_ms else None,
        "rain_last_1hr_mm": rain_1h,
        "snow_last_1hr_mm": snow_1h,
        "cloud_cover_pct": clouds.get("all"),
        "riding_verdict":  _riding_verdict(temp, wind_ms, rain_1h, snow_1h),
    }, indent=2)


@tool
def weather_get_forecast(city: str) -> str:
    """
    Get a 5-day weather forecast for a city, summarized by day: high/low temp,
    conditions, wind, rain probability, and daily riding verdict.
    Use this when planning which days this week to ride outside, or when the
    athlete asks 'when is the best day to ride this week?'
    city: city name e.g. 'London' or 'New York,US'
    """
    try:
        data = _owm_get("forecast", {"q": city, "cnt": 40})
    except Exception as e:
        return json.dumps({"error": str(e), "city": city})

    # Group 3-hour forecasts by day
    from collections import defaultdict
    days: dict = defaultdict(list)
    for item in data.get("list", []):
        day = item.get("dt_txt", "")[:10]
        days[day].append(item)

    result = []
    for day, items in sorted(days.items())[:5]:
        temps  = [i["main"]["temp"] for i in items if "main" in i]
        winds  = [i["wind"]["speed"] for i in items if "wind" in i]
        rains  = [i.get("rain", {}).get("3h", 0) for i in items]
        snows  = [i.get("snow", {}).get("3h", 0) for i in items]
        pops   = [i.get("pop", 0) for i in items]  # probability of precipitation
        conds  = [i["weather"][0]["description"] for i in items if i.get("weather")]

        max_wind = max(winds) if winds else 0
        total_rain = sum(rains)
        total_snow = sum(snows)
        max_pop    = max(pops) if pops else 0

        result.append({
            "date":             day,
            "temp_high_c":      round(max(temps), 1) if temps else None,
            "temp_low_c":       round(min(temps), 1) if temps else None,
            "conditions":       max(set(conds), key=conds.count) if conds else None,
            "max_wind_kph":     round(max_wind * 3.6, 1),
            "total_rain_mm":    round(total_rain, 1),
            "total_snow_mm":    round(total_snow, 1),
            "precip_prob_pct":  round(max_pop * 100),
            "riding_verdict":   _riding_verdict(
                max(temps) if temps else None,
                max_wind, total_rain, total_snow
            ),
        })

    return json.dumps({"city": data.get("city", {}).get("name", city), "forecast": result}, indent=2)


@tool
def weather_get_best_riding_window(city: str) -> str:
    """
    Find the best 2-3 hour window to ride today based on temperature, wind,
    and precipitation forecast. Returns the optimal time slot and conditions.
    Use this when the athlete asks 'when should I ride today?' or wants to
    plan around the weather.
    city: city name e.g. 'London'
    """
    try:
        data = _owm_get("forecast", {"q": city, "cnt": 8})  # next 24hrs (8 x 3hr slots)
    except Exception as e:
        return json.dumps({"error": str(e), "city": city})

    slots = []
    for item in data.get("list", []):
        time_str = item.get("dt_txt", "")
        main     = item.get("main", {})
        wind     = item.get("wind", {})
        rain     = item.get("rain", {}).get("3h", 0)
        snow     = item.get("snow", {}).get("3h", 0)
        pop      = item.get("pop", 0)
        temp     = main.get("temp")
        wind_ms  = wind.get("speed", 0)

        # Score: lower = better
        score = 0
        if rain > 1: score += 30
        if rain > 0: score += 10
        if snow > 0: score += 50
        if wind_ms * 3.6 > 40: score += 20
        if wind_ms * 3.6 > 25: score += 10
        if temp is not None and temp < 2: score += 20
        if temp is not None and temp > 33: score += 15
        score += pop * 20

        slots.append({
            "time":          time_str,
            "temp_c":        round(temp, 1) if temp is not None else None,
            "wind_kph":      round(wind_ms * 3.6, 1),
            "rain_mm":       rain,
            "precip_prob":   round(pop * 100),
            "condition":     (item.get("weather") or [{}])[0].get("description", "").title(),
            "score":         score,
            "verdict":       _riding_verdict(temp, wind_ms, rain, snow),
        })

    best = min(slots, key=lambda x: x["score"]) if slots else None

    return json.dumps({
        "city":         data.get("city", {}).get("name", city),
        "best_window":  best,
        "all_slots":    slots,
        "note":         "Lower score = better riding conditions. Slots are 3-hour windows.",
    }, indent=2)


# Exported list
weather_live_tools = [
    weather_get_current,
    weather_get_forecast,
    weather_get_best_riding_window,
]

print(f"  lib/tools_weather_live loaded: {len(weather_live_tools)} tools")
