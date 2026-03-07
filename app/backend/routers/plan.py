"""
Training plan router.
GET    /api/plan              → current plan + upcoming workouts
GET    /api/plan/today        → today's prescribed workout
POST   /api/plan/generate     → trigger weekly plan generation via agent tool
PATCH  /api/plan/workout/{id} → mark workout complete/skip
"""
import json
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel
from db.client import query, query_one, execute, CATALOG, ATHLETE_ID
from tools.planning import generate_weekly_plan, suggest_todays_workout

router = APIRouter(prefix="/api/plan")


class WorkoutStatusUpdate(BaseModel):
    status: str  # "completed" | "skipped"
    actual_tss: Optional[float] = None
    notes: Optional[str] = None


@router.get("")
def get_plan():
    """Return active training plan with upcoming workouts."""
    plan = query_one(f"""
        SELECT plan_id, phase, start_date, end_date, goal_event_name, weekly_tss_target
        FROM {CATALOG}.coach.training_plans
        WHERE athlete_id = '{ATHLETE_ID}' AND end_date >= CURRENT_DATE
        ORDER BY start_date DESC
        LIMIT 1
    """)

    if not plan:
        return {"plan": None, "workouts": []}

    workouts = query(f"""
        SELECT workout_id, planned_date, workout_type, duration_min, target_tss,
               description, status, actual_tss
        FROM {CATALOG}.coach.planned_workouts
        WHERE plan_id = '{plan["plan_id"]}'
          AND planned_date >= CURRENT_DATE
        ORDER BY planned_date ASC
        LIMIT 14
    """)

    return {"plan": plan, "workouts": workouts}


@router.get("/today")
def get_today_workout():
    """Return today's prescribed workout or generate a suggestion."""
    # Check saved plan first
    saved = query_one(f"""
        SELECT pw.workout_id, pw.workout_type, pw.duration_min, pw.target_tss, pw.description
        FROM {CATALOG}.coach.planned_workouts pw
        JOIN {CATALOG}.coach.training_plans tp ON pw.plan_id = tp.plan_id
        WHERE tp.athlete_id = '{ATHLETE_ID}'
          AND pw.planned_date = CURRENT_DATE
          AND pw.status = 'pending'
        LIMIT 1
    """)

    if saved:
        return {"source": "plan", "workout": saved}

    # Fall back to dynamic suggestion
    suggestion_json = suggest_todays_workout.invoke({"athlete_id": ATHLETE_ID})
    suggestion = json.loads(suggestion_json) if isinstance(suggestion_json, str) else suggestion_json
    return {"source": "suggestion", "workout": suggestion}


@router.post("/generate")
def generate_plan():
    """Generate a new weekly plan and persist it."""
    plan_json = generate_weekly_plan.invoke({"athlete_id": ATHLETE_ID})
    plan = json.loads(plan_json) if isinstance(plan_json, str) else plan_json

    if "error" in plan:
        return {"ok": False, "error": plan["error"]}

    # Persist plan
    plan_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    days = plan.get("days", [])

    execute(f"""
        INSERT INTO {CATALOG}.coach.training_plans
        (plan_id, athlete_id, phase, start_date, end_date, goal_event_name, weekly_tss_target, created_at)
        VALUES (
            '{plan_id}', '{ATHLETE_ID}',
            '{plan.get("phase", "base")}',
            '{plan.get("start_date", now[:10])}',
            '{plan.get("end_date", now[:10])}',
            '{plan.get("goal_event_name", "")}',
            {plan.get("weekly_tss_target", 0)},
            '{now}'
        )
    """)

    for day in days:
        wid = str(uuid.uuid4())
        desc = str(day.get("description", "")).replace("'", "''")
        execute(f"""
            INSERT INTO {CATALOG}.coach.planned_workouts
            (workout_id, plan_id, athlete_id, planned_date, workout_type,
             duration_min, target_tss, description, status)
            VALUES (
                '{wid}', '{plan_id}', '{ATHLETE_ID}',
                '{day["date"]}', '{day.get("workout_type", "rest")}',
                {day.get("duration_min", 0)}, {day.get("target_tss", 0)},
                '{desc}', 'pending'
            )
        """)

    return {"ok": True, "plan_id": plan_id, "plan": plan}


@router.patch("/workout/{workout_id}")
def update_workout(workout_id: str, body: WorkoutStatusUpdate):
    actual = f", actual_tss = {body.actual_tss}" if body.actual_tss is not None else ""
    notes = f", notes = '{body.notes.replace(chr(39), chr(39)*2)}'" if body.notes else ""
    execute(f"""
        UPDATE {CATALOG}.coach.planned_workouts
        SET status = '{body.status}'{actual}{notes}
        WHERE workout_id = '{workout_id}'
    """)
    return {"ok": True}
