# AI Cycling Coach — Master Architecture Plan

A world-class AI coaching system built on Databricks Lakehouse, delivering personalized training plans,
real-time coaching, performance analytics, and route intelligence for cyclists.

---

## Vision

A self-coaching AI system that rivals having a personal human coach — one who knows every ride you've
ever done, monitors your recovery, watches the weather, builds your training plan around your race
calendar, and rides alongside you with real-time guidance.

Not a generic plan generator. A living, adaptive coaching relationship backed by data.

---

## What's Already Built

| Notebook | Status | What It Does |
|---|---|---|
| `Garmin Data Ingest.ipynb` | Done | Pulls activities, daily summaries, activity details from Garmin API into Unity Catalog |
| `Strava Data Ingest.ipynb` | Done | Pulls activity streams, activity details, athlete profile from Strava API |
| `RideWithGPS Data Ingest.ipynb` | Done | Pulls routes, trips, route details from RideWithGPS API |
| `create delta tables.ipynb` | Done | Creates Delta schemas (athletes, rides, weather, routes) in `main.cycling` |

**Existing Unity Catalog tables** (in `main` catalog, source-specific schemas):
- `garmin.activities`, `garmin.daily_summaries`, `garmin.activity_details`
- `strava.activity_streams`, `strava.activity_details`, `strava.athlete`
- `ridewithgps.routes`, `ridewithgps.trips`, `ridewithgps.route_details`
- `cycling.athletes`, `cycling.rides`, `cycling.weather`, `cycling.routes` (scaffold)

---

## Target Catalog Structure (Unity Catalog)

```
ai_coach (catalog)
  bronze/       — raw API payloads, exactly as received
  silver/       — normalized, unified, cleaned
  gold/         — aggregated coaching metrics
  features/     — feature store for AI agents
  coach/        — coaching state: plans, goals, feedback, conversations
```

---

## Medallion Architecture

### Bronze (Raw Ingestion)
Extend existing ETL notebooks to write raw payloads into `ai_coach.bronze`:

| Table | Source | Key Fields |
|---|---|---|
| `bronze.garmin_activities_raw` | Garmin API | JSON blob, ingested_at |
| `bronze.garmin_daily_raw` | Garmin API | JSON blob, ingested_at |
| `bronze.strava_activities_raw` | Strava API | JSON blob, ingested_at |
| `bronze.strava_streams_raw` | Strava API | activity_id, JSON blob |
| `bronze.ridewithgps_routes_raw` | RWGPS API | JSON blob, ingested_at |
| `bronze.ridewithgps_trips_raw` | RWGPS API | JSON blob, ingested_at |
| `bronze.weather_raw` | OpenWeatherMap | lat, lon, timestamp, JSON blob |
| `bronze.fit_files_raw` | .fit upload | binary or parsed JSON, source_file |

### Silver (Normalized & Unified)

One canonical schema regardless of data source.

**`silver.activities`**
```
activity_id       STRING  (source_system + source_id, e.g. "strava_12345")
athlete_id        STRING
source_system     STRING  (garmin | strava | ridewithgps | fit_file)
source_id         STRING
start_time        TIMESTAMP
duration_sec      INT
distance_m        FLOAT
elevation_gain_m  FLOAT
elevation_loss_m  FLOAT
avg_power_w       FLOAT
normalized_power  FLOAT
avg_hr            INT
max_hr            INT
avg_cadence       INT
avg_speed_ms      FLOAT
max_speed_ms      FLOAT
calories          INT
tss               FLOAT   (Training Stress Score)
intensity_factor  FLOAT
sport_type        STRING  (Ride | VirtualRide | Run ...)
is_race           BOOLEAN
route_id          STRING
weather_id        STRING
device            STRING
ingested_at       TIMESTAMP
```

**`silver.activity_streams`** (time-series per activity)
```
activity_id   STRING
time_offset   INT     (seconds from start)
timestamp     TIMESTAMP
lat           DOUBLE
lon           DOUBLE
altitude_m    FLOAT
power_w       INT
heart_rate    INT
cadence       INT
speed_ms      FLOAT
grade_pct     FLOAT
temperature_c FLOAT
distance_m    FLOAT
```

**`silver.routes`**
```
route_id          STRING
athlete_id        STRING
name              STRING
source_system     STRING
distance_m        FLOAT
elevation_gain_m  FLOAT
elevation_loss_m  FLOAT
difficulty        STRING
surface_type      STRING
locality          STRING
gpx_data          STRING
bounding_box      STRUCT<min_lat, max_lat, min_lon, max_lon>
```

**`silver.athletes`**
```
athlete_id            STRING (primary key)
name                  STRING
strava_id             STRING
garmin_id             STRING
ftp_w                 INT    (Functional Threshold Power, updated after each FTP test)
weight_kg             FLOAT
birth_date            DATE
gender                STRING
fitness_level         STRING (Beginner | Intermediate | Advanced | Elite)
training_goal         STRING (free text)
available_hours_week  INT
race_calendar         ARRAY<STRUCT<event_name, event_date, priority>>
injury_history        STRING
notes                 STRING
created_at            TIMESTAMP
updated_at            TIMESTAMP
```

**`silver.daily_health`** (from Garmin daily summaries)
```
athlete_id          STRING
date                DATE
sleep_duration_sec  INT
sleep_score         INT
resting_hr          INT
hrv                 INT
body_battery_start  INT
body_battery_end    INT
stress_score        INT
steps               INT
floors              INT
calories_bmr        INT
```

**`silver.weather`**
```
weather_id        STRING
activity_id       STRING
observation_time  TIMESTAMP
lat               DOUBLE
lon               DOUBLE
temperature_c     FLOAT
feels_like_c      FLOAT
humidity_pct      INT
wind_speed_ms     FLOAT
wind_direction    INT
precipitation_mm  FLOAT
visibility_km     FLOAT
uv_index          INT
condition         STRING
```

### Gold (Coaching Metrics)

**`gold.daily_training_load`**
```
athlete_id      STRING
date            DATE
tss             FLOAT   (daily Training Stress Score)
ctl             FLOAT   (Chronic Training Load, 42-day EWMA)
atl             FLOAT   (Acute Training Load, 7-day EWMA)
tsb             FLOAT   (Training Stress Balance = CTL - ATL)
form            STRING  (Freshness | Neutral | Tired | Overreached)
```

**`gold.fitness_metrics`**
```
athlete_id        STRING
date              DATE
ftp_estimated_w   INT
vo2max_estimated  FLOAT
aerobic_efficiency FLOAT  (watts per bpm)
hr_drift_pct      FLOAT
peak_5s_w         INT
peak_30s_w        INT
peak_1m_w         INT
peak_5m_w         INT
peak_20m_w        INT
peak_60m_w        INT
```

**`gold.weekly_summary`**
```
athlete_id        STRING
week_start        DATE
total_hours       FLOAT
total_tss         FLOAT
total_distance_km FLOAT
total_elevation_m INT
ride_count        INT
avg_sleep_score   FLOAT
avg_body_battery  FLOAT
compliance_pct    FLOAT   (planned vs executed)
```

**`gold.zone_distribution`**
```
athlete_id    STRING
activity_id   STRING
date          DATE
zone_1_pct    FLOAT  (Active Recovery: <55% FTP)
zone_2_pct    FLOAT  (Endurance: 56-75%)
zone_3_pct    FLOAT  (Tempo: 76-90%)
zone_4_pct    FLOAT  (Threshold: 91-105%)
zone_5_pct    FLOAT  (VO2Max: 106-120%)
zone_6_pct    FLOAT  (Anaerobic: 121-150%)
zone_7_pct    FLOAT  (Neuromuscular: >150%)
```

### Coach Schema (Coaching State)

**`coach.training_plans`**
```
plan_id       STRING
athlete_id    STRING
created_at    TIMESTAMP
phase         STRING  (Base | Build | Peak | Recovery)
start_date    DATE
end_date      DATE
weekly_hours  FLOAT
focus         STRING
notes         STRING
status        STRING  (Active | Completed | Paused)
```

**`coach.planned_workouts`**
```
workout_id      STRING
plan_id         STRING
athlete_id      STRING
scheduled_date  DATE
workout_type    STRING  (Endurance | Threshold | VO2Max | Recovery | Long | Race)
duration_min    INT
target_zones    ARRAY<STRUCT<zone, duration_min>>
instructions    STRING
tss_target      FLOAT
completed       BOOLEAN
activity_id     STRING  (linked after completion)
```

**`coach.athlete_goals`**
```
goal_id       STRING
athlete_id    STRING
event_name    STRING
event_date    DATE
priority      STRING  (A | B | C)
event_type    STRING  (Race | Gran Fondo | Century | Sportive)
target        STRING  (free text)
notes         STRING
```

**`coach.coaching_conversations`**
```
conversation_id  STRING
athlete_id       STRING
timestamp        TIMESTAMP
role             STRING  (user | coach)
content          STRING
context_json     STRING  (serialized metrics/state at time of message)
```

**`coach.workout_feedback`**
```
feedback_id   STRING
athlete_id    STRING
activity_id   STRING
generated_at  TIMESTAMP
feedback_text STRING
key_metrics   STRING  (JSON: power, hr, tss, zone distribution highlights)
flags         ARRAY<STRING>  (e.g. "high_hr_drift", "underperformed_threshold")
```

---

## Feature Store

**`features.athlete_daily`** — primary feature table for AI agents
```
athlete_id           STRING
date                 DATE
ctl                  FLOAT
atl                  FLOAT
tsb                  FLOAT
weekly_hours         FLOAT
weekly_tss           FLOAT
sleep_score          INT
body_battery         INT
resting_hr           INT
hrv                  INT
days_to_goal_event   INT
ftp_w                INT
injury_flag          BOOLEAN
weather_stress_score FLOAT
compliance_7d        FLOAT
```

---

## AI Agent Architecture

The LLM (Claude) does NOT compute analytics. It calls tools that query the data layer.

```
Athlete / App
      |
  Chat API
      |
  Coaching Agent (Claude claude-sonnet-4-6)
      |
  Tool Router
      |
  ┌────────────────────────────────────┐
  │  Analytics Engine (Databricks SQL) │
  │  Feature Store                     │
  │  Weather API Client                │
  │  Route Intelligence                │
  └────────────────────────────────────┘
```

### Agent System — Four Specialized Agents

**1. Data Agent**
- Validates incoming ETL data
- Detects schema drift, missing fields
- Flags data quality issues
- Runs on schedule after each ingestion job

**2. Analytics Agent**
- Computes CTL/ATL/TSB daily
- Updates power curve (5s, 30s, 1m, 5m, 20m, 60m bests)
- Estimates FTP from recent efforts
- Calculates zone distributions
- Detects HR drift (aerobic decoupling)
- Runs after Data Agent on each new activity

**3. Planning Agent**
- Inputs: athlete goals, current CTL/ATL/TSB, race calendar, weekly hours, compliance history
- Outputs: periodized training plan (Base/Build/Peak/Recovery phases), daily workout prescriptions
- Adjusts plan weekly based on actual compliance and recovery scores
- Considers weather forecasts when scheduling outdoor vs indoor workouts

**4. Coaching Agent (primary LLM interface)**
- Receives natural language from athlete
- Calls tools to fetch relevant metrics
- Produces post-ride feedback
- Weekly review summaries
- Answers training questions
- Live coaching prompts (Phase 5)

### Coaching Tools (Python functions callable by agents)

```python
get_training_load(athlete_id, date)           # CTL, ATL, TSB, form state
get_fitness_trend(athlete_id, days=90)        # FTP trend, aerobic efficiency
analyze_last_ride(activity_id)                # power, HR, zones, anomalies
detect_overtraining(athlete_id)               # flags if TSB too negative
recommend_next_workout(athlete_id)            # based on plan + current state
get_weather_forecast(lat, lon, days=7)        # for workout planning
score_route(route_id, athlete_id)             # difficulty vs current fitness
get_power_curve(athlete_id)                   # personal record bests
get_weekly_summary(athlete_id)                # compliance, load, sleep
compare_to_period(athlete_id, weeks_ago)      # YoY / month comparison
```

---

## Key Algorithms to Implement

### Training Load (CTL/ATL/TSB)
```
TSS per ride = (duration_sec * NP * IF) / (FTP * 3600) * 100
  where IF = NP / FTP

CTL(today) = CTL(yesterday) + (TSS - CTL(yesterday)) / 42
ATL(today) = ATL(yesterday) + (TSS - ATL(yesterday)) / 7
TSB = CTL - ATL

Form interpretation:
  TSB > +25:  Very fresh (may be detrained)
  TSB +5 to +25: Fresh (race ready)
  TSB -10 to +5: Neutral
  TSB -30 to -10: Tired (productive training)
  TSB < -30: Overreached
```

### Power Zones (% of FTP)
```
Zone 1: <55%   Active Recovery
Zone 2: 56-75%  Endurance
Zone 3: 76-90%  Tempo
Zone 4: 91-105% Threshold
Zone 5: 106-120% VO2Max
Zone 6: 121-150% Anaerobic
Zone 7: >150%   Neuromuscular
```

### Normalized Power
```
NP = (30s rolling average of power^4, averaged over ride, then ^0.25)
```

### HR Drift (Aerobic Decoupling)
```
Pw:HR = (avg_power_first_half / avg_hr_first_half) vs (avg_power_second_half / avg_hr_second_half)
Aerobic decoupling % = ((first_half_ratio - second_half_ratio) / first_half_ratio) * 100
> 5% decoupling = aerobic fitness needs work at that intensity
```

### Injury Risk Score (composite)
```
inputs: TSB, sleep_score, hrv, body_battery, days_since_rest, compliance_streak
weighted sum → 0-100 risk score
flag if > 70
```

---

## External APIs

| API | Purpose | Notes |
|---|---|---|
| OpenWeatherMap | Weather per ride + 7-day forecast | Store API key in Databricks Secrets |
| Strava Webhook | Real-time activity events | Needs HTTP endpoint |
| Garmin Health API | Daily health metrics | OAuth flow |
| RideWithGPS API | Routes, planned rides | OAuth flow |
| Google Maps Elevation | Route elevation profiles | For route scoring |

---

## Phased Build Plan

### Phase 1 — Data Foundation (Build Now)
**Goal:** Clean medallion lakehouse with all data flowing correctly

- [ ] Migrate ETL outputs to `ai_coach` catalog (`bronze` schema)
- [ ] Build silver transformation notebook: activities unified schema
- [ ] Build silver transformation notebook: activity streams
- [ ] Build silver transformation notebook: daily health (from Garmin daily summaries)
- [ ] Build silver transformation notebook: routes unified
- [ ] Build gold metrics: CTL/ATL/TSB calculator (daily job)
- [ ] Build gold metrics: power curve updater
- [ ] Build gold metrics: zone distributions
- [ ] Build gold metrics: weekly summary aggregation
- [ ] Set up Databricks Workflows (Jobs) to chain ingestion -> silver -> gold
- [ ] Build feature store table (`features.athlete_daily`)
- [ ] Add real athlete profile to `silver.athletes`

**Deliverable:** Complete data pipeline from raw APIs to coaching-ready gold tables, running on schedule.

### Phase 2 — AI Coaching Core (After Phase 1)
**Goal:** Claude-powered coaching agent with data tools

- [ ] Build coaching tools library (Python functions querying gold/features tables)
- [ ] Build Coaching Agent using Anthropic SDK (claude-sonnet-4-6)
- [ ] Post-ride feedback generation (triggered after each new activity)
- [ ] Weekly review summaries
- [ ] Training plan generation (Planning Agent)
- [ ] Store all coaching output in `coach.*` tables
- [ ] Test via Databricks notebook interface

**Deliverable:** Run a conversation in a notebook — ask the coach questions, get data-backed answers.

### Phase 3 — Training Intelligence (After Phase 2)
**Goal:** Adaptive, periodized training plans

- [ ] Onboarding flow (capture goals, race calendar, FTP, available hours)
- [ ] Periodized plan generator (Base/Build/Peak/Recovery phases)
- [ ] Weekly plan adaptation (based on compliance + recovery + life events)
- [ ] FTP auto-estimation from power data
- [ ] Race/event strategy generation
- [ ] Workout prescription library (structured interval workouts with targets)
- [ ] Overtraining detection and auto-deload triggering

**Deliverable:** Full 12-week training plan built around a goal event, auto-adjusted weekly.

### Phase 4 — Environmental Intelligence (After Phase 3)
**Goal:** Weather-aware and route-smart coaching

- [ ] Weather ingestion pipeline (OpenWeatherMap → bronze → silver)
- [ ] Weather enrichment of activities (match weather to ride start time/location)
- [ ] Route scoring (difficulty vs current fitness)
- [ ] Weather-based workout recommendations (swap outdoor for indoor, clothing advice)
- [ ] Route recommendation engine (suggest routes matching training goals + conditions)
- [ ] Holistic recovery model (integrate sleep, HRV, body battery, stress)

**Deliverable:** Coach says "It'll be 85°F and windy Saturday — do your long ride Friday instead, here are 3 route options."

### Phase 5 — Web App & Live Coaching (After Phase 4)
**Goal:** Athlete-facing app with live on-bike coaching

- [ ] FastAPI backend (wraps coaching agent, auth, athlete data endpoints)
- [ ] Next.js / React frontend (dashboard, chat interface, training calendar)
- [ ] Databricks Model Serving endpoint for coaching agent
- [ ] Real-time coaching mode: athlete streams GPS + power/HR data during ride, coach responds with cues
- [ ] Push notifications (workout reminders, recovery alerts, weather changes)
- [ ] Mobile-responsive design (athlete uses phone on the bike)
- [ ] Training calendar view (planned vs completed workouts)
- [ ] Performance dashboard (CTL/ATL/TSB chart, power curve, zone history)
- [ ] Route map visualization
- [ ] Bike fit flagging (detect position-related patterns in power/HR data)

**Deliverable:** Full web app, athlete logs in, chats with coach, sees all metrics, gets live coaching on rides.

---

## Repository Layout (Target)

```
ai-coach/
  ingestion/
    garmin_connector.py         (refactored from notebook)
    strava_connector.py
    ridewithgps_connector.py
    weather_client.py
    fit_parser.py               (parse .fit files with fitparse)

  pipelines/
    bronze_to_silver.py
    silver_to_gold.py
    feature_refresh.py

  analytics/
    training_load.py            (CTL/ATL/TSB)
    power_curve.py
    zone_calculator.py
    hr_drift.py
    ftp_estimator.py
    injury_risk.py

  agents/
    coaching_agent.py           (main Claude agent)
    planning_agent.py
    analytics_agent.py

  tools/
    training_tools.py           (get_training_load, get_fitness_trend, etc.)
    ride_analysis_tools.py
    weather_tools.py
    route_tools.py

  api/
    main.py                     (FastAPI app)
    auth.py
    athlete_router.py
    coaching_router.py

  ui/                           (Next.js app)
    app/
    components/

  notebooks/                    (Databricks notebooks)
    ingestion/
    transformations/
    analytics/
    experimentation/

  jobs/                         (Databricks Workflow definitions, YAML)
    ingest_all.yml
    bronze_to_silver.yml
    silver_to_gold.yml
    feature_refresh.yml

  -- existing notebooks (to be refactored into above structure) --
  Garmin Data Ingest.ipynb
  Strava Data Ingest.ipynb
  RideWithGPS Data Ingest.ipynb
  create delta tables.ipynb
```

---

## Databricks Jobs Pipeline (Target)

```
[Schedule: every 6h]
  ingest_garmin → ingest_strava → ingest_ridewithgps
          |
  bronze_to_silver (triggered after ingestion)
          |
  silver_to_gold (CTL/ATL/TSB, power curve, zone distributions)
          |
  feature_refresh (athlete_daily feature table)
          |
  [Event: new activity]
  post_ride_analysis → coaching_agent → write feedback to coach.workout_feedback
```

---

## What Good Coaching Looks Like (System Behavior Tests)

These are acceptance criteria for the system:

1. **After a hard ride:** "Your TSB is now -24 (tired). Power was solid — NP was 102% of your threshold. HR drift was 7% in the final hour, which tells me your aerobic base needs more Z2 work. Rest tomorrow."

2. **Weekly review:** "This week you hit 87% of planned TSS. CTL climbed 3 points to 68. Sleep was below average (5.8hrs avg) — watch that, it's slowing recovery. Saturday's climb was your best 20-min power in 6 weeks."

3. **Plan adaptation:** "You missed three workouts this week. I'm adjusting next week — dropping the Tuesday VO2 session and adding an aerobic endurance day instead. Don't force intensity on a TSB of -32."

4. **Pre-race:** "Your target race is in 8 days. TSB is +12 — right in the performance window. Taper protocol: no hard efforts after Wednesday. Thursday: 45min easy with 3x5min at threshold to keep legs sharp."

5. **Weather-aware:** "Rain and 12mph headwind forecast Saturday. I'm moving your 4hr endurance ride to Friday's clear window. Saturday becomes a 90min indoor threshold session."

---

## Tech Stack Summary

| Layer | Technology |
|---|---|
| Data storage | Databricks Delta Lake + Unity Catalog |
| ETL orchestration | Databricks Workflows (Jobs) |
| Compute | Databricks Serverless SQL + Classic clusters |
| AI agent | Anthropic Claude claude-sonnet-4-6 via API |
| Agent framework | Anthropic SDK (tool use) |
| Model serving | Databricks Model Serving (for web app integration) |
| Backend API | FastAPI (Python) |
| Frontend | Next.js + React |
| Weather | OpenWeatherMap API |
| Secrets | Databricks Secrets |
| Local dev | Python, uv, notebooks |

---

## Immediate Next Steps (Start Here)

1. **Set up `ai_coach` catalog in Databricks** — create bronze/silver/gold/features/coach schemas
2. **Migrate existing ETL notebooks** to write raw data into `ai_coach.bronze.*`
3. **Build `bronze_to_silver` notebook** — unified `silver.activities` from all 3 sources
4. **Build CTL/ATL/TSB calculator** — populate `gold.daily_training_load`
5. **Add real athlete profile** — replace placeholder data in `silver.athletes`
6. **Build first coaching tool** — `analyze_last_ride()` querying silver + gold
7. **Wire up Claude** — basic coaching agent that calls the tool and returns feedback on a ride
