# Databricks notebook source

# MAGIC %md
# MAGIC # 02 — Bronze to Silver
# MAGIC
# MAGIC Normalizes raw data from all sources into a unified canonical silver schema.
# MAGIC
# MAGIC **Reads from:**
# MAGIC - `garmin.activities`, `garmin.daily_summaries`
# MAGIC - `ai_coach.bronze.strava_activities_raw`, `ai_coach.bronze.strava_streams_raw`, `ai_coach.bronze.strava_athlete_raw`
# MAGIC - `ridewithgps.routes`, `ridewithgps.trips`
# MAGIC
# MAGIC **Writes to:**
# MAGIC - `ai_coach.silver.athletes`
# MAGIC - `ai_coach.silver.activities`
# MAGIC - `ai_coach.silver.activity_streams`
# MAGIC - `ai_coach.silver.daily_health`
# MAGIC - `ai_coach.silver.routes`

# COMMAND ----------

# MAGIC %md ## Configuration

# COMMAND ----------

CATALOG = "ai_coach"

# Your athlete ID — used to link data from all sources.
# This gets set during onboarding (notebook 05), but define it here for running standalone.
ATHLETE_ID = dbutils.widgets.get("athlete_id") if "athlete_id" in [w.name for w in dbutils.widgets.getAll()] else "athlete_1"

print(f"Catalog:    {CATALOG}")
print(f"Athlete ID: {ATHLETE_ID}")

# COMMAND ----------

from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col, lit, concat, cast, when, coalesce, to_date, to_timestamp,
    unix_timestamp, from_unixtime, expr, round as spark_round
)
from pyspark.sql.types import *
from datetime import datetime

spark = SparkSession.builder.getOrCreate()

# COMMAND ----------

# MAGIC %md ## 1 — silver.athletes (from Strava athlete profile)

# COMMAND ----------

try:
    df_strava_athlete = spark.table(f"{CATALOG}.bronze.strava_athlete_raw")

    df_silver_athlete = df_strava_athlete.select(
        concat(lit("strava_"), col("athlete_id").cast("string")).alias("athlete_id"),
        concat(col("firstname"), lit(" "), col("lastname")).alias("name"),
        col("athlete_id").cast("string").alias("strava_id"),
        lit(None).cast("string").alias("garmin_id"),
        col("ftp").alias("ftp_w"),
        col("weight_kg"),
        lit(None).cast("date").alias("birth_date"),
        col("sex").alias("gender"),
        lit("Intermediate").alias("fitness_level"),
        lit(None).cast("string").alias("training_goal"),
        lit(8).alias("available_hours_week"),
        lit(None).cast("int").alias("lthr"),
        lit(None).cast("int").alias("max_hr"),
        lit(None).cast("int").alias("resting_hr"),
        lit(None).cast("string").alias("notes"),
        col("retrieved_at").alias("created_at"),
        col("retrieved_at").alias("updated_at"),
    )

    # Only insert if not already present
    df_silver_athlete.createOrReplaceTempView("strava_athlete_silver")
    spark.sql(f"""
    MERGE INTO {CATALOG}.silver.athletes AS target
    USING strava_athlete_silver AS source
    ON target.athlete_id = source.athlete_id
    WHEN MATCHED THEN UPDATE SET
      ftp_w = source.ftp_w,
      weight_kg = source.weight_kg,
      updated_at = source.updated_at
    WHEN NOT MATCHED THEN INSERT *
    """)
    print("✅ silver.athletes updated from Strava athlete profile")

except Exception as e:
    print(f"⚠️  Could not update silver.athletes from Strava: {e}")
    print("   Run notebook 05_athlete_setup first to create the athlete record.")

# COMMAND ----------

# MAGIC %md ## 2 — silver.activities

# COMMAND ----------

# MAGIC %md ### 2a — Garmin activities

# COMMAND ----------

try:
    df_garmin = spark.table("garmin.activities")

    df_garmin_silver = df_garmin.select(
        concat(lit("garmin_"), col("activity_id").cast("string")).alias("activity_id"),
        lit(ATHLETE_ID).alias("athlete_id"),
        lit("garmin").alias("source_system"),
        col("activity_id").cast("string").alias("source_id"),
        col("start_time"),
        col("duration").cast("int").alias("duration_sec"),
        col("distance").alias("distance_m"),
        col("elevation_gain").alias("elevation_gain_m"),
        col("elevation_loss").alias("elevation_loss_m"),
        lit(None).cast("double").alias("avg_power_w"),
        lit(None).cast("double").alias("normalized_power"),
        col("avg_heart_rate").cast("int").alias("avg_hr"),
        col("max_heart_rate").cast("int").alias("max_hr"),
        lit(None).cast("int").alias("avg_cadence"),
        col("avg_speed").alias("avg_speed_ms"),
        col("max_speed").alias("max_speed_ms"),
        col("calories").cast("int"),
        lit(None).cast("double").alias("tss"),
        lit(None).cast("double").alias("intensity_factor"),
        col("activity_type").alias("sport_type"),
        lit(False).alias("is_race"),
        lit(None).cast("string").alias("route_id"),
        lit(None).cast("string").alias("weather_id"),
        lit("garmin").alias("device"),
        col("retrieved_at").alias("ingested_at"),
    )

    df_garmin_silver.createOrReplaceTempView("garmin_activities_silver")
    spark.sql(f"""
    MERGE INTO {CATALOG}.silver.activities AS target
    USING garmin_activities_silver AS source
    ON target.activity_id = source.activity_id
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
    """)
    garmin_count = spark.sql("SELECT COUNT(*) AS n FROM garmin_activities_silver").collect()[0].n
    print(f"✅ Garmin: {garmin_count} activities upserted into silver.activities")

except Exception as e:
    print(f"⚠️  Could not process Garmin activities: {e}")

# COMMAND ----------

# MAGIC %md ### 2b — Strava activities

# COMMAND ----------

try:
    df_strava = spark.table(f"{CATALOG}.bronze.strava_activities_raw")

    # Only process cycling activities
    cycling_types = ["Ride", "VirtualRide", "MountainBikeRide", "GravelRide", "EBikeRide"]
    df_strava = df_strava.filter(col("activity_type").isin(cycling_types))

    df_strava_silver = df_strava.select(
        concat(lit("strava_"), col("activity_id").cast("string")).alias("activity_id"),
        lit(ATHLETE_ID).alias("athlete_id"),
        lit("strava").alias("source_system"),
        col("activity_id").cast("string").alias("source_id"),
        col("start_date_local").alias("start_time"),
        col("duration_sec"),
        col("distance_m"),
        col("elevation_gain_m"),
        lit(None).cast("double").alias("elevation_loss_m"),
        col("avg_watts").alias("avg_power_w"),
        col("weighted_avg_watts").cast("double").alias("normalized_power"),
        col("avg_heartrate").cast("int").alias("avg_hr"),
        col("max_heartrate").cast("int").alias("max_hr"),
        col("avg_cadence").cast("int"),
        col("avg_speed_ms"),
        col("max_speed_ms"),
        col("calories"),
        lit(None).cast("double").alias("tss"),        # computed in silver_to_gold
        lit(None).cast("double").alias("intensity_factor"),
        col("activity_type").alias("sport_type"),
        lit(False).alias("is_race"),
        lit(None).cast("string").alias("route_id"),
        lit(None).cast("string").alias("weather_id"),
        lit("strava").alias("device"),
        col("retrieved_at").alias("ingested_at"),
    )

    df_strava_silver.createOrReplaceTempView("strava_activities_silver")
    spark.sql(f"""
    MERGE INTO {CATALOG}.silver.activities AS target
    USING strava_activities_silver AS source
    ON target.activity_id = source.activity_id
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
    """)
    strava_count = spark.sql("SELECT COUNT(*) AS n FROM strava_activities_silver").collect()[0].n
    print(f"✅ Strava: {strava_count} activities upserted into silver.activities")

except Exception as e:
    print(f"⚠️  Could not process Strava activities: {e}")

# COMMAND ----------

# MAGIC %md ### 2c — RideWithGPS trips

# COMMAND ----------

try:
    df_rwgps = spark.table("ridewithgps.trips")

    df_rwgps_silver = df_rwgps.select(
        concat(lit("rwgps_"), col("trip_id").cast("string")).alias("activity_id"),
        lit(ATHLETE_ID).alias("athlete_id"),
        lit("ridewithgps").alias("source_system"),
        col("trip_id").cast("string").alias("source_id"),
        col("started_at").alias("start_time"),
        col("duration").cast("int").alias("duration_sec"),
        col("distance").alias("distance_m"),
        col("elevation_gain").alias("elevation_gain_m"),
        col("elevation_loss").alias("elevation_loss_m"),
        lit(None).cast("double").alias("avg_power_w"),
        lit(None).cast("double").alias("normalized_power"),
        lit(None).cast("int").alias("avg_hr"),
        lit(None).cast("int").alias("max_hr"),
        lit(None).cast("int").alias("avg_cadence"),
        col("avg_speed").alias("avg_speed_ms"),
        col("max_speed").alias("max_speed_ms"),
        lit(None).cast("int").alias("calories"),
        lit(None).cast("double").alias("tss"),
        lit(None).cast("double").alias("intensity_factor"),
        lit("Ride").alias("sport_type"),
        lit(False).alias("is_race"),
        col("route_id").cast("string").alias("route_id"),
        lit(None).cast("string").alias("weather_id"),
        lit("ridewithgps").alias("device"),
        col("retrieved_at").alias("ingested_at"),
    )

    df_rwgps_silver.createOrReplaceTempView("rwgps_activities_silver")
    spark.sql(f"""
    MERGE INTO {CATALOG}.silver.activities AS target
    USING rwgps_activities_silver AS source
    ON target.activity_id = source.activity_id
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
    """)
    rwgps_count = spark.sql("SELECT COUNT(*) AS n FROM rwgps_activities_silver").collect()[0].n
    print(f"✅ RideWithGPS: {rwgps_count} trips upserted into silver.activities")

except Exception as e:
    print(f"⚠️  Could not process RideWithGPS trips: {e}")

# COMMAND ----------

# MAGIC %md ## 3 — silver.activity_streams (from Strava bronze streams)

# COMMAND ----------

try:
    df_streams_bronze = spark.table(f"{CATALOG}.bronze.strava_streams_raw")

    # Join to activities to get start_time so we can compute absolute timestamp
    df_acts = spark.table(f"{CATALOG}.bronze.strava_activities_raw") \
        .select("activity_id", "start_date_local")

    df_streams_silver = df_streams_bronze.join(df_acts, on="activity_id", how="left") \
        .select(
            concat(lit("strava_"), col("activity_id").cast("string")).alias("activity_id"),
            col("time_offset"),
            (col("start_date_local").cast("long") + col("time_offset"))
                .cast("timestamp").alias("ts"),
            col("lat"),
            col("lon"),
            col("altitude_m").alias("altitude_m"),
            col("watts").alias("power_w"),
            col("heartrate").alias("heart_rate"),
            col("cadence"),
            col("velocity_ms").alias("speed_ms"),
            col("grade_pct"),
            col("temperature_c"),
            col("distance_m"),
        )

    # Overwrite streams (they're stable — re-run is safe)
    df_streams_silver.write.format("delta") \
        .mode("overwrite") \
        .option("mergeSchema", "true") \
        .partitionBy("activity_id") \
        .saveAsTable(f"{CATALOG}.silver.activity_streams")

    stream_count = spark.sql(f"SELECT COUNT(*) AS n FROM {CATALOG}.silver.activity_streams").collect()[0].n
    print(f"✅ {stream_count:,} stream rows written to silver.activity_streams")

except Exception as e:
    print(f"⚠️  Could not process activity streams: {e}")

# COMMAND ----------

# MAGIC %md ## 4 — silver.daily_health (from Garmin daily summaries)

# COMMAND ----------

try:
    df_garmin_daily = spark.table("garmin.daily_summaries")

    df_health_silver = df_garmin_daily.select(
        lit(ATHLETE_ID).alias("athlete_id"),
        to_date(col("date"), "yyyy-MM-dd").alias("date"),
        col("sleep_duration_seconds").alias("sleep_duration_sec"),
        col("resting_heart_rate").alias("resting_hr"),
        col("max_heart_rate").alias("max_hr"),
        col("stress_score"),
        col("body_battery"),
        col("steps"),
        col("floors_climbed").alias("floors"),
        col("calories_burned").alias("calories_bmr"),
        col("active_minutes"),
        col("distance_meters"),
    )

    df_health_silver.createOrReplaceTempView("daily_health_silver")
    spark.sql(f"""
    MERGE INTO {CATALOG}.silver.daily_health AS target
    USING daily_health_silver AS source
    ON target.athlete_id = source.athlete_id AND target.date = source.date
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
    """)
    health_count = spark.sql("SELECT COUNT(*) AS n FROM daily_health_silver").collect()[0].n
    print(f"✅ {health_count} daily health records upserted into silver.daily_health")

except Exception as e:
    print(f"⚠️  Could not process Garmin daily summaries: {e}")

# COMMAND ----------

# MAGIC %md ## 5 — silver.routes (from RideWithGPS routes)

# COMMAND ----------

try:
    df_rwgps_routes = spark.table("ridewithgps.routes")

    # Also pull GPX data from route_details if available
    try:
        df_route_details = spark.table("ridewithgps.route_details") \
            .select(col("id").alias("route_id"), col("gpx"))
    except Exception:
        df_route_details = None

    df_routes_silver = df_rwgps_routes.select(
        concat(lit("rwgps_"), col("route_id").cast("string")).alias("route_id"),
        lit(ATHLETE_ID).alias("athlete_id"),
        col("name"),
        lit("ridewithgps").alias("source_system"),
        col("distance").alias("distance_m"),
        col("elevation_gain").alias("elevation_gain_m"),
        col("elevation_loss").alias("elevation_loss_m"),
        col("difficulty"),
        col("surface_type"),
        col("locality"),
        col("country_code"),
        lit(None).cast("string").alias("gpx_data"),
        col("bounding_box_sw_lat").alias("bounding_sw_lat"),
        col("bounding_box_sw_lng").alias("bounding_sw_lng"),
        col("bounding_box_ne_lat").alias("bounding_ne_lat"),
        col("bounding_box_ne_lng").alias("bounding_ne_lng"),
        col("created_at"),
    )

    # Join in GPX data if available
    if df_route_details is not None:
        df_route_details = df_route_details.select(
            concat(lit("rwgps_"), col("route_id").cast("string")).alias("route_id"),
            col("gpx").alias("gpx_data")
        )
        df_routes_silver = df_routes_silver.drop("gpx_data") \
            .join(df_route_details, on="route_id", how="left")

    df_routes_silver.createOrReplaceTempView("routes_silver")
    spark.sql(f"""
    MERGE INTO {CATALOG}.silver.routes AS target
    USING routes_silver AS source
    ON target.route_id = source.route_id
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
    """)
    route_count = spark.sql("SELECT COUNT(*) AS n FROM routes_silver").collect()[0].n
    print(f"✅ {route_count} routes upserted into silver.routes")

except Exception as e:
    print(f"⚠️  Could not process RideWithGPS routes: {e}")

# COMMAND ----------

# MAGIC %md ## Summary

# COMMAND ----------

print("\n" + "="*50)
print("Silver Layer Summary")
print("="*50)

tables = [
    "silver.athletes",
    "silver.activities",
    "silver.activity_streams",
    "silver.daily_health",
    "silver.routes",
]
for t in tables:
    try:
        n = spark.sql(f"SELECT COUNT(*) AS n FROM {CATALOG}.{t}").collect()[0].n
        print(f"  {t}: {n:,} rows")
    except Exception as e:
        print(f"  {t}: error — {e}")
