import os
import json

# small base list
BASE_RED_FLAGS = [
    "loss of consciousness", "seizure", "unable to breathe", "can't breathe", "cannot breathe",
    "chest pain", "collapse", "fainting", "passing out", "severe bleeding", "vomiting blood",
    "blood in stool", "not breathing", "baby not breathing", "sudden weakness", "slurred speech"
]

# load KB red flag phrases optionally to extend rules
KB_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), "../../packages/kb/conditions_enriched.json"))

def _load_kb_flags():
    try:
        with open(KB_PATH, "r", encoding="utf-8") as f:
            kb = json.load(f)
        phrases = []
        for c in kb:
            for rf in c.get("red_flags", []):
                if rf and isinstance(rf, str):
                    phrases.append(rf.lower())
        return list(set(phrases))
    except Exception:
        return []

KB_RED_FLAGS = _load_kb_flags()
ALL_RED_FLAGS = list(set([p.lower() for p in BASE_RED_FLAGS + KB_RED_FLAGS]))

def check_red_flags(text: str):
    text_l = (text or "").lower()
    matches = []
    for p in ALL_RED_FLAGS:
        # simple containment
        if p in text_l:
            matches.append(p)
    return matches
