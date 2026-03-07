# AI Coach — Evaluation Test Cases
# 25 test cases across 5 categories used by 08_eval_harness.py

TEST_CASES = [

    # ────────────────────────────────────────────────────────────
    # CATEGORY 1: Factual Retrieval (6 tests)
    # ────────────────────────────────────────────────────────────
    {
        "id": "T001",
        "category": "factual",
        "question": "What is my current FTP?",
        "required_tools": ["get_athlete_profile"],
        "expected_keywords": ["FTP", "W", "watt"],
        "rubric": "Response must state the athlete's FTP value in watts. Should provide context (e.g. W/kg if weight available). Must not guess — must call get_athlete_profile.",
        "weight": 1.0,
    },
    {
        "id": "T002",
        "category": "factual",
        "question": "What is my current weight?",
        "required_tools": ["get_athlete_profile"],
        "expected_keywords": ["kg"],
        "rubric": "Response must state the athlete's weight in kg. Must pull from athlete profile, not guess.",
        "weight": 1.0,
    },
    {
        "id": "T003",
        "category": "factual",
        "question": "What is my current CTL (fitness)?",
        "required_tools": ["get_training_load"],
        "expected_keywords": ["CTL", "fitness"],
        "rubric": "Response must state the current CTL value as a number. Should briefly explain what CTL means. Must call get_training_load.",
        "weight": 1.0,
    },
    {
        "id": "T004",
        "category": "factual",
        "question": "What is my current TSB (form)?",
        "required_tools": ["get_training_load"],
        "expected_keywords": ["TSB", "form"],
        "rubric": "Response must state the current TSB value and interpret what it means (fresh/tired/overreached). Must call get_training_load.",
        "weight": 1.0,
    },
    {
        "id": "T005",
        "category": "factual",
        "question": "When was my last ride?",
        "required_tools": ["get_recent_activities"],
        "expected_keywords": ["ride", "date"],
        "rubric": "Response must state the date of the most recent activity. Should mention basic details (duration or distance). Must call get_recent_activities.",
        "weight": 1.0,
    },
    {
        "id": "T006",
        "category": "factual",
        "question": "What is my goal event and when is it?",
        "required_tools": ["get_athlete_profile"],
        "expected_keywords": ["event", "date"],
        "rubric": "Response must state the goal event name and date. If multiple events exist, list them. Must call get_athlete_profile.",
        "weight": 1.0,
    },

    # ────────────────────────────────────────────────────────────
    # CATEGORY 2: Ride Analysis (5 tests)
    # ────────────────────────────────────────────────────────────
    {
        "id": "T007",
        "category": "analysis",
        "question": "Give me detailed feedback on my last ride.",
        "required_tools": ["analyze_last_ride"],
        "expected_keywords": ["power", "TSS", "zone"],
        "rubric": "Response must include: power metrics (avg or NP), TSS, zone distribution if available, and at least one specific piece of coaching feedback. Must not be generic. Must call analyze_last_ride.",
        "weight": 1.0,
    },
    {
        "id": "T008",
        "category": "analysis",
        "question": "Was my heart rate too high on my last ride? Check for aerobic decoupling.",
        "required_tools": ["analyze_last_ride"],
        "expected_keywords": ["HR", "heart rate", "drift", "decoupling"],
        "rubric": "Response must address HR drift/aerobic decoupling specifically. Should state the HR drift percentage if available and interpret it. Must not give a generic HR answer.",
        "weight": 1.0,
    },
    {
        "id": "T009",
        "category": "analysis",
        "question": "What zones did I spend most time in on my last ride?",
        "required_tools": ["analyze_last_ride"],
        "expected_keywords": ["Z1", "Z2", "zone", "%"],
        "rubric": "Response must reference specific zone percentages from the last ride. Should interpret whether the distribution is appropriate given training goals.",
        "weight": 1.0,
    },
    {
        "id": "T010",
        "category": "analysis",
        "question": "Am I getting faster on my Zwift rides? Show me the trend.",
        "required_tools": ["compare_route_performances"],
        "expected_keywords": ["Zwift", "power", "trend"],
        "rubric": "Response must call compare_route_performances with 'Zwift' keyword. Must show actual numbers (power or time trend) across multiple rides, not just describe the concept.",
        "weight": 1.0,
    },
    {
        "id": "T011",
        "category": "analysis",
        "question": "How hard was my last ride relative to my FTP?",
        "required_tools": ["analyze_last_ride"],
        "expected_keywords": ["intensity factor", "IF", "FTP", "%"],
        "rubric": "Response must state the intensity factor (IF) and relate it to FTP percentage. Should classify the effort (easy/moderate/hard/maximal) and give context for what that means physiologically.",
        "weight": 1.0,
    },

    # ────────────────────────────────────────────────────────────
    # CATEGORY 3: Workout Planning (6 tests)
    # ────────────────────────────────────────────────────────────
    {
        "id": "T012",
        "category": "planning",
        "question": "What should I do today for training?",
        "required_tools": ["suggest_todays_workout"],
        "expected_keywords": ["TSB", "workout", "duration", "power"],
        "rubric": "Response must call suggest_todays_workout. Must include: workout type, duration, target power/zone, and rationale tied to current TSB. Must not be generic — must reference actual form data.",
        "weight": 1.0,
    },
    {
        "id": "T013",
        "category": "planning",
        "question": "Generate a training plan for this week.",
        "required_tools": ["generate_weekly_plan"],
        "expected_keywords": ["Monday", "Tuesday", "Wednesday", "TSS"],
        "rubric": "Response must call generate_weekly_plan and present a day-by-day schedule with workout types and TSS targets. Must be specific to the athlete's current fitness and phase.",
        "weight": 1.0,
    },
    {
        "id": "T014",
        "category": "planning",
        "question": "My legs are wrecked and I'm exhausted. Should I train today?",
        "required_tools": ["get_training_load"],
        "expected_keywords": ["TSB", "recovery", "rest"],
        "rubric": "Response must check training load data first. If TSB is already very negative, must recommend rest or recovery only. Must not recommend hard training when athlete reports exhaustion AND data supports overreach.",
        "weight": 1.5,
    },
    {
        "id": "T015",
        "category": "planning",
        "question": "I'm feeling amazing and my TSB is very high. What's the best workout to do?",
        "required_tools": ["suggest_todays_workout"],
        "expected_keywords": ["fresh", "quality", "power", "VO2", "interval"],
        "rubric": "Response must recognize high TSB as an opportunity for quality work. Must recommend a specific high-quality session (VO2max, sprint, race simulation) rather than another easy ride.",
        "weight": 1.0,
    },
    {
        "id": "T016",
        "category": "planning",
        "question": "I'm racing in 5 days. How should I structure my training this week?",
        "required_tools": ["generate_weekly_plan"],
        "expected_keywords": ["taper", "rest", "activation", "easy", "race"],
        "rubric": "Response must recognize pre-race context (≤7 days to race). Must recommend reduced volume, maintenance of intensity, and proper pre-race activation. Must not recommend heavy training load.",
        "weight": 1.5,
    },
    {
        "id": "T017",
        "category": "planning",
        "question": "I've been sick for a week and just got back on the bike. What should my comeback look like?",
        "required_tools": ["get_training_load", "get_fitness_snapshot"],
        "expected_keywords": ["recovery", "easy", "gradual", "TSB", "CTL"],
        "rubric": "Response must check current fitness metrics and acknowledge likely fitness loss. Must recommend gradual comeback starting with easy sessions. Must not prescribe intensity in first comeback week.",
        "weight": 1.5,
    },

    # ────────────────────────────────────────────────────────────
    # CATEGORY 4: Trend Analysis (4 tests)
    # ────────────────────────────────────────────────────────────
    {
        "id": "T018",
        "category": "trend",
        "question": "Has my fitness improved over the last 8 weeks?",
        "required_tools": ["get_weekly_summary"],
        "expected_keywords": ["CTL", "weeks", "trend"],
        "rubric": "Response must look at multi-week CTL data and quantify the change. Must state whether fitness is trending up, down, or flat with specific numbers. Must not give a vague answer.",
        "weight": 1.0,
    },
    {
        "id": "T019",
        "category": "trend",
        "question": "Is my peak power improving? Show me the trend.",
        "required_tools": ["get_power_curve_trend"],
        "expected_keywords": ["power", "improving", "declining", "30d", "90d"],
        "rubric": "Response must call get_power_curve_trend. Must cite specific peak power numbers at one or more durations and state the direction of change. Must not just list current power curve values.",
        "weight": 1.0,
    },
    {
        "id": "T020",
        "category": "trend",
        "question": "Am I training in the right zones? Do I have a training imbalance?",
        "required_tools": ["detect_training_imbalance"],
        "expected_keywords": ["Z2", "zone", "%", "recommendation"],
        "rubric": "Response must call detect_training_imbalance. Must state the actual zone distribution percentages and flag any imbalances (too much grey zone, not enough Z2, missing intensity, etc.). Must end with actionable recommendation.",
        "weight": 1.0,
    },
    {
        "id": "T021",
        "category": "trend",
        "question": "How consistent has my training been? Am I hitting my planned hours?",
        "required_tools": ["get_weekly_summary"],
        "expected_keywords": ["hours", "week", "compliance", "consistency"],
        "rubric": "Response must look at weekly data and comment on consistency of training volume. Should compare actual hours/TSS to available_hours or typical pattern. Must provide specific numbers.",
        "weight": 1.0,
    },

    # ────────────────────────────────────────────────────────────
    # CATEGORY 5: Edge / Stress Cases (4 tests)
    # ────────────────────────────────────────────────────────────
    {
        "id": "T022",
        "category": "edge_case",
        "question": "Push me hard today. I want a brutal workout.",
        "required_tools": ["get_training_load"],
        "expected_keywords": ["TSB", "form", "recovery"],
        "rubric": "CRITICAL: If TSB < -30, response MUST refuse to prescribe hard training and recommend recovery instead — regardless of athlete request. If TSB is suitable, can prescribe hard session. Must never blindly comply with intensity request when data shows overreach.",
        "weight": 2.0,
    },
    {
        "id": "T023",
        "category": "edge_case",
        "question": "I have 0 hours available this week. What's my plan?",
        "required_tools": ["get_training_load"],
        "expected_keywords": ["rest", "recovery", "zero", "maintenance"],
        "rubric": "Response must gracefully handle zero available hours. Should recommend full rest this week with maintenance mindset. Must not try to squeeze in training that isn't possible. Should note how to return next week.",
        "weight": 1.0,
    },
    {
        "id": "T024",
        "category": "edge_case",
        "question": "What's my power curve for last Tuesday's ride specifically?",
        "required_tools": ["get_recent_activities", "analyze_activity"],
        "expected_keywords": ["activity", "ride", "power"],
        "rubric": "Response must first call get_recent_activities to find Tuesday's activity_id, then call analyze_activity with that ID. Must handle the case gracefully if no ride on Tuesday (say so clearly). Must not use generic analyze_last_ride when a specific date is requested.",
        "weight": 1.5,
    },
    {
        "id": "T025",
        "category": "edge_case",
        "question": "My TSB is +20 so I feel great, but I slept 4 hours and my resting HR is elevated. Should I train hard?",
        "required_tools": ["get_fitness_snapshot"],
        "expected_keywords": ["sleep", "resting HR", "recovery", "caution"],
        "rubric": "Response must recognize the conflicting signals: good TSB but poor recovery indicators. Must NOT simply say 'yes, train hard because TSB is good'. Must weigh sleep and resting HR signals and recommend moderated training or rest.",
        "weight": 2.0,
    },
]


# ── Category helper ──────────────────────────────────────────────────────────

CATEGORIES = ["factual", "analysis", "planning", "trend", "edge_case"]

def get_by_category(category: str) -> list[dict]:
    return [t for t in TEST_CASES if t["category"] == category]

def get_by_id(test_id: str) -> dict | None:
    for t in TEST_CASES:
        if t["id"] == test_id:
            return t
    return None


if __name__ == "__main__":
    print(f"Total test cases: {len(TEST_CASES)}")
    for cat in CATEGORIES:
        cases = get_by_category(cat)
        total_weight = sum(t["weight"] for t in cases)
        print(f"  {cat:12}: {len(cases)} cases, {total_weight:.1f} total weight")
