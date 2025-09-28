from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional
import os
import joblib

app = FastAPI(title="Decider Service")

# Model paths (can be overridden via env)
PERFORM_MODEL_PATH = os.getenv("DECIDER_PERFORM_MODEL_PATH", "model/perform_model.pkl")
PERFORM_VECT_PATH = os.getenv("DECIDER_PERFORM_VECT_PATH", "model/perform_vectorizer.pkl")
LABEL_MODEL_PATH = os.getenv("DECIDER_LABEL_MODEL_PATH", "model/label_model.pkl")
LABEL_VECT_PATH = os.getenv("DECIDER_LABEL_VECT_PATH", "model/label_vectorizer.pkl")


class DecideRequest(BaseModel):
    question: str


class DecideResponse(BaseModel):
    perform_analytics: bool
    analytics: Optional[str] = None


@app.get("/health")
async def health():
    return {"ok": True}


def rule_based_decide(q: str) -> tuple[bool, Optional[str]]:
    """Simple keyword-based fallback when models are unavailable.
    Returns (perform_analytics, analytics_label or None).
    """
    ql = (q or "").lower()
    # TTL/ontology-only questions → no analytics
    if any(k in ql for k in [
        "label", "type", "class", "category", "installed", "location",
        "where is", "which sensors", "list sensors", "show sensors"
    ]):
        return False, None

    # Otherwise, assume analytics is desired and pick a label
    if any(k in ql for k in ["average", "avg", "mean"]):
        return True, "average"
    if any(k in ql for k in ["maximum", "max", "peak"]):
        return True, "max"
    if any(k in ql for k in ["minimum", "min", "lowest"]):
        return True, "min"
    if any(k in ql for k in ["trend", "trending", "over time", "time series"]):
        return True, "analyze_sensor_trend"
    if any(k in ql for k in ["anomaly", "outlier", "abnormal"]):
        return True, "detect_anomalies"
    if any(k in ql for k in ["correlate", "correlation", "relationship"]):
        return True, "correlate_sensors"
    if any(k in ql for k in ["sum", "total", "aggregate"]):
        return True, "sum"
    # Reasonable default when we think analytics is needed
    return True, "analyze_sensor_trend"


def is_ttl_only(q: str) -> bool:
    """Detect ontology/listing-only questions that shouldn't trigger analytics.
    This is applied as a hard override even when models are present to avoid
    running analytics for queries clearly about metadata or listings.
    """
    import re
    ql = (q or "").lower()
    # Quick keyword checks
    ttl_keywords = [
        "label", "type", "class", "category", "installed", "location",
        "where is", "where are",
    ]
    if any(k in ql for k in ttl_keywords):
        return True
    # Listing-style regex patterns (flexible word gaps)
    patterns = [
        r"\bwhat\s+(are|r)\s+the\s+sensors\b",
        r"\b(list|show|which)\b.*\bsensors?\b",
        r"\bsensors?\s+(in|at|for)\b",
        r"\bwhere\s+are\s+the\s+sensors\b",
    ]
    return any(re.search(p, ql) for p in patterns)


def load_model(path_model: str, path_vect: str):
    if os.path.exists(path_model) and os.path.exists(path_vect):
        model = joblib.load(path_model)
        vect = joblib.load(path_vect)
        return model, vect
    return None, None


PERFORM_MODEL, PERFORM_VECT = load_model(PERFORM_MODEL_PATH, PERFORM_VECT_PATH)
LABEL_MODEL, LABEL_VECT = load_model(LABEL_MODEL_PATH, LABEL_VECT_PATH)


@app.post("/decide", response_model=DecideResponse)
async def decide(req: DecideRequest):
    global PERFORM_MODEL, PERFORM_VECT, LABEL_MODEL, LABEL_VECT

    # TTL/listing-only override: never perform analytics for these
    if is_ttl_only(req.question):
        return {"perform_analytics": False, "analytics": None}

    # Fallback logic if models missing
    if PERFORM_MODEL is None or PERFORM_VECT is None or LABEL_MODEL is None or LABEL_VECT is None:
        perform, label = rule_based_decide(req.question)
        return {"perform_analytics": perform, "analytics": label}

    # Predict perform_analytics (boolean)
    x_perf = PERFORM_VECT.transform([req.question])
    perform_pred = PERFORM_MODEL.predict(x_perf)[0]
    perform = bool(perform_pred)

    label: Optional[str] = None
    if perform:
        # Only predict label if we plan to perform analytics
        x_lab = LABEL_VECT.transform([req.question])
        label = str(LABEL_MODEL.predict(x_lab)[0])

    return {"perform_analytics": perform, "analytics": label}
