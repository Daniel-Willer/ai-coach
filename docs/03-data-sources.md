# Your Data Sources

The coach gets smarter the more data it has. This page explains what each source provides, why it matters for coaching, and how the data flows through the system.

---

## How data flows

```
Source API  →  Bronze table   →  Silver table  →  Gold table  →  Coach
(raw JSON)     (as received)     (cleaned)         (computed)     (answers)
```

- **Bronze** — raw data exactly as the API returns it, stored as-is
- **Silver** — cleaned, unified, column names standardized across sources
- **Gold** — computed metrics: CTL, ATL, TSB, power zones, power curves
- **Features** — a daily snapshot table the coach uses to answer questions

---

## Strava

**What it provides:**
- Every ride you've ever logged (indoor and outdoor)
- Power data (if you have a power meter or smart trainer)
- Heart rate data (if you have an HR monitor)
- GPS route, distance, elevation
- Cadence, speed, calories
- Segment efforts and PRs

**Why it matters:**
Strava is the primary source for ride activity data. Without it, the coach has no rides to analyze. If you have a power meter, this is the single most important data source — power data unlocks accurate TSS calculation, zone analysis, and power curve tracking.

**What the coach can do with Strava data:**
- Analyze any specific ride (zones, HR drift, intensity factor)
- Calculate TSS for each ride to feed into training load
- Track your power curve (best 5s, 1min, 5min, 20min power)
- Detect training imbalances in zone distribution

**Live vs pipeline:**
The coach can pull fresh Strava data in real time (rides from today that haven't been processed yet) using the `strava_get_recent_activities` tool. Historical analysis uses the processed Delta tables.

**If you don't have a power meter:**
The coach works from heart rate and estimated effort, but accuracy is lower. TSS estimation relies on HR-based methods which are less precise. Getting a power meter — even a single-sided one — is the single best upgrade for data quality.

---

## Garmin Connect

**What it provides:**
- Sleep: duration, stages (deep/light/REM), overnight HRV, sleep score
- Body battery (0-100 readiness score)
- Resting heart rate
- Daily stress score
- Step count and activity tracking
- HRV status and baseline tracking

**Why it matters:**
Garmin data is what separates a generic training app from a real coach. Knowing that your TSB says you're "fresh" is one thing — but if your HRV dropped 20ms from baseline and your body battery is 30, you're not actually fresh, you're fighting something off. The coach uses these signals to override what the numbers say.

**What the coach can do with Garmin data:**
- Check if recovery signals support hard training before prescribing intensity
- Identify nights of poor sleep that may affect performance
- Track HRV trends to spot overtraining before CTL signals it
- Give body battery context ("you're at 42, moderate training only")

**HRV explained simply:**
Heart Rate Variability is the tiny variation in time between heartbeats. Higher and more stable HRV generally means your nervous system is recovered and ready. Lower-than-baseline HRV usually means stress — physical or mental. Garmin tracks this overnight while you sleep.

**Body battery explained:**
Garmin's composite score combining sleep quality, overnight HRV, daytime stress, and activity. Think of it as a phone battery — it charges while you sleep and drains during your day. A reading above 75 in the morning means you're well recovered. Below 30 and you need rest.

---

## RideWithGPS

**What it provides:**
- Your saved routes with elevation profiles and distance
- Recorded trip history with GPS tracks
- Route details: surface type, terrain, locality

**Why it matters:**
RideWithGPS is the coach's route library. When you ask "suggest a route for a 90-minute hilly ride today", the coach searches your saved routes for matches rather than giving generic advice.

**What the coach can do with RideWithGPS data:**
- Suggest specific routes that match your target duration and elevation preference
- Pull elevation profiles to estimate ride difficulty
- Track your performance on repeated routes over time

**Getting the most out of it:**
Save your regular routes in RideWithGPS. The more routes you have saved, the better the route suggestions. Name them descriptively ("Tuesday Hills Loop", "Flat Riverside Recovery").

---

## Intervals.icu

**What it provides:**
- Training load (CTL/ATL/TSB) computed independently from your Delta pipeline
- Activities aggregated from Strava, Garmin, Wahoo, and other platforms
- Wellness tracking: HRV, sleep, weight, mood, fatigue ratings
- Best power curve across all time and recent periods
- VO2max estimate
- Structured workout library

**Why it matters:**
Intervals.icu is a free platform that does excellent training science. It serves as both a cross-check on the pipeline's calculations and an additional source for wellness data you may enter manually (mood, subjective fatigue, weight).

**What the coach can do with Intervals.icu data:**
- Cross-check CTL/ATL/TSB against a second source
- Pull the best available power curve
- Access wellness data you may track in Intervals but not Garmin
- Get VO2max estimates

**Setting up Intervals.icu:**
1. Go to [intervals.icu](https://intervals.icu) and create a free account
2. Connect your Strava account so it automatically imports rides
3. Optionally connect Garmin for wellness data sync
4. Find your API key in Settings (scroll to bottom)
5. Your athlete ID is in your profile URL: `intervals.icu/athletes/iXXXXXX`

---

## OpenWeatherMap

**What it provides:**
- Current weather conditions for any city
- 5-day forecast with 3-hour resolution
- Temperature, wind speed and direction, precipitation, humidity

**Why it matters:**
Riding decisions are weather decisions. The coach can factor wind, rain, and temperature into ride planning — recommending an indoor session when conditions are genuinely bad, or finding the best window in a day with mixed weather.

**What the coach can do with weather data:**
- Give a riding verdict (GOOD / CAUTION / INDOOR) for current conditions
- Find the best 3-hour window to ride today
- Help plan which days this week are best for outdoor riding
- Factor wind when suggesting effort levels ("headwind on the way back, start easier")

**Getting a free API key:**
1. Go to [openweathermap.org](https://openweathermap.org)
2. Create a free account
3. Go to API keys — your default key is there immediately
4. Free tier: 60 calls/minute, plenty for this use case

**When asking about weather:**
Include your city name in the question: *"What's the weather like in London today — should I ride outside?"*

---

## Data source priority

When the coach has multiple sources for the same data, it uses this priority:

| Data type | Primary source | Fallback |
|-----------|---------------|---------|
| Ride activity | Strava (processed) | Strava (live API) |
| Training load (CTL/ATL) | Gold Delta tables | Intervals.icu live |
| Sleep | Garmin | Intervals.icu wellness |
| HRV | Garmin | Intervals.icu wellness |
| Body battery | Garmin only | — |
| Power curve | Gold Delta tables | Intervals.icu live |
| Routes | RideWithGPS | Silver.routes table |
| Weather | OpenWeatherMap | — |

---

## Missing data

If a data source isn't connected, the coach handles it gracefully — it just won't be able to answer questions that require that data.

Common situations:
- **No power meter** → TSS uses HR-based estimation, zone analysis is heart-rate based
- **No Garmin** → Coach can't check sleep/HRV, relies on CTL/ATL only for recovery
- **No RideWithGPS** → Route suggestions pull from whatever routes are in the activities table
- **No Intervals.icu** → Coach uses only the Delta pipeline's training load calculations
- **No weather** → Coach skips weather-based advice, focuses on training data only
