# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Strava → Bronze
# MAGIC
# MAGIC Enhanced Strava ETL that pulls ALL activities (not just one) and writes to bronze tables.
# MAGIC
# MAGIC **Writes to:**
# MAGIC - `ai_coach.bronze.strava_activities_raw` — activity list with metadata
# MAGIC - `ai_coach.bronze.strava_streams_raw` — per-second time series (power, HR, cadence, GPS)
# MAGIC - `ai_coach.bronze.strava_athlete_raw` — athlete profile (FTP, weight)
# MAGIC
# MAGIC **Secrets required:** scope `strava` with keys `client_id`, `client_secret`, `refresh_token`

# COMMAND ----------

# MAGIC %md ## Configuration

# COMMAND ----------

# DBTITLE 1,Pipeline Configuration: Full Backfill
CATALOG = "ai_coach"

# Set DAYS_BACK to 3650 for a full historical backfill
DAYS_BACK = 3650

# Fetch streams for rides with power data
FETCH_STREAMS = True

# Stream types to fetch
STREAM_KEYS = "time,latlng,distance,altitude,heartrate,watts,cadence,velocity_smooth,grade_smooth,moving,temp"

print(f"Catalog: {CATALOG}")
print(f"Days back: {DAYS_BACK}")
print(f"Fetch streams: {FETCH_STREAMS}")

# COMMAND ----------

# DBTITLE 1,Check Strava secret keys
# Check Strava secret keys in Databricks
secret_scope = "strava"
secret_keys = ["client_id", "client_secret", "refresh_token"]

for key in secret_keys:
    try:
        value = dbutils.secrets.get(scope=secret_scope, key=key)
        print(f"✅ Secret '{key}' exists and is length {len(value)}")
    except Exception as e:
        print(f"❌ Secret '{key}' is missing or not accessible: {e}")

# COMMAND ----------

# MAGIC %md ## Strava Client

# COMMAND ----------

import requests
import json
import time
import pandas as pd
from datetime import datetime, timedelta
from pyspark.sql import SparkSession
from pyspark.sql.types import *
from pyspark.sql.functions import lit
import logging

spark = SparkSession.builder.getOrCreate()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StravaClient:
    def __init__(self):
        self.access_token = None
        self.token_expires_at = 0
        self.athlete_id = None

    def _refresh_access_token(self):
        if self.access_token and self.token_expires_at > time.time():
            return True

        client_id = dbutils.secrets.get(scope="strava", key="client_id")
        client_secret = dbutils.secrets.get(scope="strava", key="client_secret")
        refresh_token = dbutils.secrets.get(scope="strava", key="refresh_token")

        resp = requests.post("https://www.strava.com/oauth/token", data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        })
        resp.raise_for_status()
        tokens = resp.json()
        self.access_token = tokens["access_token"]
        self.token_expires_at = tokens["expires_at"]
        print(f"✅ Token refreshed — expires {datetime.fromtimestamp(self.token_expires_at)}")
        return True

    def _headers(self):
        self._refresh_access_token()
        return {"Authorization": f"Bearer {self.access_token}"}

    def get_athlete(self):
        resp = requests.get("https://www.strava.com/api/v3/athlete", headers=self._headers())
        resp.raise_for_status()
        data = resp.json()
        self.athlete_id = data.get("id")
        return data

    def get_activities(self, after_ts: int, per_page: int = 100):
        """Paginate through all activities after a given unix timestamp."""
        activities = []
        page = 1
        while True:
            resp = requests.get(
                "https://www.strava.com/api/v3/athlete/activities",
                headers=self._headers(),
                params={"after": after_ts, "per_page": per_page, "page": page}
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            activities.extend(batch)
            print(f"  Page {page}: {len(batch)} activities (total so far: {len(activities)})")
            if len(batch) < per_page:
                break
            page += 1
            time.sleep(0.5)  # respect rate limits
        return activities

    def get_streams(self, activity_id: int):
        """Fetch time-series streams for one activity."""
        resp = requests.get(
            f"https://www.strava.com/api/v3/activities/{activity_id}/streams",
            headers=self._headers(),
            params={"keys": STREAM_KEYS, "key_by_type": "true"}
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

# COMMAND ----------

# MAGIC %md ## Diagnostics — Token Scope Check
# MAGIC
# MAGIC Run this cell to confirm which OAuth scopes your current refresh_token has.
# MAGIC If `activity:read_all` is missing, follow the re-authorization URL printed below.

# COMMAND ----------

# DBTITLE 1,Diagnose token scope + activities permission
import requests as _req

_client_id = dbutils.secrets.get(scope="strava", key="client_id")
_client_secret = dbutils.secrets.get(scope="strava", key="client_secret")
_refresh_token = dbutils.secrets.get(scope="strava", key="refresh_token")

# Refresh and inspect the full token response
_resp = _req.post("https://www.strava.com/oauth/token", data={
    "client_id": _client_id,
    "client_secret": _client_secret,
    "refresh_token": _refresh_token,
    "grant_type": "refresh_token",
})

print(f"Token refresh status: {_resp.status_code}")
_tokens = _resp.json()
_access_token = _tokens.get("access_token")

# Strava doesn't return scope in the refresh response, but we can probe directly
_test = _req.get(
    "https://www.strava.com/api/v3/athlete/activities",
    headers={"Authorization": f"Bearer {_access_token}"},
    params={"per_page": 1, "page": 1}
)

print(f"\nActivities endpoint status: {_test.status_code}")
if _test.status_code == 200:
    print("✅ Token has activity:read_all scope — activities endpoint works")
    print(f"   Response: {len(_test.json())} activity returned")
elif _test.status_code == 401:
    print("❌ 401 Unauthorized on activities — token is missing activity:read_all scope")
    print(f"   Error body: {_test.text}")
    print()
    print("=" * 70)
    print("FIX: Re-authorize your Strava app with the correct scopes.")
    print("1. Open this URL in your browser (replace YOUR_CLIENT_ID):")
    print()
    print(f"   https://www.strava.com/oauth/authorize"
          f"?client_id={_client_id}"
          f"&redirect_uri=http://localhost"
          f"&response_type=code"
          f"&scope=read,activity:read_all")
    print()
    print("2. Authorize the app — Strava redirects to:")
    print("   http://localhost?state=&code=XXXXXXXX&scope=read,activity:read_all")
    print()
    print("3. Copy the 'code' value from the URL, then run this exchange:")
    print("""
   import requests
   r = requests.post("https://www.strava.com/oauth/token", data={
       "client_id":     "<YOUR_CLIENT_ID>",
       "client_secret": "<YOUR_CLIENT_SECRET>",
       "code":          "<CODE_FROM_URL>",
       "grant_type":    "authorization_code",
   })
   print(r.json()["refresh_token"])   # ← store this in Databricks secrets
""")
    print("4. Update the secret:")
    print("   databricks secrets put --scope strava --key refresh_token")
    print("=" * 70)
else:
    print(f"Unexpected status {_test.status_code}: {_test.text}")


# COMMAND ----------

# MAGIC %md ## Fetch & Write Athlete Profile

# COMMAND ----------

client = StravaClient()

print("Fetching athlete profile...")
athlete = client.get_athlete()

athlete_row = {
    "athlete_id": athlete.get("id"),
    "firstname":  athlete.get("firstname"),
    "lastname":   athlete.get("lastname"),
    "ftp":        athlete.get("ftp"),
    "weight_kg":  athlete.get("weight"),
    "country":    athlete.get("country"),
    "city":       athlete.get("city"),
    "sex":        athlete.get("sex"),
    "raw_json":   json.dumps(athlete),
    "retrieved_at": datetime.now(),
}

athlete_schema = StructType([
    StructField("athlete_id",   LongType(),   True),
    StructField("firstname",    StringType(), True),
    StructField("lastname",     StringType(), True),
    StructField("ftp",          IntegerType(),True),
    StructField("weight_kg",    DoubleType(), True),
    StructField("country",      StringType(), True),
    StructField("city",         StringType(), True),
    StructField("sex",          StringType(), True),
    StructField("raw_json",     StringType(), True),
    StructField("retrieved_at", TimestampType(), True),
])

df_athlete = spark.createDataFrame([athlete_row], schema=athlete_schema)
df_athlete.write.format("delta").mode("overwrite").option("mergeSchema", "true") \
    .saveAsTable(f"{CATALOG}.bronze.strava_athlete_raw")

print(f"✅ Athlete: {athlete.get('firstname')} {athlete.get('lastname')} | FTP: {athlete.get('ftp')}W | Weight: {athlete.get('weight')}kg")

# COMMAND ----------

# MAGIC %md ## Fetch & Write Activities

# COMMAND ----------

after_ts = int((datetime.now() - timedelta(days=DAYS_BACK)).timestamp())
print(f"Fetching activities since {datetime.fromtimestamp(after_ts).date()} ({DAYS_BACK} days back)...")

activities_raw = client.get_activities(after_ts)
print(f"\n📊 Total activities fetched: {len(activities_raw)}")

# COMMAND ----------

def parse_activity(a: dict, athlete_id: int) -> dict:
    """Flatten a Strava activity dict into a row for bronze."""
    latlng = a.get("start_latlng") or [None, None]
    return {
        "activity_id":        a.get("id"),
        "activity_name":      a.get("name"),
        "activity_type":      a.get("type") or a.get("sport_type"),
        "start_date":         pd.to_datetime(a.get("start_date")),
        "start_date_local":   pd.to_datetime(a.get("start_date_local")),
        "timezone":           a.get("timezone"),
        "duration_sec":       a.get("elapsed_time"),
        "distance_m":         a.get("distance"),
        "elevation_gain_m":   a.get("total_elevation_gain"),
        "avg_speed_ms":       a.get("average_speed"),
        "max_speed_ms":       a.get("max_speed"),
        "avg_heartrate":      a.get("average_heartrate"),
        "max_heartrate":      a.get("max_heartrate"),
        "avg_watts":          a.get("average_watts"),
        "max_watts":          a.get("max_watts"),
        "weighted_avg_watts": a.get("weighted_average_watts"),
        "avg_cadence":        a.get("average_cadence"),
        "calories":           a.get("calories"),
        "suffer_score":       a.get("suffer_score"),
        "kudos_count":        a.get("kudos_count"),
        "pr_count":           a.get("pr_count"),
        "gear_id":            a.get("gear_id"),
        "start_lat":          latlng[0] if len(latlng) > 0 else None,
        "start_lon":          latlng[1] if len(latlng) > 1 else None,
        "athlete_id":         athlete_id,
        "raw_json":           json.dumps(a),
        "retrieved_at":       datetime.now(),
    }

activities_schema = StructType([
    StructField("activity_id",        LongType(),    True),
    StructField("activity_name",      StringType(),  True),
    StructField("activity_type",      StringType(),  True),
    StructField("start_date",         TimestampType(),True),
    StructField("start_date_local",   TimestampType(),True),
    StructField("timezone",           StringType(),  True),
    StructField("duration_sec",       IntegerType(), True),
    StructField("distance_m",         DoubleType(),  True),
    StructField("elevation_gain_m",   DoubleType(),  True),
    StructField("avg_speed_ms",       DoubleType(),  True),
    StructField("max_speed_ms",       DoubleType(),  True),
    StructField("avg_heartrate",      DoubleType(),  True),
    StructField("max_heartrate",      DoubleType(),  True),
    StructField("avg_watts",          DoubleType(),  True),
    StructField("max_watts",          IntegerType(), True),
    StructField("weighted_avg_watts", IntegerType(), True),
    StructField("avg_cadence",        DoubleType(),  True),
    StructField("calories",           IntegerType(), True),
    StructField("suffer_score",       IntegerType(), True),
    StructField("kudos_count",        IntegerType(), True),
    StructField("pr_count",           IntegerType(), True),
    StructField("gear_id",            StringType(),  True),
    StructField("start_lat",          DoubleType(),  True),
    StructField("start_lon",          DoubleType(),  True),
    StructField("athlete_id",         LongType(),    True),
    StructField("raw_json",           StringType(),  True),
    StructField("retrieved_at",       TimestampType(),True),
])

parsed = [parse_activity(a, client.athlete_id) for a in activities_raw]
df_activities = spark.createDataFrame(parsed, schema=activities_schema)

# Upsert: merge on activity_id to avoid duplicates on re-runs
df_activities.createOrReplaceTempView("strava_activities_new")
spark.sql(f"""
MERGE INTO {CATALOG}.bronze.strava_activities_raw AS target
USING strava_activities_new AS source
ON target.activity_id = source.activity_id
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *
""")

print(f"✅ Upserted {len(parsed)} activities into bronze.strava_activities_raw")

# COMMAND ----------

# MAGIC %md ## Fetch & Write Activity Streams (Power / HR time series)

# COMMAND ----------

if FETCH_STREAMS:
    # Only fetch streams for ride types with potential power data, skip already-fetched
    ride_types = {"Ride", "VirtualRide", "MountainBikeRide", "GravelRide", "EBikeRide"}
    ride_activities = [a for a in activities_raw if (a.get("type") or a.get("sport_type")) in ride_types]

    # Check which activity_ids already have streams
    try:
        existing_ids = set(
            row.activity_id for row in
            spark.sql(f"SELECT DISTINCT activity_id FROM {CATALOG}.bronze.strava_streams_raw").collect()
        )
    except Exception:
        existing_ids = set()

    to_fetch = [a for a in ride_activities if a.get("id") not in existing_ids]
    print(f"Rides total: {len(ride_activities)} | Already in bronze: {len(existing_ids)} | To fetch: {len(to_fetch)}")

    streams_schema = StructType([
        StructField("activity_id",   LongType(),    False),
        StructField("time_offset",   IntegerType(), True),
        StructField("distance_m",    DoubleType(),  True),
        StructField("altitude_m",    DoubleType(),  True),
        StructField("lat",           DoubleType(),  True),
        StructField("lon",           DoubleType(),  True),
        StructField("heartrate",     IntegerType(), True),
        StructField("watts",         IntegerType(), True),
        StructField("cadence",       IntegerType(), True),
        StructField("velocity_ms",   DoubleType(),  True),
        StructField("grade_pct",     DoubleType(),  True),
        StructField("temperature_c", DoubleType(),  True),
        StructField("moving",        BooleanType(), True),
        StructField("retrieved_at",  TimestampType(), True),
    ])

    BATCH_SIZE = 50  # write in batches to avoid memory issues
    total_written = 0

    for i, activity in enumerate(to_fetch):
        act_id = activity["id"]
        try:
            streams = client.get_streams(act_id)
            if not streams:
                continue

            n = len(streams.get("time", {}).get("data", []))
            if n == 0:
                continue

            def stream_vals(key, default=None):
                d = streams.get(key, {}).get("data", [])
                return d if d else [default] * n

            latlng = streams.get("latlng", {}).get("data", [])
            lats = [p[0] if p else None for p in latlng] or [None] * n
            lons = [p[1] if p else None for p in latlng] or [None] * n

            rows = [{
                "activity_id":   act_id,
                "time_offset":   stream_vals("time")[j],
                "distance_m":    stream_vals("distance")[j] if stream_vals("distance")[j] else None,
                "altitude_m":    stream_vals("altitude")[j] if stream_vals("altitude")[j] else None,
                "lat":           lats[j],
                "lon":           lons[j],
                "heartrate":     stream_vals("heartrate")[j],
                "watts":         stream_vals("watts")[j],
                "cadence":       stream_vals("cadence")[j],
                "velocity_ms":   stream_vals("velocity_smooth")[j],
                "grade_pct":     stream_vals("grade_smooth")[j],
                "temperature_c": stream_vals("temp")[j],
                "moving":        stream_vals("moving")[j],
                "retrieved_at":  datetime.now(),
            } for j in range(n)]

            df_s = spark.createDataFrame(rows, schema=streams_schema)
            df_s.write.format("delta").mode("append").saveAsTable(f"{CATALOG}.bronze.strava_streams_raw")
            total_written += n

            if (i + 1) % 10 == 0:
                print(f"  {i+1}/{len(to_fetch)} activities processed ({total_written} stream rows written)")

            time.sleep(0.3)

        except Exception as e:
            logger.warning(f"Failed to fetch streams for activity {act_id}: {e}")
            continue

    print(f"\n✅ Streams complete: {total_written} rows written for {len(to_fetch)} activities")
else:
    print("Stream fetching skipped (FETCH_STREAMS=False)")

# COMMAND ----------

# MAGIC %md ## Summary

# COMMAND ----------

act_count = spark.sql(f"SELECT COUNT(*) AS n FROM {CATALOG}.bronze.strava_activities_raw").collect()[0].n
stream_count = spark.sql(f"SELECT COUNT(*) AS n FROM {CATALOG}.bronze.strava_streams_raw").collect()[0].n

print(f"bronze.strava_activities_raw : {act_count:,} rows")
print(f"bronze.strava_streams_raw    : {stream_count:,} rows")
print(f"bronze.strava_athlete_raw    : 1 row")
