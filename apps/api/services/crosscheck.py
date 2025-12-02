# apps/api/services/crosscheck.py
import os
import json
import asyncio
from typing import List, Dict, Any

try:
    from apps.api.services.dbpedia_service import DBPediaService
except Exception:
    DBPediaService = None

KB_CANDIDATES = [
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "packages", "kb", "conditions_enriched.json")),
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "packages", "kb", "conditions.json")),
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "packages", "kb", "conditions.json")),
]

def load_kb():
    for p in KB_CANDIDATES:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError("KB not found in expected locations.")

class CrossChecker:
    def __init__(self, nlp_engine, top_k=10, top_m=2, dbpedia_enabled=True, dbpedia_min_score=0.6):
        self.nlp = nlp_engine
        self.kb_list = load_kb()
        self.kb_by_key = {}
        for c in self.kb_list:
            name_key = c.get("name", "").strip().lower()
            if name_key:
                self.kb_by_key[name_key] = c
            for a in c.get("aliases", []):
                if a and isinstance(a, str):
                    self.kb_by_key[a.strip().lower()] = c
        self.top_k = top_k
        self.top_m = top_m
        self.dbpedia = DBPediaService() if (dbpedia_enabled and DBPediaService is not None) else None
        self.dbpedia_min_score = dbpedia_min_score

    def _normalize(self, text: str) -> str:
        return (text or "").lower()

    def _contains_token(self, haystack: str, token: str) -> bool:
        if not token:
            return False
        return token.lower() in haystack

    def _missing_symptoms(self, user_text: str, condition: Dict[str,Any]) -> List[str]:
        text = self._normalize(user_text)
        missing = []
        for s in condition.get("common_symptoms", []):
            if not self._contains_token(text, s):
                missing.append(s)
        return missing

    def _pick_followup(self, missing: List[str], condition: Dict[str,Any]):
        questions = condition.get("follow_up_questions", [])
        if not questions:
            return None
        if not missing:
            return questions[0]
        for m in missing:
            for q in questions:
                if any(word in q.get("text","").lower() for word in m.lower().split() if len(word) > 3):
                    return q
        return questions[0]

    def _risk_score(self, final_score: float, severity_score: float, age: int = 30, chronic_conditions: list = None):
        chronic_conditions = chronic_conditions or []
        chronic_factor = 1.2 if chronic_conditions else 1.0
        age_factor = 1.0 + max(0, (age - 50) / 200.0)
        base = (final_score * 0.6) + (severity_score * 0.4)
        risk = min(1.0, base * chronic_factor * age_factor)
        return round(risk, 3)

    def _lookup_kb_by_nlp_name(self, nlp_name: str):
        if not nlp_name:
            return None
        key = nlp_name.strip().lower()
        return self.kb_by_key.get(key)

    async def analyze_async(self, user_text: str, age: int = 30, chronic_conditions: list = None):
        """
        Async analyze: runs NLP.rank in a thread, then performs DBpedia lookups concurrently.
        Returns same structure as synchronous analyze but with DBpedia fields filled.
        """
        chronic_conditions = chronic_conditions or []
        # Run the synchronous nlp.rank in a thread to avoid blocking event loop
        ranked = await asyncio.to_thread(self.nlp.rank, user_text)
        ranked = ranked[: self.top_k]

        results = []
        # prepare tasks for DBpedia lookups for high-confidence top_m items
        db_tasks = []
        db_indices = []
        for idx, item in enumerate(ranked):
            name = item.get("name")
            final_score = float(item.get("final_score", 0.0))
            kb_item = self._lookup_kb_by_nlp_name(name)
            if self.dbpedia and idx < self.top_m and final_score >= self.dbpedia_min_score:
                db_name = kb_item.get("name") if kb_item else name
                db_tasks.append(self.dbpedia.lookup_abstract(db_name))
                db_indices.append(idx)
            else:
                db_tasks.append(None)  # placeholder to keep index mapping

        # run all DBpedia tasks concurrently but skip None
        # build a list of coroutine objects for the non-None tasks
        coros = [t for t in db_tasks if t is not None]
        db_results = []
        if coros:
            db_results = await asyncio.gather(*coros, return_exceptions=True)

        # map db_results back to db_tasks indices
        db_map = {}
        res_ptr = 0
        for i, t in enumerate(db_tasks):
            if t is not None:
                r = db_results[res_ptr]
                res_ptr += 1
                if isinstance(r, Exception):
                    db_map[i] = {"matched": False}
                else:
                    db_map[i] = r
            else:
                db_map[i] = None

        # build final results
        for idx, item in enumerate(ranked):
            name = item.get("name")
            final_score = float(item.get("final_score", 0.0))
            similarity_score = item.get("similarity_score")
            zero_shot = item.get("zero_shot_score")
            rationale = item.get("rationale", "")

            kb_item = self._lookup_kb_by_nlp_name(name)
            missing = []
            followup = None
            severity = 0.5
            urgency = "routine"
            if kb_item:
                missing = self._missing_symptoms(user_text, kb_item)
                followup = self._pick_followup(missing, kb_item)
                severity = kb_item.get("severity_score", 0.5)
                urgency = kb_item.get("urgency", "routine")

            risk = self._risk_score(final_score, severity, age, chronic_conditions)

            dbpedia_info = db_map.get(idx) if db_map.get(idx) is not None else None

            results.append({
                "name": name,
                "final_score": round(final_score, 3),
                "similarity_score": similarity_score,
                "zero_shot_score": zero_shot,
                "rationale": rationale,
                "kb": kb_item,
                "missing_symptoms": missing,
                "follow_up_question": followup,
                "risk_score": risk,
                "dbpedia": dbpedia_info
            })
        return results

    # backward-compatible synchronous wrapper
    def analyze(self, user_text: str, age: int = 30, chronic_conditions: list = None):
        # synchronous pass-through that runs the async version in the event loop if possible
        try:
            return asyncio.get_event_loop().run_until_complete(self.analyze_async(user_text, age, chronic_conditions))
        except Exception:
            # fallback: run in a new loop (safe but slower)
            return asyncio.new_event_loop().run_until_complete(self.analyze_async(user_text, age, chronic_conditions))
