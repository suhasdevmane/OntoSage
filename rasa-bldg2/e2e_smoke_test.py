import os
import json
import random
import time
import requests
from datetime import datetime

DATA_FILE = os.path.join('Transformers','t5_base','abacws_bldg_timeseries_question_pairs_entities.json')
RASA_REST_URL = os.getenv('RASA_REST_URL', 'http://localhost:5005/webhooks/rest/webhook')
PARSE_URL = os.getenv('RASA_PARSE_URL', 'http://localhost:5005/model/parse')
ARTIFACTS_DIR = os.path.join('rasa-ui','shared_data','artifacts','smoke')
DECIDER_URL = os.getenv('DECIDER_URL', 'http://localhost:6009/decide')
ACTION_LOG = os.path.join('rasa-ui','shared_data','logs','action.log')

os.makedirs(ARTIFACTS_DIR, exist_ok=True)


def pick_questions(n=5):
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    # Try to bias a few questions towards timeseries/analytics style
    keywords = [
        'trend','average','mean','max','min','between','from','to','last','today',
        'temperature','humidity','co2','pm','pressure','air quality','flow'
    ]
    ts_like = [x for x in data if any(k in x['question'].lower() for k in keywords)]
    other = [x for x in data if x not in ts_like]
    sample = []
    if ts_like:
        sample.extend(random.sample(ts_like, k=min(3, len(ts_like))))
    if other:
        sample.extend(random.sample(other, k=max(0, n - len(sample))))
    if len(sample) < n and len(data) >= n:
        sample.extend(random.sample(data, k=n-len(sample)))
    return sample[:n]


def post_rasa_rest(text, sender='smoketest', timeout=60, retries=1):
    payload = {"sender": sender, "message": text}
    attempt = 0
    while True:
        try:
            r = requests.post(RASA_REST_URL, json=payload, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.ReadTimeout as e:
            if attempt < retries:
                attempt += 1
                time.sleep(2)
                timeout = min(timeout + 30, 180)
                continue
            raise


def parse_intent(text, timeout=30):
    r = requests.post(PARSE_URL, json={"text": text}, timeout=timeout)
    r.raise_for_status()
    return r.json()


def save_artifact(name, content):
    path = os.path.join(ARTIFACTS_DIR, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content if isinstance(content, str) else json.dumps(content, indent=2))
    return path


def main():
    sample = pick_questions(5)
    # Add crafted relative-date prompts to ensure coverage
    crafted = [
        {"question": "Show temperature trend today"},
        {"question": "CO2 average yesterday"},
        {"question": "Noise levels last week"},
        {"question": "Air quality last month"},
        {"question": "Give me readings until now"},
        {"question": "Humidity over the last 24 hours"},
        {"question": "PM levels over the past 7 days"},
        {"question": "CO readings for the last 30 days"},
        {"question": "Trend this week"},
        {"question": "Average this month"},
        {"question": "Noise last quarter"},
        {"question": "Air quality last year"},
        {"question": "Readings since 01/09/2025"},
        {"question": "Readings until 15/09/2025"},
        {"question": "Temperature over the previous 2 weeks"},
        {"question": "CO2 in the last 3 months"},
        {"question": "Humidity year to date"},
        {"question": "AQI quarter to date"},
        {"question": "Sound levels last weekend"},
    ]
    sample.extend(crafted)
    results = []
    for i, item in enumerate(sample, 1):
        q = item['question']
        print(f"\n[{i}] Q: {q}")
        intent = parse_intent(q)
        print("intent:", intent.get('intent',{}))
        sender_id = f"smoketest_{i}_{int(time.time())}"
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        try:
            rasa_msgs = post_rasa_rest(q, sender=sender_id, timeout=60, retries=1)
            print("messages count:", len(rasa_msgs))
            # Save raw convo transcript
            transcript_path = save_artifact(f"rest_{i}_{ts}.json", rasa_msgs)
            results.append({
                'question': q,
                'intent': intent.get('intent',{}),
                'messages_saved': transcript_path,
            })
        except Exception as e:
            err = f"ERROR posting to Rasa: {e}"
            print(err)
            transcript_path = save_artifact(f"rest_{i}_{ts}_error.txt", err)
            results.append({
                'question': q,
                'intent': intent.get('intent',{}),
                'error': str(e),
                'error_saved': transcript_path,
            })
            # Move on to next question
            continue
        # Look for any follow-up prompt for dates
        prompts = [m.get('text','') for m in rasa_msgs if isinstance(m, dict) and m.get('text')]
        if any(('start date' in p.lower()) or ('end date' in p.lower()) or ('please provide' in p.lower() and 'date' in p.lower()) for p in prompts):
            # reply with 'today' to exercise the special-case path
            reply = 'today'
            print("Replying with:", reply)
            rasa_msgs2 = post_rasa_rest(reply, sender=sender_id)
            save_artifact(f"rest_{i}_{ts}_reply.json", rasa_msgs2)
        # Ask bot to print date entities for visibility
        try:
            rasa_msgs3 = post_rasa_rest("/action_debug_entities", sender=sender_id, timeout=30, retries=0)
            save_artifact(f"rest_{i}_{ts}_debug.json", rasa_msgs3)
        except Exception as e:
            save_artifact(f"rest_{i}_{ts}_debug_error.txt", f"DEBUG ACTION ERROR: {e}")
        # Capture a short tail of action.log for each run to verify stages
        try:
            if os.path.exists(ACTION_LOG):
                with open(ACTION_LOG, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()[-200:]
                save_artifact(f"action_log_tail_{i}_{ts}.log", ''.join(lines))
        except Exception as e:
            print("Warning: couldn't read action.log:", e)
    # Save summary report
    save_artifact('summary.json', results)
    print("\nSmoke test complete. Artifacts saved under shared_data/artifacts/smoke")

if __name__ == '__main__':
    main()
