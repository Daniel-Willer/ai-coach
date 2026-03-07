"""
Insights router — proactive coach insights.
GET   /api/insights           → list insights (unread first)
PATCH /api/insights/{id}/read → mark as read
DELETE /api/insights/{id}     → dismiss
"""
from fastapi import APIRouter
from db.client import query, execute, CATALOG, ATHLETE_ID

router = APIRouter(prefix="/api/insights")


@router.get("")
def list_insights(include_read: bool = False):
    read_filter = "" if include_read else "AND is_read = false"
    rows = query(f"""
        SELECT insight_id, category, severity, title, body, action_prompt, is_read, created_at
        FROM {CATALOG}.coach.insights
        WHERE athlete_id = '{ATHLETE_ID}'
          {read_filter}
        ORDER BY
            CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END ASC,
            created_at DESC
        LIMIT 50
    """)
    return {"insights": rows}


@router.patch("/{insight_id}/read")
def mark_read(insight_id: str):
    execute(f"""
        UPDATE {CATALOG}.coach.insights
        SET is_read = true
        WHERE insight_id = '{insight_id}' AND athlete_id = '{ATHLETE_ID}'
    """)
    return {"ok": True}


@router.delete("/{insight_id}")
def dismiss_insight(insight_id: str):
    execute(f"""
        DELETE FROM {CATALOG}.coach.insights
        WHERE insight_id = '{insight_id}' AND athlete_id = '{ATHLETE_ID}'
    """)
    return {"ok": True}
