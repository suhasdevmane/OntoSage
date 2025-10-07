import logging
import re
import os
from typing import Dict, Any, List, Tuple
from flask import Blueprint, request, jsonify

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None  # Fallback – service will still run with basic logic

decider_service = Blueprint("decider_service", __name__)

RULES_PATH = os.getenv(
    "DECIDER_RULES_FILE",
    os.path.join(os.path.dirname(__file__), "..", "config", "analytics_mapping_rules.yml"),
)

_rules_cache: Dict[str, Any] = {}


def _load_rules() -> Dict[str, Any]:
    if not yaml:
        logging.warning("PyYAML not installed – Decider will run with default heuristics only.")
        return {}
    global _rules_cache
    try:
        if os.path.exists(RULES_PATH):
            with open(RULES_PATH, "r", encoding="utf-8") as f:
                _rules_cache = yaml.safe_load(f) or {}
        else:
            logging.warning(f"Decider rules file not found at {RULES_PATH}")
    except Exception as e:  # pragma: no cover
        logging.error(f"Failed to load decider rules: {e}")
    return _rules_cache


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _baseline_metadata_question(q: str) -> bool:
    ql = q.lower()
    return any(
        p in ql
        for p in [
            "which sensors",
            "list sensors",
            "show sensors",
            "where are the sensors",
            "location",
            "label",
            "class",
            "type",
            "installed",
        ]
    )


def _score_candidate(question: str, fn_name: str, meta: Dict[str, Any], rules: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
    tokens = _tokenize(question)
    token_set = set(tokens)
    patterns = meta.get("patterns", []) or []
    pattern_hits: List[str] = []
    pattern_score = 0.0
    for pat in patterns:
        try:
            if re.search(pat, question, flags=re.IGNORECASE):
                pattern_hits.append(pat)
                # weight longer patterns slightly higher
                pattern_score += 1.0 + min(len(pat) / 40.0, 0.5)
        except re.error:
            continue

    # keyword boosts from rules
    boosts_cfg = (rules.get("boosts") or {}).get(fn_name, {})
    kw_list = boosts_cfg.get("keywords", []) or []
    weight = float(boosts_cfg.get("weight", 1.0))
    keyword_matches: List[str] = []
    kw_score = 0.0
    if kw_list:
        for kw in kw_list:
            kw_norm = kw.lower()
            if kw_norm in token_set:
                keyword_matches.append(kw_norm)
                kw_score += weight

    raw_score = pattern_score + kw_score
    return raw_score, {
        "function": fn_name,
        "patterns_matched": pattern_hits,
        "keywords_matched": keyword_matches,
        "pattern_score": round(pattern_score, 3),
        "keyword_score": round(kw_score, 3),
        "raw_score": round(raw_score, 3),
        "description": (meta.get("description") or "").split("\n")[0][:160],
    }


def _apply_overrides(question: str, rules: Dict[str, Any]) -> str:
    overrides = rules.get("overrides") or []
    for ov in overrides:
        cond = ov.get("if")
        target = ov.get("analysis_type")
        if not cond or not target:
            continue
        try:
            if re.search(cond, question, flags=re.IGNORECASE):
                return target
        except re.error:
            continue
    return ""


def _suggest_params(analysis_type: str, question: str) -> Dict[str, Any]:
    ql = question.lower()
    suggested: Dict[str, Any] = {}
    if analysis_type in {"analyze_temperatures", "analyze_humidity", "analyze_temperature_humidity"}:
        if "range" in ql or "comfort" in ql:
            # Provide a generic comfort band hint
            if analysis_type.startswith("analyze_temperature"):
                suggested["acceptable_range"] = [18, 24]
            if analysis_type.startswith("analyze_humidity") or analysis_type == "analyze_temperature_humidity":
                suggested["humidity_range"] = [40, 60]
    if analysis_type == "detect_anomalies" and any(w in ql for w in ["robust", "iqr"]):
        if "iqr" in ql:
            suggested["method"] = "iqr"
        if "robust" in ql:
            suggested["robust"] = True
    if analysis_type == "time_to_threshold":
        # attempt to parse a numeric threshold
        m = re.search(r"(\d+(?:\.\d+)?)", ql)
        if m:
            try:
                suggested["threshold"] = float(m.group(1))
            except Exception:
                pass
    return suggested


@decider_service.route("/health", methods=["GET"])
def health():  # pragma: no cover
    return jsonify({"status": "ok", "rules_loaded": bool(_rules_cache)}), 200

@decider_service.route("/reload", methods=["POST", "GET"])
def reload_rules():
    before = bool(_rules_cache)
    rules = _load_rules()
    return jsonify({"ok": True, "had_rules": before, "loaded": bool(rules), "version": rules.get("version") if isinstance(rules, dict) else None})


@decider_service.route("/decide", methods=["POST"])
def decide():
    from .analytics_service import _analytics_registry_meta  # local import to avoid circular during app init

    payload = request.get_json(force=True, silent=True) or {}
    question = payload.get("question", "")
    if not question:
        return jsonify({"error": "question field required"}), 400

    # Lazy load or reload rules if empty
    if not _rules_cache:
        _load_rules()

    rules = _rules_cache or {}

    if _baseline_metadata_question(question):
        return jsonify({
            "perform_analytics": False,
            "analytics": None,
            "reason": "Detected metadata/listing style question",
            "confidence": 0.0,
        })

    # Overrides take precedence
    override_choice = _apply_overrides(question, rules)
    override_used = False
    candidate_rows: List[Dict[str, Any]] = []
    max_score = 0.0
    for fn_name, meta in _analytics_registry_meta.items():
        score, detail = _score_candidate(question, fn_name, meta, rules)
        if score > 0:
            max_score = max(max_score, score)
            candidate_rows.append(detail)

    # Normalise scores
    if max_score > 0:
        for row in candidate_rows:
            row["normalized_score"] = round(row["raw_score"] / max_score, 4)
    candidate_rows.sort(key=lambda r: r.get("raw_score", 0), reverse=True)

    selected = candidate_rows[0]["function"] if candidate_rows else None
    confidence = candidate_rows[0].get("normalized_score", 0.0) if candidate_rows else 0.0

    if override_choice:
        selected = override_choice
        confidence = max(confidence, 0.95)
        override_used = True

    min_conf = float(os.getenv("DECIDER_MIN_CONF", "0.25"))
    perform = bool(selected and confidence >= min_conf)

    suggested_params = _suggest_params(selected, question) if perform and selected else {}

    return jsonify({
        "question": question,
        "perform_analytics": perform,
        "analytics": selected,
        "confidence": round(confidence, 4),
        "override_used": override_used,
        "candidates": candidate_rows[:5],  # top 5 for transparency
        "suggested_params": suggested_params,
        "rules_version": rules.get("version"),
    })


# Convenience endpoint for quick manual testing from a browser
@decider_service.route("/demo", methods=["GET"])
def demo():  # pragma: no cover - convenience only
    q = request.args.get("q", "show me the latest temperature trend")
    return decide()
