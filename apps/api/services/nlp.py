# apps/api/services/nlp.py
from sentence_transformers import SentenceTransformer, util
import json
import os
import sys

class SymptomNLP:
    def __init__(self, model_name="sentence-transformers/all-MiniLM-L6-v2", top_k=5):
        self.top_k = top_k
        # Load model (fast & lightweight)
        try:
            self.model = SentenceTransformer(model_name)
        except Exception as e:
            print(f"[SymptomNLP] Error loading model '{model_name}': {e}", file=sys.stderr)
            raise

        # Resolve KB path(s) - prefer conditions.json, fallback to conditions_enriched.json
        base_dir = os.path.dirname(__file__)
        candidates = [
            os.path.normpath(os.path.join(base_dir, "..", "..", "packages", "kb", "conditions.json")),
            os.path.normpath(os.path.join(base_dir, "..", "..", "packages", "kb", "conditions_enriched.json")),
            os.path.normpath(os.path.join(base_dir, "..", "..", "..", "packages", "kb", "conditions.json")),
            os.path.normpath(os.path.join(base_dir, "..", "..", "..", "packages", "kb", "conditions_enriched.json")),
        ]

        self.conditions = []
        kb_path_used = None
        for p in candidates:
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        self.conditions = json.load(f)
                    kb_path_used = p
                    break
                except Exception as e:
                    print(f"[SymptomNLP] Failed to load KB at {p}: {e}", file=sys.stderr)

        if not self.conditions:
            print("[SymptomNLP] WARNING: No KB file found. Continuing with empty KB.", file=sys.stderr)
            # Set empty embeddings to avoid attribute errors later
            self.condition_descriptions = []
            self.condition_names = []
            self.description_embeddings = None
            self.name_embeddings = None
            return

        print(f"[SymptomNLP] Loaded KB from: {kb_path_used}")

        # Precompute lists
        self.condition_descriptions = [c.get("description", "") for c in self.conditions]
        self.condition_names = [c.get("name", "") for c in self.conditions]

        # Compute embeddings (wrapped in try/except to avoid crashing on unexpected errors)
        try:
            if self.condition_descriptions:
                self.description_embeddings = self.model.encode(
                    self.condition_descriptions,
                    convert_to_tensor=True
                )
            else:
                self.description_embeddings = None

            if self.condition_names:
                self.name_embeddings = self.model.encode(
                    self.condition_names,
                    convert_to_tensor=True
                )
            else:
                self.name_embeddings = None
        except Exception as e:
            print(f"[SymptomNLP] Error computing embeddings: {e}", file=sys.stderr)
            self.description_embeddings = None
            self.name_embeddings = None

    def rank(self, user_text: str):
        """
        Returns a list of up to top_k dicts:
        {
            "name": ...,
            "similarity_score": float,
            "zero_shot_score": float,
            "final_score": float,
            "rationale": ...
        }
        """
        user_text = (user_text or "").strip()
        if not user_text:
            return []

        # If no KB or embeddings available, return empty gracefully
        if not self.conditions or self.description_embeddings is None or self.name_embeddings is None:
            # fallback: return empty list (or could return model-only suggestions later)
            return []

        try:
            user_emb = self.model.encode(user_text, convert_to_tensor=True)
        except Exception as e:
            print(f"[SymptomNLP] Error encoding user text: {e}", file=sys.stderr)
            return []

        # Compute similarities
        try:
            desc_scores_tensor = util.cos_sim(user_emb, self.description_embeddings)[0]  # tensor of shape (N,)
            name_scores_tensor = util.cos_sim(user_emb, self.name_embeddings)[0]
        except Exception as e:
            print(f"[SymptomNLP] Error computing similarity: {e}", file=sys.stderr)
            return []

        combined = []
        for idx in range(len(self.conditions)):
            try:
                d_score = desc_scores_tensor[idx].item() if hasattr(desc_scores_tensor[idx], "item") else float(desc_scores_tensor[idx])
            except Exception:
                d_score = 0.0
            try:
                n_score = name_scores_tensor[idx].item() if hasattr(name_scores_tensor[idx], "item") else float(name_scores_tensor[idx])
            except Exception:
                n_score = 0.0

            final_score = float(0.7 * d_score + 0.3 * n_score)

            combined.append({
                "name": self.conditions[idx].get("name", ""),
                "similarity_score": float(d_score),
                "zero_shot_score": float(n_score),
                "final_score": round(final_score, 6),
                "rationale": self.conditions[idx].get("description", "")
            })

        # sort and return top_k
        combined = sorted(combined, key=lambda x: x["final_score"], reverse=True)
        return combined[: self.top_k]
