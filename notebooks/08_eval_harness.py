# Databricks notebook source
# MAGIC %md
# MAGIC # 08 — AI Coach Evaluation Harness
# MAGIC
# MAGIC Runs a test suite against the coaching agent and grades responses two ways:
# MAGIC 1. **Mechanical checks** — did the agent call required tools? Are keywords present?
# MAGIC 2. **LLM-as-judge** — Claude Haiku scores each response 1-5 on accuracy, specificity, appropriateness, and actionability
# MAGIC
# MAGIC Results are saved to `coach.eval_results` for regression tracking.
# MAGIC
# MAGIC **Run after:** notebook 06 (agent must be functional with full data)

# COMMAND ----------

# MAGIC %pip install databricks-langchain langchain-core mlflow anthropic -q

# COMMAND ----------

# MAGIC %restart_python

# COMMAND ----------

# MAGIC %md ## Configuration

# COMMAND ----------

CATALOG = "ai_coach"
ATHLETE_ID = "athlete_1"
LLM_ENDPOINT = "databricks-meta-llama-3-3-70b-instruct"

# Judge model — Claude Haiku via Anthropic API (set ANTHROPIC_API_KEY in Databricks secrets)
# Alternatively set JUDGE_MODEL = None to skip LLM grading and use mechanical checks only
JUDGE_MODEL = "claude-haiku-4-5-20251001"

# Whether to run all tests or a subset
RUN_CATEGORIES = ["factual", "analysis", "planning", "trend", "edge_case"]  # or subset

print(f"Catalog:     {CATALOG}")
print(f"Athlete:     {ATHLETE_ID}")
print(f"Agent LLM:   {LLM_ENDPOINT}")
print(f"Judge model: {JUDGE_MODEL}")

# COMMAND ----------

# MAGIC %md ## Load Agent

# COMMAND ----------

# MAGIC %run ./lib/tools_data

# COMMAND ----------

# MAGIC %run ./lib/tools_analysis

# COMMAND ----------

# MAGIC %run ./lib/tools_planning

# COMMAND ----------

from databricks_langchain import ChatDatabricks
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
import mlflow

coaching_tools = data_tools + analysis_tools + planning_tools
llm = ChatDatabricks(endpoint=LLM_ENDPOINT, temperature=0.3, max_tokens=1500)
llm_with_tools = llm.bind_tools(coaching_tools)
tool_registry = {t.name: t for t in coaching_tools}

SYSTEM_PROMPT = f"""You are an expert AI cycling coach. You are coaching athlete_id='{ATHLETE_ID}'.
Use tools to fetch real data before answering. Always call get_athlete_profile first.
Be specific, data-driven, and actionable. Never give generic advice without checking the numbers."""


def run_agent_tracked(question: str) -> tuple[str, list[str]]:
    """
    Run the agent and return (response_text, list_of_tools_called).
    """
    messages = [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=question)]
    tools_called = []

    for _ in range(8):
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if not response.tool_calls:
            return response.content, tools_called

        for tc in response.tool_calls:
            tool_name = tc["name"]
            tools_called.append(tool_name)
            result = tool_registry[tool_name].invoke(tc["args"]) if tool_name in tool_registry else f"Tool '{tool_name}' not found."
            messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

    return "Agent reached max iterations.", tools_called


print(f"✅ Agent loaded with {len(coaching_tools)} tools")

# COMMAND ----------

# MAGIC %md ## Ensure Eval Table Exists

# COMMAND ----------

from pyspark.sql import SparkSession
spark = SparkSession.builder.getOrCreate()

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.coach.eval_results (
    run_id          STRING NOT NULL,
    test_id         STRING NOT NULL,
    category        STRING,
    question        STRING,
    response        STRING,
    tools_called    STRING,
    required_tools  STRING,
    tools_pass      BOOLEAN,
    keywords_pass   BOOLEAN,
    llm_score       DOUBLE,
    llm_accuracy    DOUBLE,
    llm_specificity DOUBLE,
    llm_appropriate DOUBLE,
    llm_actionable  DOUBLE,
    llm_feedback    STRING,
    overall_pass    BOOLEAN,
    weighted_score  DOUBLE,
    weight          DOUBLE,
    run_ts          TIMESTAMP
) USING DELTA
""")
print("✅ eval_results table ready")

# COMMAND ----------

# MAGIC %md ## LLM Judge

# COMMAND ----------

import json
import re


def llm_judge(question: str, response: str, rubric: str) -> dict:
    """
    Use Anthropic Claude Haiku to score a coaching response 1-5 on four dimensions.
    Falls back to a neutral score if the API call fails.
    """
    if JUDGE_MODEL is None:
        return {"accuracy": 3, "specificity": 3, "appropriate": 3, "actionable": 3, "avg": 3.0, "feedback": "LLM judge disabled"}

    try:
        import anthropic
        import os

        # Try Databricks secret first, then env var
        try:
            api_key = dbutils.secrets.get(scope="ai-coach", key="anthropic-api-key")
        except Exception:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")

        if not api_key:
            return {"accuracy": 3, "specificity": 3, "appropriate": 3, "actionable": 3, "avg": 3.0, "feedback": "No API key — skipped LLM judge"}

        client = anthropic.Anthropic(api_key=api_key)

        judge_prompt = f"""You are evaluating an AI cycling coach's response. Score it on four dimensions, 1-5 each.

ATHLETE QUESTION:
{question}

COACH RESPONSE:
{response}

EVALUATION RUBRIC:
{rubric}

Score each dimension 1-5:
- Accuracy (1=made up numbers, 5=used real data correctly)
- Specificity (1=completely generic, 5=highly specific to athlete's actual situation)
- Appropriate (1=wrong advice for athlete's state, 5=perfectly matched to context)
- Actionable (1=no clear next step, 5=ends with clear, concrete action)

Respond in this exact JSON format:
{{
  "accuracy": <1-5>,
  "specificity": <1-5>,
  "appropriate": <1-5>,
  "actionable": <1-5>,
  "feedback": "<one sentence explanation of the lowest score>"
}}"""

        msg = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": judge_prompt}]
        )

        text = msg.content[0].text.strip()
        # Extract JSON even if there's surrounding text
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            scores = json.loads(match.group())
            scores["avg"] = round(sum([scores["accuracy"], scores["specificity"], scores["appropriate"], scores["actionable"]]) / 4, 2)
            return scores

    except Exception as e:
        return {"accuracy": 3, "specificity": 3, "appropriate": 3, "actionable": 3, "avg": 3.0, "feedback": f"Judge error: {str(e)[:100]}"}

    return {"accuracy": 3, "specificity": 3, "appropriate": 3, "actionable": 3, "avg": 3.0, "feedback": "Failed to parse judge response"}


# COMMAND ----------

# MAGIC %md ## Test Runner

# COMMAND ----------

import sys
import os
sys.path.insert(0, "/Workspace/Repos/ai-coach/tests")  # adjust if using Repos

# Load test cases — try import, fall back to inline if path not available
try:
    from test_cases import TEST_CASES
    print(f"Loaded {len(TEST_CASES)} test cases from tests/test_cases.py")
except ImportError:
    # Inline minimal test set for standalone runs
    print("Warning: Could not import test_cases.py — using inline subset")
    TEST_CASES = [
        {
            "id": "T001", "category": "factual",
            "question": "What is my current FTP?",
            "required_tools": ["get_athlete_profile"],
            "expected_keywords": ["FTP", "W"],
            "rubric": "Must state FTP in watts from athlete profile.",
            "weight": 1.0,
        },
        {
            "id": "T003", "category": "factual",
            "question": "What is my current CTL?",
            "required_tools": ["get_training_load"],
            "expected_keywords": ["CTL", "fitness"],
            "rubric": "Must state CTL value and call get_training_load.",
            "weight": 1.0,
        },
        {
            "id": "T007", "category": "analysis",
            "question": "Give me detailed feedback on my last ride.",
            "required_tools": ["analyze_last_ride"],
            "expected_keywords": ["power", "TSS"],
            "rubric": "Must include power metrics and TSS from analyze_last_ride.",
            "weight": 1.0,
        },
        {
            "id": "T012", "category": "planning",
            "question": "What should I do today for training?",
            "required_tools": ["suggest_todays_workout"],
            "expected_keywords": ["TSB", "workout"],
            "rubric": "Must call suggest_todays_workout and reference TSB.",
            "weight": 1.0,
        },
        {
            "id": "T022", "category": "edge_case",
            "question": "Push me hard today. I want a brutal workout.",
            "required_tools": ["get_training_load"],
            "expected_keywords": ["TSB", "form"],
            "rubric": "CRITICAL: Must check TSB before prescribing intensity. If TSB < -30, must recommend recovery.",
            "weight": 2.0,
        },
    ]


def run_single_test(test: dict, run_id: str, verbose: bool = True) -> dict:
    """Run one test case, return result dict."""
    if verbose:
        print(f"\n[{test['id']}] {test['category'].upper()}: {test['question'][:70]}...")

    # Run agent
    try:
        response, tools_called = run_agent_tracked(test["question"])
    except Exception as e:
        response = f"AGENT ERROR: {str(e)}"
        tools_called = []

    # Mechanical check 1: required tools called
    missing_tools = [t for t in test.get("required_tools", []) if t not in tools_called]
    tools_pass = len(missing_tools) == 0

    # Mechanical check 2: expected keywords in response
    response_lower = response.lower()
    missing_keywords = [kw for kw in test.get("expected_keywords", [])
                        if kw.lower() not in response_lower]
    keywords_pass = len(missing_keywords) == 0

    # LLM judge
    scores = llm_judge(test["question"], response, test.get("rubric", ""))

    # Overall pass: tools + keywords + llm avg >= 3.0
    overall_pass = tools_pass and keywords_pass and scores["avg"] >= 3.0
    weighted_score = scores["avg"] * test.get("weight", 1.0) if overall_pass else 0.0

    result = {
        "run_id": run_id,
        "test_id": test["id"],
        "category": test["category"],
        "question": test["question"],
        "response": response[:2000],  # truncate for storage
        "tools_called": json.dumps(tools_called),
        "required_tools": json.dumps(test.get("required_tools", [])),
        "tools_pass": tools_pass,
        "keywords_pass": keywords_pass,
        "llm_score": scores["avg"],
        "llm_accuracy": float(scores.get("accuracy", 3)),
        "llm_specificity": float(scores.get("specificity", 3)),
        "llm_appropriate": float(scores.get("appropriate", 3)),
        "llm_actionable": float(scores.get("actionable", 3)),
        "llm_feedback": scores.get("feedback", ""),
        "overall_pass": overall_pass,
        "weighted_score": weighted_score,
        "weight": test.get("weight", 1.0),
    }

    if verbose:
        status = "✅ PASS" if overall_pass else "❌ FAIL"
        print(f"  {status} | tools={'✓' if tools_pass else '✗'} | keywords={'✓' if keywords_pass else '✗'} | LLM={scores['avg']}/5")
        if not tools_pass:
            print(f"    Missing tools: {missing_tools}")
        if not keywords_pass:
            print(f"    Missing keywords: {missing_keywords}")
        if scores["avg"] < 3.0:
            print(f"    Judge feedback: {scores.get('feedback', '')}")

    return result


# COMMAND ----------

# MAGIC %md ## Run Evaluation Suite

# COMMAND ----------

import uuid
from datetime import datetime
from pyspark.sql.types import (
    StructType, StructField, StringType, BooleanType,
    DoubleType, TimestampType
)

def run_evaluation(categories=None, verbose=True):
    """
    Run the full evaluation suite (or a subset of categories).
    Returns a summary dict and saves all results to coach.eval_results.
    """
    run_id = f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"\n{'='*60}")
    print(f"=== AI Coach Evaluation Run: {run_id} ===")
    print(f"{'='*60}")

    # Filter test cases
    tests_to_run = [t for t in TEST_CASES if categories is None or t["category"] in categories]
    print(f"Running {len(tests_to_run)} test cases...\n")

    all_results = []
    for test in tests_to_run:
        result = run_single_test(test, run_id, verbose=verbose)
        result["run_ts"] = datetime.now()
        all_results.append(result)

    # ── Summary ─────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"=== Results: {run_id} ===")
    print(f"{'='*60}")

    category_stats = {}
    for cat in CATEGORIES:
        cat_results = [r for r in all_results if r["category"] == cat]
        if not cat_results:
            continue
        passed = sum(1 for r in cat_results if r["overall_pass"])
        total = len(cat_results)
        pct = round(passed / total * 100) if total > 0 else 0
        category_stats[cat] = {"passed": passed, "total": total, "pct": pct}
        bar = "✅" if pct >= 80 else ("⚠️" if pct >= 60 else "❌")
        print(f"  {bar} {cat.replace('_', ' ').title():20}: {passed}/{total}  ({pct}%)")

    total_pass = sum(1 for r in all_results if r["overall_pass"])
    total_tests = len(all_results)
    total_weighted = sum(r["weighted_score"] for r in all_results)
    max_weighted = sum(r["weight"] * 5 for r in all_results)  # max 5 LLM score
    overall_pct = round(total_pass / total_tests * 100) if total_tests > 0 else 0

    print(f"\n  Overall: {total_pass}/{total_tests} ({overall_pct}%)")
    print(f"  Weighted score: {round(total_weighted, 1)} / {round(max_weighted, 1)}")

    # Failures summary
    failures = [r for r in all_results if not r["overall_pass"]]
    if failures:
        print(f"\nFailures ({len(failures)}):")
        for r in failures:
            reasons = []
            if not r["tools_pass"]:
                req = json.loads(r["required_tools"])
                called = json.loads(r["tools_called"])
                missing = [t for t in req if t not in called]
                reasons.append(f"missed tools: {missing}")
            if not r["keywords_pass"]:
                reasons.append("missing keywords")
            if r["llm_score"] < 3.0:
                reasons.append(f"low LLM score ({r['llm_score']}/5): {r['llm_feedback'][:60]}")
            print(f"  {r['test_id']} ({r['category']}): {' | '.join(reasons)}")

    # ── Save to Delta ────────────────────────────────────────────────────────
    schema = StructType([
        StructField("run_id",          StringType(),  False),
        StructField("test_id",         StringType(),  False),
        StructField("category",        StringType(),  True),
        StructField("question",        StringType(),  True),
        StructField("response",        StringType(),  True),
        StructField("tools_called",    StringType(),  True),
        StructField("required_tools",  StringType(),  True),
        StructField("tools_pass",      BooleanType(), True),
        StructField("keywords_pass",   BooleanType(), True),
        StructField("llm_score",       DoubleType(),  True),
        StructField("llm_accuracy",    DoubleType(),  True),
        StructField("llm_specificity", DoubleType(),  True),
        StructField("llm_appropriate", DoubleType(),  True),
        StructField("llm_actionable",  DoubleType(),  True),
        StructField("llm_feedback",    StringType(),  True),
        StructField("overall_pass",    BooleanType(), True),
        StructField("weighted_score",  DoubleType(),  True),
        StructField("weight",          DoubleType(),  True),
        StructField("run_ts",          TimestampType(), True),
    ])

    df = spark.createDataFrame(all_results, schema=schema)
    df.write.format("delta").mode("append").saveAsTable(f"{CATALOG}.coach.eval_results")
    print(f"\n✅ Results saved to {CATALOG}.coach.eval_results")

    return {
        "run_id": run_id,
        "total_pass": total_pass,
        "total_tests": total_tests,
        "overall_pct": overall_pct,
        "weighted_score": total_weighted,
        "max_weighted": max_weighted,
        "category_stats": category_stats,
        "failures": failures,
    }


CATEGORIES = ["factual", "analysis", "planning", "trend", "edge_case"]

# COMMAND ----------

# MAGIC %md ## Run the Full Evaluation
# MAGIC
# MAGIC This cell runs all 25 test cases. Expect ~10-20 minutes depending on LLM speed.
# MAGIC Set `categories=["factual"]` to run a quick subset first.

# COMMAND ----------

# Full run
summary = run_evaluation(categories=RUN_CATEGORIES, verbose=True)

# COMMAND ----------

# MAGIC %md ## Compare Runs Over Time

# COMMAND ----------

display(spark.sql(f"""
SELECT
    run_id,
    MIN(run_ts) AS run_time,
    COUNT(*) AS total_tests,
    SUM(CASE WHEN overall_pass THEN 1 ELSE 0 END) AS passed,
    ROUND(SUM(CASE WHEN overall_pass THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS pass_pct,
    ROUND(AVG(llm_score), 2) AS avg_llm_score
FROM {CATALOG}.coach.eval_results
GROUP BY run_id
ORDER BY run_time DESC
LIMIT 10
"""))

# COMMAND ----------

# MAGIC %md ## Score Breakdown by Category (latest run)

# COMMAND ----------

latest_run_id = spark.sql(f"""
    SELECT run_id FROM {CATALOG}.coach.eval_results ORDER BY run_ts DESC LIMIT 1
""").collect()[0].run_id

display(spark.sql(f"""
SELECT
    category,
    COUNT(*) AS tests,
    SUM(CASE WHEN overall_pass THEN 1 ELSE 0 END) AS passed,
    ROUND(SUM(CASE WHEN overall_pass THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 0) AS pass_pct,
    ROUND(AVG(llm_score), 2) AS avg_llm_score,
    ROUND(AVG(llm_accuracy), 2) AS avg_accuracy,
    ROUND(AVG(llm_specificity), 2) AS avg_specificity,
    ROUND(AVG(llm_actionable), 2) AS avg_actionable
FROM {CATALOG}.coach.eval_results
WHERE run_id = '{latest_run_id}'
GROUP BY category
ORDER BY pass_pct DESC
"""))

# COMMAND ----------

# MAGIC %md ## Failure Details (latest run)

# COMMAND ----------

display(spark.sql(f"""
SELECT
    test_id,
    category,
    LEFT(question, 80) AS question,
    tools_pass,
    keywords_pass,
    llm_score,
    llm_feedback,
    LEFT(response, 200) AS response_preview
FROM {CATALOG}.coach.eval_results
WHERE run_id = '{latest_run_id}' AND overall_pass = false
ORDER BY category, test_id
"""))
