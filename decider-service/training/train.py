import os
import json
import argparse
from typing import List, Tuple
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression


ROOT = os.path.dirname(os.path.dirname(__file__))
MODEL_DIR = os.path.join(ROOT, "model")
DATA_DIR = os.path.join(ROOT, "data")

# Default dataset combining perform flag and analytics label
COMBINED_DATA = os.path.join(DATA_DIR, "decider_training.auto.jsonl")


def ensure_dirs():
    os.makedirs(MODEL_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)


def load_combined_dataset(path: str) -> Tuple[List[str], List[int], List[str]]:
    texts: List[str] = []
    perform_flags: List[int] = []
    labels: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            q = obj.get("text") or obj.get("question") or ""
            perform = int(obj.get("perform", obj.get("perform_analytics", 0)))
            analytics = obj.get("analytics")
            texts.append(q)
            perform_flags.append(perform)
            labels.append(analytics if analytics is not None else "none")
    return texts, perform_flags, labels


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=COMBINED_DATA)
    args = parser.parse_args()

    ensure_dirs()

    if not os.path.exists(args.data):
        raise FileNotFoundError(f"Dataset not found: {args.data}\nPlease generate {args.data} first.")

    texts, perform_flags, labels = load_combined_dataset(args.data)
    print(f"Loaded {len(texts)} training examples")

    # Train perform_analytics classifier
    perf_vect = TfidfVectorizer(ngram_range=(1, 2), min_df=2)
    Xp = perf_vect.fit_transform(texts)
    perf_clf = LogisticRegression(max_iter=1000)
    perf_clf.fit(Xp, perform_flags)

    joblib.dump(perf_clf, os.path.join(MODEL_DIR, "perform_model.pkl"))
    joblib.dump(perf_vect, os.path.join(MODEL_DIR, "perform_vectorizer.pkl"))
    print("Saved perform_analytics model + vectorizer")

    # Train label classifier (on all examples; the model will learn to map ontology-only Qs to 'none')
    lab_vect = TfidfVectorizer(ngram_range=(1, 2), min_df=2)
    Xl = lab_vect.fit_transform(texts)
    lab_clf = LogisticRegression(max_iter=1000)
    lab_clf.fit(Xl, labels)

    joblib.dump(lab_clf, os.path.join(MODEL_DIR, "label_model.pkl"))
    joblib.dump(lab_vect, os.path.join(MODEL_DIR, "label_vectorizer.pkl"))
    print("Saved analytics label model + vectorizer")


if __name__ == "__main__":
    main()
