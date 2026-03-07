# AI Cycling Coach

A personal AI coaching system built on Databricks that connects your training data from Strava, Garmin, RideWithGPS, and Intervals.icu — then lets you have real conversations with a coach that actually knows your numbers.

> **New here?** Start with [Getting Started](docs/01-getting-started.md).

---

## What it does

- Pulls all your ride data, sleep, HRV, and recovery metrics into one place
- Calculates your fitness (CTL), fatigue (ATL), and form (TSB) daily
- Lets you chat with an AI coach that answers questions grounded in your actual data
- Prescribes specific workouts based on your current form, goals, and time available
- Detects training imbalances, power curve trends, and recovery warning signs

**Example questions you can ask:**
- *"How am I doing? Give me a full overview."*
- *"How did my last ride go? Give me real feedback."*
- *"What should I do today given my current form?"*
- *"Am I training in the right zones or is something off?"*
- *"Should I ride outside today or is the weather bad?"*
- *"Generate a training plan for this week."*

---

## Documentation

| Guide | What it covers |
|-------|---------------|
| [Getting Started](docs/01-getting-started.md) | What this is, how it works, what you'll need |
| [Setup Guide](docs/02-setup.md) | Step-by-step first-time setup (accounts, secrets, notebooks) |
| [Your Data Sources](docs/03-data-sources.md) | Connecting Strava, Garmin, RideWithGPS, Intervals.icu, weather |
| [Running the Pipeline](docs/04-running-the-pipeline.md) | Keeping your data fresh, notebook execution order |
| [Talking to Your Coach](docs/05-talking-to-your-coach.md) | How to ask questions, example conversations, what the coach can do |
| [Training Concepts](docs/06-training-concepts.md) | FTP, CTL/ATL/TSB, power zones, TSS explained simply |
| [Troubleshooting](docs/07-troubleshooting.md) | Common errors and how to fix them |

---

## Quick reference — notebook order

```
00_setup_catalog.py       ← run once to create tables
00b_garmin_bronze_v2.py   ← run to import Garmin data
01_strava_bronze.py       ← run to import Strava data
02_bronze_to_silver.py    ← cleans and unifies all activity data
03_silver_to_gold.py      ← calculates CTL/ATL/TSB, zones, power curves
04_feature_refresh.py     ← builds the AI's feature table
05_athlete_setup.py       ← run once (or when you update your profile)
06_coaching_agent.py      ← talk to your coach here
07_training_planner.py    ← generate and save a multi-week training plan
08_eval_harness.py        ← test suite for evaluating coach quality
```

---

## Data sources

| Source | What it provides | Required |
|--------|-----------------|----------|
| Strava | All ride activity data, power, HR, GPS | Yes |
| Garmin Connect | Sleep, HRV, body battery, resting HR, stress | Recommended |
| RideWithGPS | Saved routes, elevation profiles, trip history | Optional |
| Intervals.icu | Cross-platform training load, wellness data | Optional |
| OpenWeatherMap | Current conditions and forecast for route planning | Optional |
