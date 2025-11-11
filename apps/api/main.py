from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="CURASENSE API", version="1.0.0")

class TriageRequest(BaseModel):
    text: str
    age_range: str | None = None
    sex: str | None = None
    chronic_conditions: list[str] | None = []

@app.post("/api/v1/triage")
async def triage(req: TriageRequest):
    return {
        "conditions": [
            {"name": "Common Cold", "score": 0.78, "rationale": "Fever, sore throat, fatigue detected."},
            {"name": "Influenza", "score": 0.65, "rationale": "Symptoms overlap with flu-like patterns."}
        ],
        "urgency": "routine",
        "red_flags": [],
        "advice": {
            "selfcare": ["Hydrate well", "Rest", "Monitor temperature"],
            "escalate_when": ["Persistent high fever >3 days"]
        },
        "trace_id": "demo123"
    }
