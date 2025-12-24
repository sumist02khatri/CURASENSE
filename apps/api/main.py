# apps/api/main.py
import re
import time
import hashlib
import asyncio
import json
from typing import List, Optional

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

# --- IMPORT SERVICES (your existing modules) ---
from apps.api.services.nlp import SymptomNLP
from apps.api.services.rules import detect_red_flags   # existing rule-based detector
from apps.api.services.redflags import check_red_flags as kb_check_red_flags
from apps.api.services.crosscheck import CrossChecker

# -------------------------------
#       APP INIT
# -------------------------------
app = FastAPI(
    title="CURASENSE API",
    version="1.0.0",
    description="AI Symptom Screening & Triage Backend (with KB + DBpedia enrichment)"
)

# -------------------------------
#       CONFIG / INSTANCES
# -------------------------------
# Init NLP (loads model and KB descriptions)
nlp_engine = SymptomNLP()

# CrossChecker: tuned for speed/precision
# top_k: how many candidates to consider
# top_m: how many of top_k to run DBpedia lookup for (keep small: 1-2)
# dbpedia_min_score: threshold to call DBpedia (0.0-1.0)
cross_checker = CrossChecker(
    nlp_engine=nlp_engine,
    top_k=10,
    top_m=1,
    dbpedia_enabled=True,
    dbpedia_min_score=0.60
)


# -------------------------------
#       MODELS
# -------------------------------
class TriageRequest(BaseModel):
    text: str
    age_range: Optional[str] = None
    sex: Optional[str] = None
    chronic_conditions: Optional[List[str]] = []
    user_name: Optional[str] = None


# -------------------------------
#   Utility helpers
# -------------------------------
def parse_age_range(age_range: Optional[str]) -> int:
    """
    Convert strings like "30-39", "30", "30s" into an integer age.
    Returns default 30 if parsing fails or None provided.
    """
    if not age_range:
        return 30
    s = str(age_range).strip()
    if re.fullmatch(r"\d{1,3}$", s):
        return int(s)
    m = re.match(r"^\s*(\d{1,3})\s*-\s*(\d{1,3})\s*$", s)
    if m:
        a = int(m.group(1)); b = int(m.group(2))
        return (a + b) // 2
    m2 = re.match(r"^(\d{2})s('?s)?$", s)
    if m2:
        base = int(m2.group(1))
        return base + 5
    m3 = re.search(r"(\d{1,3})", s)
    if m3:
        return int(m3.group(1))
    return 30


def make_trace_id(user_text: str, user_name: Optional[str] = None) -> str:
    """
    Privacy-conscious trace id using a hash of text + optional name + timestamp.
    """
    key = f"{user_text}|{user_name or ''}|{time.time()}"
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return f"trace-{h[:12]}"


# -------------------------------
#       Health / Ping
# -------------------------------
@app.get("/")
def home():
    return {
        "status": "CURASENSE API running",
        "message": "Welcome to CURASENSE - AI Symptom Triage Backend",
        "docs": "/docs",
        "triage_endpoint": "/api/v1/triage"
    }


@app.get("/ping")
def ping():
    return {"status": "ok"}


# -------------------------------
#  Startup: pre-warm DBpedia cache (optional)
# -------------------------------
@app.on_event("startup")
async def prewarm_dbpedia():
    """
    Pre-warm DBpedia cache for top KB names to reduce first-request latency.
    This will only run if cross_checker.dbpedia is available.
    """
    db = getattr(cross_checker, "dbpedia", None)
    if db is None:
        print("[startup] DBpedia disabled or unavailable; skipping prewarm.")
        return

    try:
        names = [c.get("name") for c in getattr(cross_checker, "kb_list", [])[:8] if c.get("name")]
        if not names:
            print("[startup] No KB names to prewarm.")
            return
        print(f"[startup] Pre-warming DBpedia cache for {len(names)} KB entries...")
        tasks = [db.lookup_abstract(n) for n in names]
        # Run with gather (concurrent)
        await asyncio.gather(*tasks, return_exceptions=True)
        print("[startup] DBpedia pre-warm complete.")
    except Exception as e:
        print("[startup] DBpedia prewarm failed:", e)


# -------------------------------
#       TRIAGE ENDPOINT (async)
# -------------------------------
@app.post("/api/v1/triage")
async def triage(req: TriageRequest):
    user_text = (req.text or "").strip()
    user_name = (req.user_name or "").strip() if req.user_name else None

    if not user_text:
        return {
            "conditions": [],
            "urgency": "routine",
            "red_flags": [],
            "advice": {"selfcare": [], "escalate_when": []},
            "trace_id": make_trace_id("", user_name),
            "user_name": user_name
        }

    # 1) Rule-based red-flag checks (existing)
    rf_user = detect_red_flags(user_text) or []
    rf_kb = kb_check_red_flags(user_text) or []

    # ----- FIX: dedupe list-of-dicts while preserving order -----
    seen = set()
    combined_rf = []
    for item in (rf_user + rf_kb):
        # Use JSON serialization for a stable, comparable key
        try:
            key = json.dumps(item, sort_keys=True)
        except (TypeError, ValueError):
            # Fallback to repr if something inside item is not JSON-serializable
            key = repr(item)
        if key not in seen:
            seen.add(key)
            combined_rf.append(item)
    # -----------------------------------------------------------

    if combined_rf:
        return {
            "conditions": [],
            "urgency": "emergency",
            "red_flags": combined_rf,
            "advice": {
                "selfcare": [],
                "escalate_when": ["Seek emergency care immediately."]
            },
            "trace_id": make_trace_id(user_text, user_name),
            "user_name": user_name
        }

    # 2) Parse age and chronic conditions
    age = parse_age_range(req.age_range)
    chronic_conditions = req.chronic_conditions or []

    # 3) Run analysis with CrossChecker (async, concurrent DBpedia lookups)
    # Use analyze_async which runs the synchronous NLP.rank in a thread and DBpedia lookups concurrently
    try:
        enriched = await cross_checker.analyze_async(user_text, age=age, chronic_conditions=chronic_conditions)
    except AttributeError:
        # If cross_checker doesn't expose analyze_async, fall back to sync analyze (preserves compatibility)
        enriched = cross_checker.analyze(user_text, age=age, chronic_conditions=chronic_conditions)
    except Exception as e:
        # If something goes wrong while enriching, fallback to fast NLP ranking to avoid total failure
        print("[triage] analyze_async failed:", e)
        try:
            ranked = nlp_engine.rank(user_text)[:5]
            enriched = [{"name": r.get("name"), "final_score": r.get("final_score"), "rationale": r.get("rationale")} for r in ranked]
        except Exception as e2:
            print("[triage] fallback rank failed:", e2)
            enriched = []

    # 4) Build response
    response = {
        "conditions": enriched[:5],
        "urgency": "routine",
        "red_flags": [],
        "advice": {
            "selfcare": ["Hydrate well", "Rest", "Monitor symptoms"],
            "escalate_when": ["Symptoms worsen", "Fever lasts >3 days"]
        },
        "trace_id": make_trace_id(user_text, user_name),
        "user_name": user_name
    }

    # -------------------------------
    # ADD DELAY HERE (3–5 SECONDS)
    # -------------------------------
    import random
    delay = random.uniform(3, 5)
    await asyncio.sleep(delay)

    return response


# -------------------------------
#  Run dev server (optional)
# -------------------------------
if __name__ == "__main__":
    uvicorn.run("apps.api.main:app", host="0.0.0.0", port=8000, reload=True)
