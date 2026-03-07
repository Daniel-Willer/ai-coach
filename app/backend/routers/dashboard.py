"""
Dashboard router — fitness timeseries, daily snapshot, weekly summary.
GET /api/dashboard/fitness  → CTL/ATL/TSB history (last 90 days)
GET /api/dashboard/today    → current fitness snapshot
GET /api/dashboard/weekly   → this week's stats
"""
from fastapi import APIRouter
from db.client import query, query_one, CATALOG, ATHLETE_ID

router = APIRouter(prefix="/api/dashboard")


@router.get("/fitness")
def get_fitness(days: int = 90):
    """CTL/ATL/TSB timeseries for chart rendering."""
    rows = query(f"""
        SELECT date, ctl, atl, tsb, is_actual, source
        FROM {CATALOG}.gold.fitness_trajectory
        WHERE athlete_id = '{ATHLETE_ID}'
          AND date >= CURRENT_DATE - INTERVAL {days} DAYS
        ORDER BY date ASC
    """)
    return {"data": rows}


@router.get("/today")
def get_today():
    """Current fitness snapshot — latest CTL/ATL/TSB."""
    snapshot = query_one(f"""
        SELECT date, ctl, atl, tsb
        FROM {CATALOG}.gold.daily_training_load
        WHERE athlete_id = '{ATHLETE_ID}'
        ORDER BY date DESC
        LIMIT 1
    """)

    last_ride = query_one(f"""
        SELECT activity_date, activity_name, distance_km, duration_min, tss, avg_power_w, np_w
        FROM {CATALOG}.silver.activities
        WHERE athlete_id = '{ATHLETE_ID}'
        ORDER BY activity_date DESC
        LIMIT 1
    """)

    profile = query_one(f"""
        SELECT ftp_w, weight_kg, goal_event_name, goal_event_date
        FROM {CATALOG}.silver.athletes
        WHERE athlete_id = '{ATHLETE_ID}'
        LIMIT 1
    """)

    return {
        "fitness": snapshot,
        "last_ride": last_ride,
        "profile": profile,
    }


@router.get("/weekly")
def get_weekly():
    """This week's training summary — TSS, hours, rides."""
    stats = query_one(f"""
        SELECT
            COUNT(*) AS rides,
            ROUND(SUM(duration_min) / 60.0, 1) AS hours,
            ROUND(SUM(tss), 0) AS weekly_tss,
            ROUND(AVG(avg_power_w), 0) AS avg_power_w,
            ROUND(SUM(distance_km), 1) AS distance_km
        FROM {CATALOG}.silver.activities
        WHERE athlete_id = '{ATHLETE_ID}'
          AND activity_date >= DATE_TRUNC('week', CURRENT_DATE)
    """)

    zone_dist = query(f"""
        SELECT zone, ROUND(SUM(seconds_in_zone) / 60.0, 1) AS minutes
        FROM {CATALOG}.gold.zone_distribution
        WHERE athlete_id = '{ATHLETE_ID}'
          AND activity_date >= DATE_TRUNC('week', CURRENT_DATE)
        GROUP BY zone
        ORDER BY zone ASC
    """)

    return {
        "stats": stats,
        "zone_distribution": zone_dist,
    }
