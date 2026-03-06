# Databricks notebook source

# MAGIC %md
# MAGIC # 00 — Setup ai_coach Catalog
# MAGIC
# MAGIC Creates the full `ai_coach` Unity Catalog with all schemas and tables.
# MAGIC Run this **once** before any other notebook.
# MAGIC
# MAGIC **Schemas created:**
# MAGIC - `bronze` — raw API payloads exactly as received
# MAGIC - `silver` — normalized, unified canonical schema
# MAGIC - `gold` — aggregated coaching metrics
# MAGIC - `features` — feature store for AI agents
# MAGIC - `coach` — coaching state: plans, workouts, goals, conversations

# COMMAND ----------

# MAGIC %md
# MAGIC ## Configuration
# MAGIC
# MAGIC If you are on Databricks Community Edition or don't have permission to create catalogs,
# MAGIC set `CATALOG = "main"` and it will create schemas inside the `main` catalog instead.

# COMMAND ----------

# Set catalog name here — change to "main" if you can't create new catalogs
CATALOG = "ai_coach"

print(f"Target catalog: {CATALOG}")

# COMMAND ----------

# MAGIC %md ## Create Catalog & Schemas

# COMMAND ----------

from pyspark.sql import SparkSession
spark = SparkSession.builder.getOrCreate()

# Create catalog (skip if using existing catalog like "main")
if CATALOG != "main":
    spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}")
    print(f"✅ Catalog '{CATALOG}' ready")
else:
    print("Using existing 'main' catalog")

# Create schemas
schemas = ["bronze", "silver", "gold", "features", "coach"]
for schema in schemas:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{schema}")
    print(f"✅ Schema '{CATALOG}.{schema}' ready")

# COMMAND ----------

# MAGIC %md ## Bronze Tables

# COMMAND ----------

# bronze.garmin_activities_raw
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.bronze.garmin_activities_raw (
  activity_id       BIGINT,
  activity_name     STRING,
  activity_type     STRING,
  start_time        TIMESTAMP,
  duration          BIGINT,
  distance          DOUBLE,
  calories          BIGINT,
  avg_heart_rate    BIGINT,
  max_heart_rate    BIGINT,
  avg_speed         DOUBLE,
  max_speed         DOUBLE,
  elevation_gain    DOUBLE,
  elevation_loss    DOUBLE,
  retrieved_at      TIMESTAMP
)
USING DELTA
""")
print("✅ bronze.garmin_activities_raw")

# bronze.garmin_daily_raw
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.bronze.garmin_daily_raw (
  date                    STRING,
  steps                   BIGINT,
  calories_burned         BIGINT,
  distance_meters         DOUBLE,
  active_minutes          BIGINT,
  floors_climbed          BIGINT,
  sleep_duration_seconds  BIGINT,
  resting_heart_rate      BIGINT,
  max_heart_rate          BIGINT,
  stress_score            BIGINT,
  body_battery            BIGINT,
  retrieved_at            TIMESTAMP
)
USING DELTA
""")
print("✅ bronze.garmin_daily_raw")

# bronze.garmin_activity_details_raw
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.bronze.garmin_activity_details_raw (
  activity_id       BIGINT,
  detailed_metrics  STRING,
  gps_data          STRING,
  heart_rate_zones  STRING,
  splits            STRING,
  retrieved_at      TIMESTAMP
)
USING DELTA
""")
print("✅ bronze.garmin_activity_details_raw")

# bronze.strava_activities_raw
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.bronze.strava_activities_raw (
  activity_id         BIGINT,
  activity_name       STRING,
  activity_type       STRING,
  start_date          TIMESTAMP,
  start_date_local    TIMESTAMP,
  timezone            STRING,
  duration_sec        INT,
  distance_m          DOUBLE,
  elevation_gain_m    DOUBLE,
  avg_speed_ms        DOUBLE,
  max_speed_ms        DOUBLE,
  avg_heartrate       DOUBLE,
  max_heartrate       DOUBLE,
  avg_watts           DOUBLE,
  max_watts           INT,
  weighted_avg_watts  INT,
  avg_cadence         DOUBLE,
  calories            INT,
  suffer_score        INT,
  kudos_count         INT,
  pr_count            INT,
  gear_id             STRING,
  start_lat           DOUBLE,
  start_lon           DOUBLE,
  athlete_id          BIGINT,
  raw_json            STRING,
  retrieved_at        TIMESTAMP
)
USING DELTA
""")
print("✅ bronze.strava_activities_raw")

# bronze.strava_streams_raw
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.bronze.strava_streams_raw (
  activity_id     BIGINT,
  time_offset     INT,
  distance_m      DOUBLE,
  altitude_m      DOUBLE,
  lat             DOUBLE,
  lon             DOUBLE,
  heartrate       INT,
  watts           INT,
  cadence         INT,
  velocity_ms     DOUBLE,
  grade_pct       DOUBLE,
  temperature_c   DOUBLE,
  moving          BOOLEAN,
  retrieved_at    TIMESTAMP
)
USING DELTA
""")
print("✅ bronze.strava_streams_raw")

# bronze.strava_athlete_raw
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.bronze.strava_athlete_raw (
  athlete_id    BIGINT,
  firstname     STRING,
  lastname      STRING,
  ftp           INT,
  weight_kg     DOUBLE,
  country       STRING,
  city          STRING,
  sex           STRING,
  raw_json      STRING,
  retrieved_at  TIMESTAMP
)
USING DELTA
""")
print("✅ bronze.strava_athlete_raw")

# bronze.ridewithgps_routes_raw
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.bronze.ridewithgps_routes_raw (
  route_id                BIGINT,
  name                    STRING,
  description             STRING,
  distance                DOUBLE,
  elevation_gain          DOUBLE,
  elevation_loss          DOUBLE,
  difficulty              STRING,
  surface_type            STRING,
  created_at              TIMESTAMP,
  updated_at              TIMESTAMP,
  is_private              BOOLEAN,
  user_id                 BIGINT,
  locality                STRING,
  administrative_area     STRING,
  country_code            STRING,
  bounding_box_sw_lat     DOUBLE,
  bounding_box_sw_lng     DOUBLE,
  bounding_box_ne_lat     DOUBLE,
  bounding_box_ne_lng     DOUBLE,
  retrieved_at            TIMESTAMP
)
USING DELTA
""")
print("✅ bronze.ridewithgps_routes_raw")

# bronze.ridewithgps_trips_raw
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.bronze.ridewithgps_trips_raw (
  trip_id               BIGINT,
  name                  STRING,
  description           STRING,
  distance              DOUBLE,
  duration              DOUBLE,
  elevation_gain        DOUBLE,
  elevation_loss        DOUBLE,
  avg_speed             DOUBLE,
  max_speed             DOUBLE,
  started_at            TIMESTAMP,
  is_private            BOOLEAN,
  user_id               BIGINT,
  route_id              BIGINT,
  locality              STRING,
  administrative_area   STRING,
  country_code          STRING,
  retrieved_at          TIMESTAMP
)
USING DELTA
""")
print("✅ bronze.ridewithgps_trips_raw")

# bronze.weather_raw
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.bronze.weather_raw (
  weather_id          STRING,
  activity_id         STRING,
  observation_time    TIMESTAMP,
  lat                 DOUBLE,
  lon                 DOUBLE,
  temperature_c       DOUBLE,
  feels_like_c        DOUBLE,
  humidity_pct        INT,
  wind_speed_ms       DOUBLE,
  wind_direction      INT,
  precipitation_mm    DOUBLE,
  visibility_km       DOUBLE,
  uv_index            INT,
  condition           STRING,
  raw_json            STRING,
  retrieved_at        TIMESTAMP
)
USING DELTA
""")
print("✅ bronze.weather_raw")

# COMMAND ----------

# MAGIC %md ## Silver Tables

# COMMAND ----------

# silver.athletes
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.silver.athletes (
  athlete_id              STRING NOT NULL,
  name                    STRING,
  strava_id               STRING,
  garmin_id               STRING,
  ftp_w                   INT,
  weight_kg               DOUBLE,
  birth_date              DATE,
  gender                  STRING,
  fitness_level           STRING,
  training_goal           STRING,
  available_hours_week    INT,
  lthr                    INT,
  max_hr                  INT,
  resting_hr              INT,
  notes                   STRING,
  created_at              TIMESTAMP,
  updated_at              TIMESTAMP
)
USING DELTA
""")
print("✅ silver.athletes")

# silver.activities
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.silver.activities (
  activity_id         STRING NOT NULL,
  athlete_id          STRING,
  source_system       STRING,
  source_id           STRING,
  start_time          TIMESTAMP,
  duration_sec        INT,
  distance_m          DOUBLE,
  elevation_gain_m    DOUBLE,
  elevation_loss_m    DOUBLE,
  avg_power_w         DOUBLE,
  normalized_power    DOUBLE,
  avg_hr              INT,
  max_hr              INT,
  avg_cadence         INT,
  avg_speed_ms        DOUBLE,
  max_speed_ms        DOUBLE,
  calories            INT,
  tss                 DOUBLE,
  intensity_factor    DOUBLE,
  sport_type          STRING,
  is_race             BOOLEAN,
  route_id            STRING,
  weather_id          STRING,
  device              STRING,
  ingested_at         TIMESTAMP
)
USING DELTA
""")
print("✅ silver.activities")

# silver.activity_streams
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.silver.activity_streams (
  activity_id   STRING NOT NULL,
  time_offset   INT,
  ts            TIMESTAMP,
  lat           DOUBLE,
  lon           DOUBLE,
  altitude_m    DOUBLE,
  power_w       INT,
  heart_rate    INT,
  cadence       INT,
  speed_ms      DOUBLE,
  grade_pct     DOUBLE,
  temperature_c DOUBLE,
  distance_m    DOUBLE
)
USING DELTA
PARTITIONED BY (activity_id)
""")
print("✅ silver.activity_streams")

# silver.daily_health
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.silver.daily_health (
  athlete_id          STRING NOT NULL,
  date                DATE NOT NULL,
  sleep_duration_sec  BIGINT,
  resting_hr          BIGINT,
  max_hr              BIGINT,
  stress_score        BIGINT,
  body_battery        BIGINT,
  steps               BIGINT,
  floors              BIGINT,
  calories_bmr        BIGINT,
  active_minutes      BIGINT,
  distance_meters     DOUBLE
)
USING DELTA
""")
print("✅ silver.daily_health")

# silver.routes
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.silver.routes (
  route_id              STRING NOT NULL,
  athlete_id            STRING,
  name                  STRING,
  source_system         STRING,
  distance_m            DOUBLE,
  elevation_gain_m      DOUBLE,
  elevation_loss_m      DOUBLE,
  difficulty            STRING,
  surface_type          STRING,
  locality              STRING,
  country_code          STRING,
  gpx_data              STRING,
  bounding_sw_lat       DOUBLE,
  bounding_sw_lng       DOUBLE,
  bounding_ne_lat       DOUBLE,
  bounding_ne_lng       DOUBLE,
  created_at            TIMESTAMP
)
USING DELTA
""")
print("✅ silver.routes")

# silver.weather
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.silver.weather (
  weather_id        STRING NOT NULL,
  activity_id       STRING,
  observation_time  TIMESTAMP,
  lat               DOUBLE,
  lon               DOUBLE,
  temperature_c     DOUBLE,
  feels_like_c      DOUBLE,
  humidity_pct      INT,
  wind_speed_ms     DOUBLE,
  wind_direction    INT,
  precipitation_mm  DOUBLE,
  visibility_km     DOUBLE,
  uv_index          INT,
  condition         STRING
)
USING DELTA
""")
print("✅ silver.weather")

# COMMAND ----------

# MAGIC %md ## Gold Tables

# COMMAND ----------

# gold.daily_training_load
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.gold.daily_training_load (
  athlete_id  STRING NOT NULL,
  date        DATE   NOT NULL,
  tss         DOUBLE,
  ctl         DOUBLE,
  atl         DOUBLE,
  tsb         DOUBLE,
  form        STRING
)
USING DELTA
""")
print("✅ gold.daily_training_load")

# gold.fitness_metrics
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.gold.fitness_metrics (
  athlete_id          STRING NOT NULL,
  date                DATE   NOT NULL,
  ftp_estimated_w     INT,
  aerobic_efficiency  DOUBLE,
  hr_drift_pct        DOUBLE,
  peak_5s_w           INT,
  peak_30s_w          INT,
  peak_1m_w           INT,
  peak_5m_w           INT,
  peak_20m_w          INT,
  peak_60m_w          INT
)
USING DELTA
""")
print("✅ gold.fitness_metrics")

# gold.weekly_summary
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.gold.weekly_summary (
  athlete_id          STRING NOT NULL,
  week_start          DATE   NOT NULL,
  total_hours         DOUBLE,
  total_tss           DOUBLE,
  total_distance_km   DOUBLE,
  total_elevation_m   INT,
  ride_count          INT,
  avg_sleep_sec       DOUBLE,
  avg_body_battery    DOUBLE,
  avg_resting_hr      DOUBLE,
  compliance_pct      DOUBLE
)
USING DELTA
""")
print("✅ gold.weekly_summary")

# gold.zone_distribution
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.gold.zone_distribution (
  athlete_id    STRING NOT NULL,
  activity_id   STRING NOT NULL,
  date          DATE,
  zone_1_pct    DOUBLE,
  zone_2_pct    DOUBLE,
  zone_3_pct    DOUBLE,
  zone_4_pct    DOUBLE,
  zone_5_pct    DOUBLE,
  zone_6_pct    DOUBLE,
  zone_7_pct    DOUBLE,
  zone_basis    STRING
)
USING DELTA
""")
print("✅ gold.zone_distribution")

# COMMAND ----------

# MAGIC %md ## Feature Table

# COMMAND ----------

# features.athlete_daily
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.features.athlete_daily (
  athlete_id            STRING NOT NULL,
  date                  DATE   NOT NULL,
  ctl                   DOUBLE,
  atl                   DOUBLE,
  tsb                   DOUBLE,
  form                  STRING,
  weekly_hours          DOUBLE,
  weekly_tss            DOUBLE,
  sleep_duration_sec    BIGINT,
  body_battery          BIGINT,
  resting_hr            BIGINT,
  stress_score          BIGINT,
  days_to_goal_event    INT,
  ftp_w                 INT,
  injury_flag           BOOLEAN,
  compliance_7d         DOUBLE
)
USING DELTA
""")
print("✅ features.athlete_daily")

# COMMAND ----------

# MAGIC %md ## Coach Schema Tables

# COMMAND ----------

# coach.training_plans
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.coach.training_plans (
  plan_id       STRING NOT NULL,
  athlete_id    STRING,
  created_at    TIMESTAMP,
  phase         STRING,
  start_date    DATE,
  end_date      DATE,
  weekly_hours  DOUBLE,
  focus         STRING,
  notes         STRING,
  status        STRING
)
USING DELTA
""")
print("✅ coach.training_plans")

# coach.planned_workouts
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.coach.planned_workouts (
  workout_id      STRING NOT NULL,
  plan_id         STRING,
  athlete_id      STRING,
  scheduled_date  DATE,
  workout_type    STRING,
  duration_min    INT,
  instructions    STRING,
  tss_target      DOUBLE,
  completed       BOOLEAN,
  activity_id     STRING,
  created_at      TIMESTAMP
)
USING DELTA
""")
print("✅ coach.planned_workouts")

# coach.athlete_goals
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.coach.athlete_goals (
  goal_id       STRING NOT NULL,
  athlete_id    STRING,
  event_name    STRING,
  event_date    DATE,
  priority      STRING,
  event_type    STRING,
  target        STRING,
  notes         STRING,
  created_at    TIMESTAMP
)
USING DELTA
""")
print("✅ coach.athlete_goals")

# coach.coaching_conversations
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.coach.coaching_conversations (
  conversation_id  STRING NOT NULL,
  athlete_id       STRING,
  ts               TIMESTAMP,
  role             STRING,
  content          STRING,
  context_json     STRING
)
USING DELTA
""")
print("✅ coach.coaching_conversations")

# coach.workout_feedback
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.coach.workout_feedback (
  feedback_id    STRING NOT NULL,
  athlete_id     STRING,
  activity_id    STRING,
  generated_at   TIMESTAMP,
  feedback_text  STRING,
  key_metrics    STRING,
  flags          ARRAY<STRING>
)
USING DELTA
""")
print("✅ coach.workout_feedback")

# COMMAND ----------

# MAGIC %md ## Verify Setup

# COMMAND ----------

print(f"\n{'='*50}")
print(f"ai_coach catalog setup complete")
print(f"{'='*50}\n")

for schema in ["bronze", "silver", "gold", "features", "coach"]:
    tables = spark.sql(f"SHOW TABLES IN {CATALOG}.{schema}").collect()
    print(f"{CATALOG}.{schema}: {len(tables)} tables")
    for t in tables:
        print(f"  - {t.tableName}")
    print()
