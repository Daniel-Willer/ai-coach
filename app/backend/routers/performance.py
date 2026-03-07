"""
Performance router — power curve, personal records, trend analysis.
GET /api/performance/power-curve   → current power curve (best efforts)
GET /api/performance/power-trend   → power curve trend over 30/60/90 days
GET /api/performance/records       → personal records
GET /api/performance/zones         → historical zone distribution trends
"""
from fastapi import APIRouter, Query
from db.client import query, CATALOG, ATHLETE_ID

router = APIRouter(prefix="/api/performance")


@router.get("/power-curve")
def get_power_curve(days: int = Query(90, ge=7, le=365)):
    """Best power at standard durations over the last N days."""
    rows = query(f"""
        SELECT duration_label, duration_sec,
               MAX(power_watts) AS power_watts,
               ROUND(MAX(power_watts) / a.weight_kg, 2) AS wkg
        FROM {CATALOG}.gold.fitness_metrics fm
        CROSS JOIN (
            SELECT weight_kg FROM {CATALOG}.silver.athletes
            WHERE athlete_id = '{ATHLETE_ID}' LIMIT 1
        ) a
        WHERE fm.athlete_id = '{ATHLETE_ID}'
          AND fm.activity_date >= CURRENT_DATE - INTERVAL {days} DAYS
        GROUP BY duration_label, duration_sec, a.weight_kg
        ORDER BY duration_sec ASC
    """)
    return {"power_curve": rows, "days": days}


@router.get("/power-trend")
def get_power_trend():
    """Power curve values for 30/60/90 day windows — shows improvement or decline."""
    windows = {"30d": 30, "60d": 60, "90d": 90}
    result = {}
    for label, days in windows.items():
        rows = query(f"""
            SELECT duration_label, duration_sec, MAX(power_watts) AS power_watts
            FROM {CATALOG}.gold.fitness_metrics
            WHERE athlete_id = '{ATHLETE_ID}'
              AND activity_date >= CURRENT_DATE - INTERVAL {days} DAYS
            GROUP BY duration_label, duration_sec
            ORDER BY duration_sec ASC
        """)
        result[label] = rows
    return {"trend": result}


@router.get("/records")
def get_records():
    """All-time and recent personal records."""
    all_time = query(f"""
        SELECT duration_label, duration_sec, power_watts, wkg, activity_id, recorded_at
        FROM {CATALOG}.coach.personal_records
        WHERE athlete_id = '{ATHLETE_ID}' AND is_alltime_pr = true
        ORDER BY duration_sec ASC
    """)

    recent = query(f"""
        SELECT duration_label, duration_sec, power_watts, wkg, activity_id, recorded_at
        FROM {CATALOG}.coach.personal_records
        WHERE athlete_id = '{ATHLETE_ID}'
          AND recorded_at >= CURRENT_DATE - INTERVAL 90 DAYS
        ORDER BY recorded_at DESC
        LIMIT 20
    """)

    return {"all_time": all_time, "recent_90d": recent}


@router.get("/zones")
def get_zone_trend(weeks: int = Query(8, ge=1, le=52)):
    """Weekly zone distribution trend — shows if training polarization is shifting."""
    rows = query(f"""
        SELECT
            DATE_TRUNC('week', activity_date) AS week_start,
            zone,
            ROUND(SUM(seconds_in_zone) / 60.0, 1) AS minutes
        FROM {CATALOG}.gold.zone_distribution
        WHERE athlete_id = '{ATHLETE_ID}'
          AND activity_date >= CURRENT_DATE - INTERVAL {weeks * 7} DAYS
        GROUP BY 1, 2
        ORDER BY 1 ASC, 2 ASC
    """)
    return {"zone_trend": rows}
