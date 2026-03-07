"""
Activities router — paginated ride log.
GET /api/activities          → paginated activity list
GET /api/activities/{id}     → single activity detail
"""
from fastapi import APIRouter, Query
from db.client import query, query_one, CATALOG, ATHLETE_ID

router = APIRouter(prefix="/api/activities")


@router.get("")
def list_activities(page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100)):
    offset = (page - 1) * per_page
    rows = query(f"""
        SELECT
            activity_id, activity_date, activity_name, sport_type,
            distance_km, duration_min, elevation_m, avg_power_w, np_w,
            avg_hr, tss, intensity_factor
        FROM {CATALOG}.silver.activities
        WHERE athlete_id = '{ATHLETE_ID}'
        ORDER BY activity_date DESC
        LIMIT {per_page} OFFSET {offset}
    """)

    total = query_one(f"""
        SELECT COUNT(*) AS cnt
        FROM {CATALOG}.silver.activities
        WHERE athlete_id = '{ATHLETE_ID}'
    """)

    return {
        "activities": rows,
        "page": page,
        "per_page": per_page,
        "total": total["cnt"] if total else 0,
    }


@router.get("/{activity_id}")
def get_activity(activity_id: str):
    """Return full detail for a single activity including zone breakdown."""
    activity = query_one(f"""
        SELECT *
        FROM {CATALOG}.silver.activities
        WHERE athlete_id = '{ATHLETE_ID}' AND activity_id = '{activity_id}'
        LIMIT 1
    """)

    zones = query(f"""
        SELECT zone, seconds_in_zone, ROUND(seconds_in_zone / 60.0, 1) AS minutes_in_zone
        FROM {CATALOG}.gold.zone_distribution
        WHERE athlete_id = '{ATHLETE_ID}' AND activity_id = '{activity_id}'
        ORDER BY zone ASC
    """)

    return {
        "activity": activity,
        "zone_distribution": zones,
    }
