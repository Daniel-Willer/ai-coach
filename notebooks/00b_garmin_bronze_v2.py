# Databricks notebook source

# MAGIC %md
# MAGIC # 00b — Garmin Bronze (v2, reliable auth)
# MAGIC
# MAGIC Replaces the original `Garmin Data Ingest.ipynb` which uses raw HTTP form login
# MAGIC that Garmin's SSO breaks regularly.
# MAGIC
# MAGIC This version uses the `garminconnect` pip package which handles Garmin's
# MAGIC OAuth/SSO flow correctly and is actively maintained.
# MAGIC
# MAGIC **Writes to:**
# MAGIC - `ai_coach.bronze.garmin_activities_raw`
# MAGIC - `ai_coach.bronze.garmin_daily_raw`
# MAGIC - `ai_coach.bronze.garmin_activity_details_raw`
# MAGIC
# MAGIC **Secrets required:** scope `garmin` with keys `username` and `password`

# COMMAND ----------

# MAGIC %pip install garminconnect -q

# COMMAND ----------

# MAGIC %restart_python

# COMMAND ----------

CATALOG = "ai_coach"
DAYS_BACK = 365  # set to 3650 for a full historical backfill

print(f"Catalog: {CATALOG} | Days back: {DAYS_BACK}")

# COMMAND ----------

# MAGIC %md ## Authenticate

# COMMAND ----------

from garminconnect import Garmin
from datetime import datetime, timedelta, date
import json
import pandas as pd
from pyspark.sql import SparkSession
from pyspark.sql.types import *

spark = SparkSession.builder.getOrCreate()

username = dbutils.secrets.get(scope="garmin", key="username")
password = dbutils.secrets.get(scope="garmin", key="password")

client = Garmin(username, password)
client.login()
print("✅ Authenticated with Garmin Connect")

# COMMAND ----------

# MAGIC %md ## Fetch Activities

# COMMAND ----------

start_date = (datetime.now() - timedelta(days=DAYS_BACK)).date()
end_date = datetime.now().date()

print(f"Fetching activities from {start_date} to {end_date}...")
activities = client.get_activities_by_date(str(start_date), str(end_date))
print(f"✅ Found {len(activities)} activities")

# COMMAND ----------

def parse_garmin_activity(a: dict) -> dict:
    return {
        "activity_id":    a.get("activityId"),
        "activity_name":  a.get("activityName"),
        "activity_type":  a.get("activityType", {}).get("typeKey") if isinstance(a.get("activityType"), dict) else a.get("activityType"),
        "start_time":     pd.to_datetime(a.get("startTimeLocal")) if a.get("startTimeLocal") else None,
        "duration":       a.get("duration"),
        "distance":       a.get("distance"),
        "calories":       a.get("calories"),
        "avg_heart_rate": a.get("averageHR"),
        "max_heart_rate": a.get("maxHR"),
        "avg_speed":      a.get("averageSpeed"),
        "max_speed":      a.get("maxSpeed"),
        "elevation_gain": a.get("elevationGain"),
        "elevation_loss": a.get("elevationLoss"),
        "retrieved_at":   datetime.now(),
    }

activities_schema = StructType([
    StructField("activity_id",    LongType(),      True),
    StructField("activity_name",  StringType(),    True),
    StructField("activity_type",  StringType(),    True),
    StructField("start_time",     TimestampType(), True),
    StructField("duration",       LongType(),      True),
    StructField("distance",       DoubleType(),    True),
    StructField("calories",       LongType(),      True),
    StructField("avg_heart_rate", LongType(),      True),
    StructField("max_heart_rate", LongType(),      True),
    StructField("avg_speed",      DoubleType(),    True),
    StructField("max_speed",      DoubleType(),    True),
    StructField("elevation_gain", DoubleType(),    True),
    StructField("elevation_loss", DoubleType(),    True),
    StructField("retrieved_at",   TimestampType(), True),
])

parsed = [parse_garmin_activity(a) for a in activities]
df_acts = spark.createDataFrame(parsed, schema=activities_schema)

df_acts.createOrReplaceTempView("garmin_acts_new")
spark.sql(f"""
MERGE INTO {CATALOG}.bronze.garmin_activities_raw AS target
USING garmin_acts_new AS source
ON target.activity_id = source.activity_id
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *
""")

print(f"✅ {len(parsed)} activities upserted into bronze.garmin_activities_raw")

# COMMAND ----------

# MAGIC %md ## Fetch Daily Health Summaries

# COMMAND ----------

daily_schema = StructType([
    StructField("date",                   StringType(),    True),
    StructField("steps",                  LongType(),      True),
    StructField("calories_burned",        LongType(),      True),
    StructField("distance_meters",        DoubleType(),    True),
    StructField("active_minutes",         LongType(),      True),
    StructField("floors_climbed",         LongType(),      True),
    StructField("sleep_duration_seconds", LongType(),      True),
    StructField("resting_heart_rate",     LongType(),      True),
    StructField("max_heart_rate",         LongType(),      True),
    StructField("stress_score",           LongType(),      True),
    StructField("body_battery",           LongType(),      True),
    StructField("retrieved_at",           TimestampType(), True),
])

daily_rows = []
current = start_date
while current <= end_date:
    try:
        summary = client.get_stats(str(current))
        if summary:
            daily_rows.append({
                "date":                   str(current),
                "steps":                  summary.get("totalSteps"),
                "calories_burned":        summary.get("totalKilocalories"),
                "distance_meters":        summary.get("totalDistanceMeters"),
                "active_minutes":         summary.get("activeMinutes"),
                "floors_climbed":         summary.get("floorsClimbed"),
                "sleep_duration_seconds": summary.get("sleepingSeconds"),
                "resting_heart_rate":     summary.get("restingHeartRate"),
                "max_heart_rate":         summary.get("maxHeartRate"),
                "stress_score":           summary.get("maxStressScore"),
                "body_battery":           summary.get("bodyBatteryChargedUp"),
                "retrieved_at":           datetime.now(),
            })
    except Exception as e:
        pass  # some days may not have data
    current += timedelta(days=1)

if daily_rows:
    df_daily = spark.createDataFrame(daily_rows, schema=daily_schema)
    df_daily.createOrReplaceTempView("garmin_daily_new")
    spark.sql(f"""
    MERGE INTO {CATALOG}.bronze.garmin_daily_raw AS target
    USING garmin_daily_new AS source
    ON target.date = source.date
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
    """)
    print(f"✅ {len(daily_rows)} daily summaries upserted into bronze.garmin_daily_raw")
else:
    print("⚠️  No daily summaries retrieved")

# COMMAND ----------

# MAGIC %md ## Verify

# COMMAND ----------

act_count  = spark.sql(f"SELECT COUNT(*) AS n FROM {CATALOG}.bronze.garmin_activities_raw").collect()[0].n
day_count  = spark.sql(f"SELECT COUNT(*) AS n FROM {CATALOG}.bronze.garmin_daily_raw").collect()[0].n
date_range = spark.sql(f"SELECT MIN(start_time), MAX(start_time) FROM {CATALOG}.bronze.garmin_activities_raw").collect()[0]

print(f"bronze.garmin_activities_raw : {act_count} rows | {date_range[0]} → {date_range[1]}")
print(f"bronze.garmin_daily_raw      : {day_count} rows")
print(f"\nNext: run notebook 02_bronze_to_silver → 03_silver_to_gold → 04_feature_refresh")
