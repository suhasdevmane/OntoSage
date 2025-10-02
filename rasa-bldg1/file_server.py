import os
import mimetypes
import json
import datetime
from typing import Optional
from flask import Flask, request, abort, Response, send_file, make_response, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from werkzeug.utils import safe_join
import jwt
import subprocess
import time
import shutil
import glob
import io
import zipfile
import requests
from requests import exceptions as req_exc
import docker

ROOT_DIR = os.environ.get("ROOT_DIR", "/data")
RASA_HOST = os.environ.get("RASA_HOST", "rasa")
RASA_HTTP_PORT = int(os.environ.get("RASA_HTTP_PORT", "5005"))
RASA_BASE = f"http://{RASA_HOST}:{RASA_HTTP_PORT}"
app = Flask(__name__)

# Security / CORS config
JWT_SECRET = os.environ.get("JWT_SECRET", "dev_secret_change_me")
JWT_EXPIRES_DAYS = int(os.environ.get("JWT_EXPIRES_DAYS", "7"))
SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "false").lower() in ("1", "true", "yes")
# Control whether to auto-restart and hot-load model after training
AUTO_LOAD_AFTER_TRAIN = os.environ.get("AUTO_LOAD_AFTER_TRAIN", "true").lower() in ("1", "true", "yes")
# Support a single origin (FRONTEND_ORIGIN) or comma-separated list (ALLOWED_ORIGINS)
_origins_env = os.environ.get("ALLOWED_ORIGINS") or os.environ.get("FRONTEND_ORIGIN") or "http://localhost:3000"
ALLOWED_ORIGINS = {o.strip() for o in _origins_env.split(",") if o.strip()}

# In-memory training status (single job at a time)
TRAIN_STATUS = {
    "running": False,
    "step": "idle",
    "error": None,
    "model": None,
}

# In-memory action server restart jobs (multiple concurrent by id)
ACTION_JOBS = {}
RASA_START_JOBS = {}
TRAIN_JOBS = {}

def _new_action_job():
    jid = f"job-{int(time.time()*1000)}"
    ACTION_JOBS[jid] = {
        "running": True,
        "state": "starting",  # starting | stopping | starting_container | healthy | error
        "error": None,
        "logs": [],
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    return jid

def _append_action_log(job_id: str, message: str):
    job = ACTION_JOBS.get(job_id)
    if not job:
        return
    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    job["logs"].append(f"[{ts}] {message}")
    # Limit memory
    if len(job["logs"]) > 2000:
        job["logs"] = job["logs"][-2000:]
    job["updated_at"] = time.time()

def _new_rasa_start_job():
    jid = f"start-{int(time.time()*1000)}"
    RASA_START_JOBS[jid] = {
        "running": True,
        "state": "starting",  # starting | healthy | error
        "error": None,
        "logs": [],
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    return jid

def _append_rasa_start_log(job_id: str, message: str):
    job = RASA_START_JOBS.get(job_id)
    if not job:
        return
    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    job["logs"].append(f"[{ts}] {message}")
    if len(job["logs"]) > 2000:
        job["logs"] = job["logs"][-2000:]
    job["updated_at"] = time.time()

def _new_train_job():
    jid = f"train-{int(time.time()*1000)}"
    TRAIN_JOBS[jid] = {
        "running": True,
        "state": "starting",  # starting | stopping_rasa | training | training_done | starting_rasa | rasa_ready | loading_model | done | error
        "error": None,
        "logs": [],
        "model": None,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    return jid

def _append_train_log(job_id: str, message: str):
    job = TRAIN_JOBS.get(job_id)
    if not job:
        return
    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    job["logs"].append(f"[{ts}] {message}")
    if len(job["logs"]) > 4000:
        job["logs"] = job["logs"][-4000:]
    job["updated_at"] = time.time()

def _set_train_status(step: str, **kwargs):
    TRAIN_STATUS.update({"step": step, **kwargs})

def _begin_train_status():
    TRAIN_STATUS.update({"running": True, "step": "starting", "error": None, "model": None})

def _end_train_status(error: Optional[str] = None, model: Optional[str] = None):
    TRAIN_STATUS.update({
        "running": False,
        "step": "error" if error else "done",
        "error": error,
        "model": model,
    })


def add_cors(resp):
    origin = request.headers.get("Origin")
    if origin and ("*" in ALLOWED_ORIGINS or origin in ALLOWED_ORIGINS):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Credentials"] = "true"
    else:
        # Fallback for non-credentialed requests (no Origin) like direct file fetches
        resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS, POST"
    resp.headers["Access-Control-Allow-Headers"] = "Range, Content-Type, Origin, Accept, Authorization, X-CSRF-Token"
    resp.headers["Access-Control-Expose-Headers"] = "Content-Range"
    return resp


@app.after_request
def after_request(resp):
    return add_cors(resp)


@app.route("/health")
def health():
    return {"status": "ok"}, 200


# -----------------------------
# Simple Auth and History Store
# -----------------------------
DB_PATH = os.path.join(ROOT_DIR, "auth", "users.db")
ARTIFACTS_ROOT = os.path.join(ROOT_DIR, "artifacts")
# Point to mounted Rasa project inside this container for optional local train
RASA_PROJECT_ROOT = os.environ.get("RASA_PROJECT_ROOT", "/srv/rasa")
RASA_MODELS_DIR = os.path.join(RASA_PROJECT_ROOT, "models")
ALLOW_LOCAL_RASA_TRAIN = os.environ.get("ALLOW_LOCAL_RASA_TRAIN", "false").lower() in ("1", "true", "yes")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(ARTIFACTS_ROOT, exist_ok=True)


def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def sanitize_username(name: str) -> str:
    # Keep alnum, dash, underscore
    return "".join(c for c in name if c.isalnum() or c in ("-", "_"))[:64]


def create_token(username: str) -> str:
    now = datetime.datetime.utcnow()
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + datetime.timedelta(days=JWT_EXPIRES_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def get_user_from_request() -> Optional[str]:
    token = request.cookies.get("auth") or None
    if not token:
        # Optional: support Authorization: Bearer <token>
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
    if not token:
        return None
    try:
        decoded = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return sanitize_username(decoded.get("sub") or "") or None
    except Exception:
        return None


@app.route("/api/register", methods=["POST"])
def api_register():
    init_db()
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify({"error": "username and password required"}), 400
    username = sanitize_username(username)
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, generate_password_hash(password)))
        conn.commit()
        conn.close()
        # Ensure user artifact folder exists
        os.makedirs(os.path.join(ARTIFACTS_ROOT, username), exist_ok=True)
        resp = jsonify({"ok": True, "username": username})
        token = create_token(username)
        resp.set_cookie(
            "auth",
            token,
            httponly=True,
            secure=SECURE_COOKIES,
            samesite="Lax",
            path="/",
            max_age=JWT_EXPIRES_DAYS * 24 * 60 * 60,
        )
        return resp, 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "username already exists"}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/login", methods=["POST"])
def api_login():
    init_db()
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify({"error": "username and password required"}), 400
    username = sanitize_username(username)
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT password_hash FROM users WHERE username=?", (username,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return jsonify({"error": "invalid credentials"}), 401
        if not check_password_hash(row[0], password):
            return jsonify({"error": "invalid credentials"}), 401
        # Ensure user artifact folder exists
        os.makedirs(os.path.join(ARTIFACTS_ROOT, username), exist_ok=True)
        resp = jsonify({"ok": True, "username": username})
        token = create_token(username)
        resp.set_cookie(
            "auth",
            token,
            httponly=True,
            secure=SECURE_COOKIES,
            samesite="Lax",
            path="/",
            max_age=JWT_EXPIRES_DAYS * 24 * 60 * 60,
        )
        return resp, 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def user_history_path(username: str) -> str:
    return os.path.join(ARTIFACTS_ROOT, username, "chat_history.json")


@app.route("/api/me", methods=["GET"]) 
def api_me():
    user = get_user_from_request()
    if not user:
        return jsonify({"authenticated": False}), 200
    return jsonify({"authenticated": True, "username": user}), 200


@app.route("/api/get_history", methods=["GET"])
def api_get_history():
    username = get_user_from_request()
    if not username:
        return jsonify({"error": "unauthorized"}), 401
    path = user_history_path(username)
    if not os.path.exists(path):
        return jsonify({"messages": []})
    try:
        with open(path, "r", encoding="utf-8") as f:
            return jsonify(json.loads(f.read()))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/save_history", methods=["POST"])
def api_save_history():
    data = request.get_json(silent=True) or {}
    username = get_user_from_request()
    if not username:
        return jsonify({"error": "unauthorized"}), 401
    messages = data.get("messages")
    if not isinstance(messages, list):
        return jsonify({"error": "messages[] required"}), 400
    try:
        user_dir = os.path.join(ARTIFACTS_ROOT, username)
        os.makedirs(user_dir, exist_ok=True)
        with open(user_history_path(username), "w", encoding="utf-8") as f:
            f.write(json.dumps({"messages": messages}, ensure_ascii=False, indent=2))
        return jsonify({"ok": True}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/logout", methods=["POST"])
def api_logout():
    # Clear the auth cookie
    resp = jsonify({"ok": True})
    resp.set_cookie("auth", "", expires=0, path="/")
    return resp, 200


def _latest_model_path(models_dir: str) -> Optional[str]:
    try:
        candidates = sorted(glob.glob(os.path.join(models_dir, "*.tar.gz")), key=os.path.getmtime, reverse=True)
        return candidates[0] if candidates else None
    except Exception:
        return None


def _docker_client():
    try:
        return docker.from_env()
    except Exception as e:
        raise RuntimeError(f"docker client init failed: {e}")


def _rasa_container(client):
    # Prefer compose label match, then name
    for c in client.containers.list(all=True):
        try:
            labels = c.labels or {}
            if labels.get('com.docker.compose.service') == 'rasa':
                return c
        except Exception:
            pass
        if c.name == 'rasa_container':
            return c
        try:
            if 'rasa/rasa' in (c.image.tags[0] if c.image.tags else ''):
                return c
        except Exception:
            pass
    return None


def _http_server_container(client):
    for c in client.containers.list(all=True):
        try:
            labels = c.labels or {}
            if labels.get('com.docker.compose.service') == 'http_server':
                return c
        except Exception:
            pass
        if c.name == 'http_server_container':
            return c
    return None

def _action_server_container(client):
    for c in client.containers.list(all=True):
        try:
            labels = c.labels or {}
            if labels.get('com.docker.compose.service') == 'action_server':
                return c
        except Exception:
            pass
        if c.name == 'action_server_container':
            return c
    return None


def _rasa_train_template(client):
    for c in client.containers.list(all=True):
        # Service created in compose named 'rasa-train' with container_name 'rasa_train_template'
        try:
            labels = c.labels or {}
            if labels.get('com.docker.compose.service') == 'rasa-train':
                return c
        except Exception:
            pass
        if c.name == 'rasa_train_template':
            return c
    return None


def _container_ip_on_network(container, prefer_suffix: str = "_ontobot-network") -> Optional[str]:
    try:
        nets = container.attrs.get('NetworkSettings', {}).get('Networks', {})
        # Prefer compose-created network that ends with suffix, else any
        for name, info in nets.items():
            if name.endswith(prefer_suffix):
                return info.get('IPAddress')
        for name, info in nets.items():
            ip = info.get('IPAddress')
            if ip:
                return ip
    except Exception:
        pass
    return None


def _rasa_base_candidates(rasa_ct) -> list:
    candidates = []
    try:
        ip = _container_ip_on_network(rasa_ct)
        if ip:
            candidates.append(f"http://{ip}:{RASA_HTTP_PORT}")
    except Exception:
        pass
    # Always include DNS name last
    candidates.append(RASA_BASE)
    return candidates

def _container_health_status(container) -> str:
    try:
        container.reload()
        state = container.attrs.get('State', {})
        health = state.get('Health', {})
        return (health.get('Status') or state.get('Status') or '').lower()
    except Exception:
        return ''

def _restart_action_server_job(job_id: str, timeout: int = 300):
    try:
        client = _docker_client()
        ct = _action_server_container(client)
        if not ct:
            _append_action_log(job_id, "action_server container not found")
            ACTION_JOBS[job_id].update({"running": False, "state": "error", "error": "container not found"})
            return
        ACTION_JOBS[job_id]["state"] = "stopping"
        _append_action_log(job_id, f"Stopping container {ct.name}…")
        try:
            ct.reload()
            if ct.status in ("running", "restarting"):
                ct.stop(timeout=20)
                _append_action_log(job_id, "Stopped.")
        except Exception as e:
            _append_action_log(job_id, f"Stop error (continuing): {e}")

        ACTION_JOBS[job_id]["state"] = "starting_container"
        _append_action_log(job_id, "Starting container…")
        try:
            ct.start()
        except Exception as e:
            _append_action_log(job_id, f"Start error: {e}")
            ACTION_JOBS[job_id].update({"running": False, "state": "error", "error": str(e)})
            return

        # Wait for healthy or running
        start_time = time.time()
        last_health = ''
        while time.time() - start_time < timeout:
            hs = _container_health_status(ct)
            if hs and hs != last_health:
                _append_action_log(job_id, f"Health: {hs}")
                last_health = hs
            ct.reload()
            if hs == 'healthy' or ct.status == 'running':
                break
            time.sleep(1)

        hs = _container_health_status(ct)
        if hs == 'healthy' or ct.status == 'running':
            ACTION_JOBS[job_id].update({"running": False, "state": "healthy"})
            _append_action_log(job_id, "Action server is up.")
            try:
                logs = ct.logs(tail=200).decode('utf-8', errors='ignore')
                if logs:
                    for line in logs.splitlines():
                        _append_action_log(job_id, f"[container] {line}")
            except Exception:
                pass
        else:
            ACTION_JOBS[job_id].update({"running": False, "state": "error", "error": f"timed out waiting for healthy (status={ct.status}, health={hs})"})
            _append_action_log(job_id, "Timed out waiting for healthy.")
    except Exception as e:
        ACTION_JOBS[job_id].update({"running": False, "state": "error", "error": str(e)})
        _append_action_log(job_id, f"Unexpected error: {e}")


@app.route("/api/action_server/restart", methods=["POST"])
def api_action_server_restart():
    username = get_user_from_request()
    if not username:
        return jsonify({"error": "unauthorized"}), 401
    jid = _new_action_job()
    _append_action_log(jid, f"User {username} requested action server restart")
    # fire background thread
    import threading
    t = threading.Thread(target=_restart_action_server_job, args=(jid,), daemon=True)
    t.start()
    return jsonify({"ok": True, "jobId": jid}), 202


@app.route("/api/action_server/restart/<job_id>/status", methods=["GET"])
def api_action_server_restart_status(job_id: str):
    username = get_user_from_request()
    if not username:
        return jsonify({"error": "unauthorized"}), 401
    job = ACTION_JOBS.get(job_id)
    if not job:
        return jsonify({"error": "unknown jobId"}), 404
    # Return tail of logs (join)
    tail = "\n".join(job.get("logs", [])[-1000:])
    return jsonify({
        "running": job.get("running", False),
        "state": job.get("state"),
        "error": job.get("error"),
        "updatedAt": int(job.get("updated_at", time.time())*1000),
        "logs": tail,
    }), 200


@app.route("/api/rasa/models", methods=["GET"])
def api_rasa_models():
    """List available models and which is currently loaded."""
    username = get_user_from_request()
    if not username:
        return jsonify({"error": "unauthorized"}), 401
    os.makedirs(RASA_MODELS_DIR, exist_ok=True)
    models = []
    for p in sorted(glob.glob(os.path.join(RASA_MODELS_DIR, "*.tar.gz")), key=os.path.getmtime, reverse=True):
        models.append({
            "name": os.path.basename(p),
            "mtime": int(os.path.getmtime(p)),
            "size": os.path.getsize(p),
        })
    # Try to detect currently loaded model via Rasa /model endpoint
    try:
        r = requests.get(f"{RASA_BASE}/model", timeout=5)
        current = None
        if r.status_code == 200 and r.content:
            # If server returns binary model when GET /model, we can't infer name; fall back to /status if available
            try:
                s = requests.get(f"{RASA_BASE}/status", timeout=5)
                if s.status_code == 200:
                    j = s.json()
                    current = j.get('model_file') or j.get('model')
            except Exception:
                pass
        else:
            # Some versions return JSON with info
            try:
                j = r.json()
                current = j.get('model') or j.get('path')
            except Exception:
                pass
    except Exception:
        current = None
    return jsonify({"models": models, "current": os.path.basename(current) if current else None})


@app.route("/api/rasa/models/select", methods=["POST"])
def api_rasa_models_select():
    username = get_user_from_request()
    if not username:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    model_name = data.get("model")
    # By default, restart Rasa so it boots with the selected model
    restart = data.get("restart", True)
    if not model_name:
        return jsonify({"error": "model is required"}), 400
    model_path = os.path.join(RASA_MODELS_DIR, os.path.basename(model_name))
    if not os.path.exists(model_path):
        return jsonify({"error": "model not found"}), 404
    try:
        client = _docker_client()
        rasa_ct = _rasa_container(client)
        if not rasa_ct:
            return jsonify({"error": "rasa container not found"}), 404
        shared_pin = "/data/pinned_model.txt"  # http_server mounts shared_data at /data; rasa mounts at /app/shared_data
        # Restart path: write pin and restart so start_rasa.sh loads it
        if restart:
            try:
                with open(shared_pin, "w", encoding="utf-8") as fh:
                    fh.write(os.path.basename(model_name))
            except Exception as e:
                return jsonify({"error": f"failed to write pin file: {e}"}), 500
        else:
            # Hot-load path: remove any existing pin to preserve default-latest-on-boot
            try:
                if os.path.exists(shared_pin):
                    os.remove(shared_pin)
            except Exception:
                pass
        # Restart if requested; otherwise ensure it's running
        try:
            rasa_ct.reload()
            if restart:
                if rasa_ct.status == 'running':
                    rasa_ct.stop(timeout=30)
                # Ensure docker updates status before starting again
                time.sleep(1)
                rasa_ct.reload()
        except Exception:
            pass
        # Ensure Rasa is running
        try:
            rasa_ct.reload()
            if rasa_ct.status != 'running':
                rasa_ct.start()
        except Exception:
            # Retry start once if needed
            try:
                rasa_ct.reload()
                if rasa_ct.status != 'running':
                    rasa_ct.start()
            except Exception as e:
                return jsonify({"error": f"failed to start rasa: {e}"}), 500
        # Wait for readiness up to 5 minutes with IP fallback
        start_ts = time.time()
        ready = False
        last_exc = None
        while time.time() - start_ts < 300:
            try:
                rasa_ct.reload()
                base_candidates = _rasa_base_candidates(rasa_ct)
                for base in base_candidates:
                    try:
                        r = requests.get(f"{base}/version", timeout=5)
                        if r.status_code == 200:
                            ready = True
                            break
                    except Exception as ie:
                        last_exc = ie
                if ready:
                    break
            except Exception as e:
                last_exc = e
            time.sleep(2)
        if not ready:
            return jsonify({"error": f"rasa not ready within timeout", "details": str(last_exc) if last_exc else None}), 504
        if restart:
            # Verify the pinned model is active via /status (allow up to 5 minutes)
            verify_deadline = time.time() + 300
            verified = False
            last_err = None
            while time.time() < verify_deadline and not verified:
                try:
                    bases = _rasa_base_candidates(rasa_ct)
                    for base in bases:
                        try:
                            st = requests.get(f"{base}/status", timeout=5)
                            if st.status_code == 200:
                                info = st.json()
                                loaded = info.get('model_file') or info.get('model') or ''
                                if os.path.basename(model_path) in str(loaded):
                                    verified = True
                                    break
                                last_err = f"loaded model mismatch: {loaded}"
                        except Exception as ie:
                            last_err = str(ie)
                    if verified:
                        break
                except Exception as e:
                    last_err = str(e)
                time.sleep(2)
            if verified:
                return jsonify({"ok": True, "model": os.path.basename(model_path), "restart": True, "verified": True})
            return jsonify({"error": last_err or "model not verified"}), 500
        else:
            # Hot-load selected model into running server via HTTP PUT /model
            last_err = None
            for base in _rasa_base_candidates(rasa_ct):
                try:
                    with open(model_path, "rb") as fh:
                        files = {"model": (os.path.basename(model_path), fh, "application/gzip")}
                        lr = requests.put(f"{base}/model", files=files, timeout=300)
                        if lr.status_code in (200, 204):
                            # Verify via /status (allow up to 5 minutes)
                            verify_deadline = time.time() + 300
                            verified = False
                            while time.time() < verify_deadline and not verified:
                                try:
                                    st = requests.get(f"{base}/status", timeout=5)
                                    if st.status_code == 200:
                                        info = st.json()
                                        loaded = info.get('model_file') or info.get('model') or ''
                                        if os.path.basename(model_path) in str(loaded):
                                            verified = True
                                            break
                                except Exception:
                                    pass
                                time.sleep(2)
                            return jsonify({
                                "ok": True,
                                "model": os.path.basename(model_path),
                                "restart": False,
                                "verified": verified
                            })
                        last_err = f"model load failed: {lr.status_code} {lr.text}"
                except Exception as ie:
                    last_err = str(ie)
            return jsonify({"error": last_err or "unknown error"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/rasa/models/delete", methods=["POST"])
def api_rasa_models_delete():
    """Delete a model tar.gz from the models directory. Prevent deleting the currently loaded model."""
    username = get_user_from_request()
    if not username:
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    model_name = data.get("model")
    if not model_name:
        return jsonify({"error": "model is required"}), 400
    model_path = os.path.join(RASA_MODELS_DIR, os.path.basename(model_name))
    if not os.path.exists(model_path):
        return jsonify({"error": "model not found"}), 404

    # Detect currently loaded model via Rasa /status
    current = None
    try:
        client = _docker_client()
        rasa_ct = _rasa_container(client)
        bases = _rasa_base_candidates(rasa_ct) if rasa_ct else [RASA_BASE]
        for base in bases:
            try:
                s = requests.get(f"{base}/status", timeout=5)
                if s.status_code == 200:
                    j = s.json()
                    current = j.get('model_file') or j.get('model')
                    break
            except Exception:
                continue
    except Exception:
        pass
    if current and os.path.basename(model_path) in os.path.basename(str(current)):
        return jsonify({"error": "cannot delete the currently loaded model"}), 409

    try:
        os.remove(model_path)
        return jsonify({"ok": True, "deleted": os.path.basename(model_path)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/rasa/train_job", methods=["POST"])
def api_rasa_train_job():
    """Stop Rasa, run one-off training (compose-like), then start Rasa and load latest model."""
    username = get_user_from_request()
    if not username:
        return jsonify({"error": "unauthorized"}), 401
    if TRAIN_STATUS.get("running"):
        return jsonify({"error": "training already in progress", "status": TRAIN_STATUS}), 409
    _begin_train_status()
    job_start_ts = time.time()
    # Snapshot current latest model to verify new artifact is created by this run
    prev_latest = _latest_model_path(RASA_MODELS_DIR)
    prev_latest_mtime = os.path.getmtime(prev_latest) if prev_latest and os.path.exists(prev_latest) else 0
    # Use docker socket to orchestrate
    try:
        client = _docker_client()
    except Exception as e:
        _end_train_status(error=str(e))
        return jsonify({"error": str(e), "hint": "ensure /var/run/docker.sock is mounted and docker pkg installed"}), 500

    # Stop rasa container if running
    try:
        rasa_ct = _rasa_container(client)
        _set_train_status("stopping_rasa")
        if rasa_ct and rasa_ct.status == 'running':
            rasa_ct.stop(timeout=30)
        _set_train_status("rasa_stopped")
    except Exception as e:
        _end_train_status(error=f"failed to stop rasa: {e}")
        return jsonify({"error": f"failed to stop rasa: {e}"}), 500

    # Run training job (prefer reusing rasa_train_template if present)
    training_error = None
    logs_tail = ''
    try:
        tmpl = _rasa_train_template(client)
        if tmpl:
            _set_train_status("training")
            # Ensure it's not running, then start and wait
            try:
                if tmpl.status == 'running':
                    tmpl.stop(timeout=10)
            except Exception:
                pass
            # If the template was created by compose with user root (as configured), just start.
            # If not, and start fails due to permissions, we will recreate below.
            try:
                tmpl.start()
            except Exception:
                try:
                    tmpl.remove(force=True)
                except Exception:
                    pass
                # Recreate template as root
                http_ct = _http_server_container(client)
                if not http_ct:
                    raise RuntimeError('http_server container not found for volumes_from while recreating template')
                tmpl = client.containers.run(
                    image='rasa/rasa:3.6.12-full',
                    name='rasa_train_template',
                    command=['train', '--config', '/srv/rasa/config.yml', '--domain', '/srv/rasa/domain.yml', '--data', '/srv/rasa/data', '--out', '/srv/rasa/models'],
                    working_dir='/srv/rasa',
                    detach=True,
                    volumes_from=[http_ct.id],
                    user='root',
                    remove=False,
                    environment={}
                )
            exit_code = tmpl.wait(timeout=3600).get('StatusCode')
            try:
                logs_tail = tmpl.logs().decode('utf-8', errors='ignore')
            except Exception:
                logs_tail = tmpl.logs(tail=2000).decode('utf-8', errors='ignore')
            if exit_code != 0:
                training_error = f"training job failed (template) with exit {exit_code}"
        else:
            # Fallback: ephemeral container with volumes_from http_server
            http_ct = _http_server_container(client)
            if not http_ct:
                training_error = "http_server container not found for volumes_from"
            else:
                # Use root to avoid PermissionError on creating .rasa in working directory
                job = client.containers.run(
                    image='rasa/rasa:3.6.12-full',
                    name=f"rasa_train_job_{int(time.time())}",
                    command=['train', '--config', '/srv/rasa/config.yml', '--domain', '/srv/rasa/domain.yml', '--data', '/srv/rasa/data', '--out', '/srv/rasa/models'],
                    working_dir='/srv/rasa',
                    detach=True,
                    volumes_from=[http_ct.id],
                    user='root',
                    remove=True,
                    environment={}
                )
                _set_train_status("training")
                exit_code = job.wait(timeout=3600).get('StatusCode')
                try:
                    logs_tail = job.logs().decode('utf-8', errors='ignore')
                except Exception:
                    logs_tail = job.logs(tail=2000).decode('utf-8', errors='ignore')
                if exit_code != 0:
                    training_error = f"training job failed with exit {exit_code}"
    except Exception as e:
        training_error = f"failed to run training job: {e}"

    # Find latest model produced by this run
    model_path = _latest_model_path(RASA_MODELS_DIR)
    model_mtime = os.path.getmtime(model_path) if model_path and os.path.exists(model_path) else 0
    # Require a new model (newer timestamp or different filename) to consider training successful
    produced_new_model = bool(model_path) and os.path.exists(model_path) and (
        (model_mtime > max(prev_latest_mtime, job_start_ts - 2)) or (prev_latest and os.path.basename(model_path) != os.path.basename(prev_latest)) or (not prev_latest)
    )
    if not produced_new_model:
        if training_error is None:
            training_error = "no new model produced by training job"

    # If auto-load is disabled, finish here after saving the model.
    if not AUTO_LOAD_AFTER_TRAIN:
        if training_error:
            _end_train_status(error=training_error)
            return jsonify({"error": training_error, "logs": logs_tail[-2000:]}), 500
        # Safety: ensure we have a valid model_path
        if not (model_path and os.path.exists(model_path)):
            _end_train_status(error="training finished but model missing")
            return jsonify({"error": "training finished but model missing", "logs": logs_tail[-2000:]}), 500
        _end_train_status(model=os.path.basename(model_path))
        return jsonify({"ok": True, "strategy": "job", "model": os.path.basename(model_path), "auto_load": False})

    # Start rasa back up (always attempt)
    start_err = None
    rasa_base = RASA_BASE
    try:
        rasa_ct = _rasa_container(client) or rasa_ct
        if rasa_ct:
            rasa_ct.start()
            _set_train_status("starting_rasa")
            # Wait for readiness
            start_ts = time.time()
            while time.time() - start_ts < 300:
                try:
                    # refresh attrs to get current IP
                    rasa_ct.reload()
                    ip = _container_ip_on_network(rasa_ct)
                    if ip:
                        rasa_base = f"http://{ip}:{RASA_HTTP_PORT}"
                    else:
                        rasa_base = RASA_BASE
                    vr = requests.get(f"{rasa_base}/version", timeout=5)
                    if vr.status_code == 200:
                        _set_train_status("rasa_ready")
                        break
                except Exception:
                    pass
                time.sleep(2)
            else:
                start_err = "rasa not ready within timeout"
    except Exception as e:
        start_err = f"failed to start rasa: {e}"

    # Decide response path
    if training_error:
        _end_train_status(error=training_error)
        return jsonify({"error": training_error, "logs": logs_tail[-2000:], "rasa_restart_error": start_err}), 500

    # Load the newly trained model
    try:
        files = {"model": (os.path.basename(model_path), open(model_path, "rb"), "application/gzip")}
        _set_train_status("loading_model")
        last_err = None
        for base in _rasa_base_candidates(rasa_ct) if rasa_ct else [rasa_base]:
            try:
                lr = requests.put(f"{base}/model", files=files, timeout=120)
                if lr.status_code in (200, 204):
                    _end_train_status(model=os.path.basename(model_path))
                    return jsonify({"ok": True, "strategy": "job", "model": os.path.basename(model_path)})
                last_err = f"model load failed: {lr.status_code} {lr.text}"
            except Exception as ee:
                last_err = str(ee)
        _end_train_status(error=last_err or "unknown error")
        return jsonify({"error": last_err or "unknown error"}), 500
    except Exception as e:
        _end_train_status(error=str(e))
        return jsonify({"error": str(e)}), 500


def _run_training_job_with_logs(job_id: str):
    try:
        client = _docker_client()
    except Exception as e:
        TRAIN_JOBS[job_id].update({"running": False, "state": "error", "error": str(e)})
        _append_train_log(job_id, f"docker client init failed: {e}")
        return

    # Stop rasa if running
    try:
        rasa_ct = _rasa_container(client)
        TRAIN_JOBS[job_id]["state"] = "stopping_rasa"
        if rasa_ct and rasa_ct.status == 'running':
            rasa_ct.stop(timeout=30)
        TRAIN_JOBS[job_id]["state"] = "training"
    except Exception as e:
        TRAIN_JOBS[job_id].update({"running": False, "state": "error", "error": f"failed to stop rasa: {e}"})
        _append_train_log(job_id, f"failed to stop rasa: {e}")
        return

    # Run training (reuse template if exists else ephemeral)
    training_error = None
    try:
        tmpl = _rasa_train_template(client)
        if tmpl:
            try:
                if tmpl.status == 'running':
                    tmpl.stop(timeout=10)
            except Exception:
                pass
            try:
                tmpl.start()
            except Exception:
                http_ct = _http_server_container(client)
                if not http_ct:
                    training_error = "http_server container not found for volumes_from"
                else:
                    try:
                        tmpl.remove(force=True)
                    except Exception:
                        pass
                    tmpl = client.containers.run(
                        image='rasa/rasa:3.6.12-full',
                        name='rasa_train_template',
                        command=['train', '--config', '/srv/rasa/config.yml', '--domain', '/srv/rasa/domain.yml', '--data', '/srv/rasa/data', '--out', '/srv/rasa/models'],
                        working_dir='/srv/rasa',
                        detach=True,
                        volumes_from=[http_ct.id],
                        user='root',
                        remove=False,
                        environment={}
                    )
            # Stream logs while waiting for completion
            try:
                for line in tmpl.logs(stream=True, follow=True):
                    try:
                        txt = line.decode('utf-8', errors='ignore') if isinstance(line, (bytes, bytearray)) else str(line)
                        if txt.strip():
                            _append_train_log(job_id, f"[train] {txt.strip()}")
                    except Exception:
                        pass
            except Exception:
                pass
            exit_code = tmpl.wait(timeout=3600).get('StatusCode')
            if exit_code != 0:
                training_error = f"training job failed (template) with exit {exit_code}"
        else:
            http_ct = _http_server_container(client)
            if not http_ct:
                training_error = "http_server container not found for volumes_from"
            else:
                job = client.containers.run(
                    image='rasa/rasa:3.6.12-full',
                    name=f"rasa_train_job_{int(time.time())}",
                    command=['train', '--config', '/srv/rasa/config.yml', '--domain', '/srv/rasa/domain.yml', '--data', '/srv/rasa/data', '--out', '/srv/rasa/models'],
                    working_dir='/srv/rasa',
                    detach=True,
                    volumes_from=[http_ct.id],
                    user='root',
                    remove=True,
                    environment={}
                )
                # Stream logs while waiting
                while True:
                    try:
                        for line in job.logs(stream=True, follow=True):
                            try:
                                txt = line.decode('utf-8', errors='ignore') if isinstance(line, (bytes, bytearray)) else str(line)
                                if txt.strip():
                                    _append_train_log(job_id, f"[train] {txt.strip()}")
                            except Exception:
                                pass
                            TRAIN_JOBS[job_id]["updated_at"] = time.time()
                    except Exception:
                        # break when container stops
                        break
                    time.sleep(1)
                exit_code = job.wait(timeout=3600).get('StatusCode')
                if exit_code != 0:
                    training_error = f"training job failed with exit {exit_code}"
    except Exception as e:
        training_error = f"failed to run training job: {e}"

    # Find latest model
    model_path = _latest_model_path(RASA_MODELS_DIR)
    if not model_path or not os.path.exists(model_path):
        if training_error is None:
            training_error = "no model produced by training job"

    if training_error:
        TRAIN_JOBS[job_id].update({"running": False, "state": "error", "error": training_error})
        _append_train_log(job_id, training_error)
        return

    # Start rasa back up and load model
    TRAIN_JOBS[job_id]["state"] = "starting_rasa"
    rasa_base = RASA_BASE
    start_err = None
    try:
        rasa_ct = _rasa_container(client)
        if rasa_ct:
            rasa_ct.start()
            TRAIN_JOBS[job_id]["state"] = "rasa_ready"
            start_ts = time.time()
            while time.time() - start_ts < 300:
                try:
                    rasa_ct.reload()
                    ip = _container_ip_on_network(rasa_ct)
                    rasa_base = f"http://{ip}:{RASA_HTTP_PORT}" if ip else RASA_BASE
                    vr = requests.get(f"{rasa_base}/version", timeout=5)
                    if vr.status_code == 200:
                        break
                except Exception:
                    pass
                time.sleep(2)
        else:
            start_err = "rasa container not found"
    except Exception as e:
        start_err = f"failed to start rasa: {e}"

    # Load model into Rasa
    if start_err:
        TRAIN_JOBS[job_id].update({"running": False, "state": "error", "error": start_err})
        _append_train_log(job_id, start_err)
        return
    try:
        TRAIN_JOBS[job_id]["state"] = "loading_model"
        with open(model_path, "rb") as fh:
            files = {"model": (os.path.basename(model_path), fh, "application/gzip")}
            lr = requests.put(f"{rasa_base}/model", files=files, timeout=300)
            if lr.status_code in (200, 204):
                TRAIN_JOBS[job_id].update({"running": False, "state": "done", "model": os.path.basename(model_path)})
                _append_train_log(job_id, f"Model loaded: {os.path.basename(model_path)}")
                return
        TRAIN_JOBS[job_id].update({"running": False, "state": "error", "error": f"model load failed: {lr.status_code} {lr.text}"})
        _append_train_log(job_id, f"model load failed: {lr.status_code} {lr.text}")
    except Exception as e:
        TRAIN_JOBS[job_id].update({"running": False, "state": "error", "error": str(e)})
        _append_train_log(job_id, f"Unexpected error: {e}")


@app.route("/api/rasa/train_job2", methods=["POST"])
def api_rasa_train_job2():
    """Like train_job, but with log streaming that the frontend can poll."""
    username = get_user_from_request()
    if not username:
        return jsonify({"error": "unauthorized"}), 401
    jid = _new_train_job()
    _append_train_log(jid, f"User {username} requested training job")
    import threading
    t = threading.Thread(target=_run_training_job_with_logs, args=(jid,), daemon=True)
    t.start()
    return jsonify({"ok": True, "jobId": jid}), 202


@app.route("/api/rasa/train_job2/<job_id>/status", methods=["GET"])
def api_rasa_train_job2_status(job_id: str):
    username = get_user_from_request()
    if not username:
        return jsonify({"error": "unauthorized"}), 401
    job = TRAIN_JOBS.get(job_id)
    if not job:
        return jsonify({"error": "unknown jobId"}), 404
    tail = "\n".join(job.get("logs", [])[-1200:])
    return jsonify({
        "running": job.get("running", False),
        "state": job.get("state"),
        "error": job.get("error"),
        "model": job.get("model"),
        "updatedAt": int(job.get("updated_at", time.time())*1000),
        "logs": tail,
    }), 200


@app.route("/api/rasa/start", methods=["POST"])
def api_rasa_start():
    username = get_user_from_request()
    if not username:
        return jsonify({"error": "unauthorized"}), 401
    try:
        client = _docker_client()
        rasa_ct = _rasa_container(client)
        if not rasa_ct:
            return jsonify({"error": "rasa container not found"}), 404
        try:
            rasa_ct.reload()
        except Exception:
            pass
        if rasa_ct.status != 'running':
            rasa_ct.start()
        # Wait up to 5 minutes; on each retry, reload container and try IP and DNS bases
        start_ts = time.time()
        while time.time() - start_ts < 300:
            try:
                try:
                    rasa_ct.reload()
                except Exception:
                    pass
                bases = _rasa_base_candidates(rasa_ct) if rasa_ct else [RASA_BASE]
                for base in bases:
                    try:
                        r = requests.get(f"{base}/version", timeout=5)
                        if r.status_code == 200:
                            return jsonify({"ok": True})
                    except Exception:
                        continue
            except Exception:
                pass
            time.sleep(2)
        return jsonify({"error": "rasa not ready within timeout"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _start_rasa_job(job_id: str, timeout: int = 300):
    try:
        client = _docker_client()
        rasa_ct = _rasa_container(client)
        if not rasa_ct:
            RASA_START_JOBS[job_id].update({"running": False, "state": "error", "error": "container not found"})
            _append_rasa_start_log(job_id, "Rasa container not found")
            return
        # Try starting if not running
        try:
            rasa_ct.reload()
        except Exception:
            pass
        if rasa_ct.status != 'running':
            _append_rasa_start_log(job_id, "Starting Rasa container…")
            try:
                rasa_ct.start()
            except Exception as e:
                RASA_START_JOBS[job_id].update({"running": False, "state": "error", "error": str(e)})
                _append_rasa_start_log(job_id, f"Failed to start container: {e}")
                return

        # Poll readiness and stream recent logs
        start_ts = time.time()
        last_log_ts = 0.0
        while time.time() - start_ts < timeout:
            try:
                try:
                    rasa_ct.reload()
                except Exception:
                    pass
                # check health via /version using best-guess base candidates
                bases = _rasa_base_candidates(rasa_ct) if rasa_ct else [RASA_BASE]
                healthy = False
                for base in bases:
                    try:
                        r = requests.get(f"{base}/version", timeout=3)
                        if r.status_code == 200:
                            healthy = True
                            break
                    except Exception:
                        continue

                # append container logs tail periodically
                try:
                    logs = rasa_ct.logs(since=int(last_log_ts) or None, tail=50)
                    if isinstance(logs, bytes):
                        txt = logs.decode('utf-8', errors='ignore')
                    else:
                        txt = str(logs)
                    if txt:
                        for line in txt.splitlines():
                            if line.strip():
                                _append_rasa_start_log(job_id, f"[container] {line}")
                    last_log_ts = time.time()
                except Exception:
                    pass

                if healthy:
                    RASA_START_JOBS[job_id].update({"running": False, "state": "healthy"})
                    _append_rasa_start_log(job_id, "Rasa is healthy.")
                    return
            except Exception as e:
                RASA_START_JOBS[job_id].update({"running": False, "state": "error", "error": str(e)})
                _append_rasa_start_log(job_id, f"Unexpected error: {e}")
                return
            time.sleep(2)

        # timeout
        RASA_START_JOBS[job_id].update({"running": False, "state": "error", "error": "timed out waiting for healthy"})
        _append_rasa_start_log(job_id, "Timed out waiting for healthy.")
    except Exception as e:
        RASA_START_JOBS[job_id].update({"running": False, "state": "error", "error": str(e)})
        _append_rasa_start_log(job_id, f"Unexpected error: {e}")


@app.route("/api/rasa/start_job", methods=["POST"])
def api_rasa_start_job():
    username = get_user_from_request()
    if not username:
        return jsonify({"error": "unauthorized"}), 401
    jid = _new_rasa_start_job()
    _append_rasa_start_log(jid, f"User {username} requested Rasa start")
    import threading
    t = threading.Thread(target=_start_rasa_job, args=(jid,), daemon=True)
    t.start()
    return jsonify({"ok": True, "jobId": jid}), 202


@app.route("/api/rasa/start_job/<job_id>/status", methods=["GET"])
def api_rasa_start_job_status(job_id: str):
    username = get_user_from_request()
    if not username:
        return jsonify({"error": "unauthorized"}), 401
    job = RASA_START_JOBS.get(job_id)
    if not job:
        return jsonify({"error": "unknown jobId"}), 404
    tail = "\n".join(job.get("logs", [])[-1000:])
    return jsonify({
        "running": job.get("running", False),
        "state": job.get("state"),
        "error": job.get("error"),
        "updatedAt": int(job.get("updated_at", time.time())*1000),
        "logs": tail,
    }), 200


@app.route("/api/rasa/stop", methods=["POST"])
def api_rasa_stop():
    username = get_user_from_request()
    if not username:
        return jsonify({"error": "unauthorized"}), 401
    try:
        client = _docker_client()
        rasa_ct = _rasa_container(client)
        if not rasa_ct:
            return jsonify({"error": "rasa container not found"}), 404
        if rasa_ct.status == 'running':
            rasa_ct.stop(timeout=30)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/rasa/train_job/status", methods=["GET"])
def api_rasa_train_job_status():
    """Return coarse-grained training status for UI polling."""
    username = get_user_from_request()
    if not username:
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(TRAIN_STATUS)


@app.route("/api/rasa/train", methods=["POST"])
def api_rasa_train():
    """
    Trigger a Rasa model training and hot-load it into the running Rasa server.
    Two strategies supported:
      1) Remote train via Rasa HTTP API /model/train (preferred when rasa service is running)
      2) Local train by invoking `rasa train` if project is mounted (fallback)
    Requires authentication cookie.
    """
    username = get_user_from_request()
    if not username:
        return jsonify({"error": "unauthorized"}), 401

    # Ensure models dir exists
    os.makedirs(RASA_MODELS_DIR, exist_ok=True)

    # Ensure Rasa API is reachable (poll /version briefly)
    train_url = f"{RASA_BASE}/model/train"
    load_url = f"{RASA_BASE}/model"
    version_url = f"{RASA_BASE}/version"

    # Small readiness wait (up to ~30s)
    ready = False
    start_ts = time.time()
    while time.time() - start_ts < 30:
        try:
            vr = requests.get(version_url, timeout=5)
            if vr.status_code == 200:
                ready = True
                break
        except Exception:
            pass
        time.sleep(2)
    if not ready:
        return jsonify({
            "error": "rasa service not ready",
            "hint": f"could not reach {version_url}; ensure the 'rasa' container is healthy and port 5005 is up",
        }), 503

    # Try remote train first (zip project and upload)
    try:
        # Build a zip of the Rasa project: config.yml, domain.yml, data/**
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            # config.yml and domain.yml at root
            for fname in ("config.yml", "domain.yml"):
                fpath = os.path.join(RASA_PROJECT_ROOT, fname)
                if os.path.exists(fpath):
                    zf.write(fpath, arcname=fname)
            # data directory recursively
            data_dir = os.path.join(RASA_PROJECT_ROOT, "data")
            for root, dirs, files in os.walk(data_dir):
                for f in files:
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, RASA_PROJECT_ROOT)
                    zf.write(full, arcname=rel)
        buf.seek(0)

        # Preferred: send ZIP as raw body so Rasa doesn't try to decode as UTF-8 YAML
        buf.seek(0)
        r = requests.post(
            train_url,
            params={"force_training": "true", "save_to_default_model_directory": "true"},
            data=buf.getvalue(),
            headers={"Content-Type": "application/zip", "Accept": "application/octet-stream"},
            timeout=1800,
        )
        if r.status_code not in (200, 201):
            # Fallback: try multipart upload with different field names to support older Rasa versions
            attempt_errors = []
            response = None
            for field in ("training_files", "training_data", "files"):
                buf.seek(0)
                files = {field: ("project.zip", buf, "application/zip")}
                rr = requests.post(
                    train_url,
                    files=files,
                    data={"force_training": "true", "save_to_default_model_directory": "true"},
                    headers={"Accept": "application/octet-stream"},
                    timeout=1800,
                )
                if rr.status_code in (200, 201):
                    r = rr
                    response = rr
                    break
                else:
                    snippet = None
                    try:
                        snippet = json.dumps(rr.json())[:400]
                    except Exception:
                        snippet = (rr.text or "")[:400]
                    attempt_errors.append({"field": field, "status": rr.status_code, "body": snippet})
            if response is None:
                return jsonify({
                    "error": "remote training failed",
                    "attempts": attempt_errors,
                }), 502
        if r.status_code in (200, 201):
            # Some Rasa versions return binary model; if so, save it
            content_type = r.headers.get("Content-Type", "")
            model_path = None
            if "application/gzip" in content_type or "application/octet-stream" in content_type or r.content[:2] == b"\x1f\x8b":
                # Save model to mounted models dir
                ts = int(time.time())
                model_path = os.path.join(RASA_MODELS_DIR, f"model-{ts}.tar.gz")
                with open(model_path, "wb") as f:
                    f.write(r.content)
            else:
                # If JSON returned with model path on server, try to read it
                try:
                    info = r.json()
                    model_path = info.get("model") or info.get("path")
                except Exception:
                    pass

            # Determine model to load
            if not model_path or not os.path.exists(model_path):
                # Try downloading current model from Rasa server
                mr = requests.get(load_url, timeout=120)
                if mr.status_code == 200 and (mr.headers.get("Content-Type", "").startswith("application/") or mr.content[:2] == b"\x1f\x8b"):
                    ts = int(time.time())
                    model_path = os.path.join(RASA_MODELS_DIR, f"model-{ts}.tar.gz")
                    with open(model_path, "wb") as f:
                        f.write(mr.content)
                else:
                    model_path = _latest_model_path(RASA_MODELS_DIR)
            if not model_path or not os.path.exists(model_path):
                return jsonify({"error": "training finished but model file not found"}), 500

            # Hot reload into Rasa
            files = {"model": (os.path.basename(model_path), open(model_path, "rb"), "application/gzip")}
            lr = requests.put(load_url, files=files, timeout=120)
            if lr.status_code in (200, 204):
                return jsonify({"ok": True, "strategy": "remote", "model": os.path.basename(model_path)}), 200
            return jsonify({"error": f"model load failed: {lr.status_code} {lr.text}"}), 500
        else:
            # Bubble up detailed remote error instead of attempting local CLI (not available here)
            err_text = None
            try:
                err_json = r.json()
                err_text = json.dumps(err_json)[:4000]
            except Exception:
                err_text = r.text[:4000]
            return jsonify({
                "error": "remote training failed",
                "status": r.status_code,
                "body": err_text,
            }), 502
    except req_exc.RequestException as e:
        # Network/connection error to Rasa
        return jsonify({
            "error": "rasa service unreachable",
            "details": str(e),
            "hint": f"verify RASA_HOST={RASA_HOST} is reachable from http_server and the container is healthy",
        }), 502

    # Fallback: run local training if project is mounted
    # Optional: allow a local training fallback if explicitly enabled
    if ALLOW_LOCAL_RASA_TRAIN:
        try:
            if not os.path.isdir(RASA_PROJECT_ROOT):
                return jsonify({"error": "rasa project not mounted for local training"}), 500
            proc = subprocess.run(
                ["bash", "-lc", f"cd '{RASA_PROJECT_ROOT}' && rasa train --out '{RASA_MODELS_DIR}'"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=1200,
                text=True,
            )
            if proc.returncode != 0:
                return jsonify({"error": "local training failed", "output": proc.stdout[-4000:]}), 500
            model_path = _latest_model_path(RASA_MODELS_DIR)
            if not model_path or not os.path.exists(model_path):
                return jsonify({"error": "no model produced"}), 500
            files = {"model": (os.path.basename(model_path), open(model_path, "rb"), "application/gzip")}
            lr = requests.put(load_url, files=files, timeout=120)
            if lr.status_code in (200, 204):
                return jsonify({"ok": True, "strategy": "local", "model": os.path.basename(model_path)}), 200
            return jsonify({"error": f"model load failed: {lr.status_code} {lr.text}"}), 500
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        return jsonify({
            "error": "training could not be performed",
            "hint": "Rasa API training failed or is unreachable. Use the one-off trainer: scripts/train-rasa.ps1, or enable local fallback by setting ALLOW_LOCAL_RASA_TRAIN=true in http_server env.",
        }), 502


@app.route("/api/clear_artifacts", methods=["POST"])
def api_clear_artifacts():
    username = get_user_from_request()
    if not username:
        return jsonify({"error": "unauthorized"}), 401
    user_dir = os.path.join(ARTIFACTS_ROOT, username)
    if not os.path.isdir(user_dir):
        return jsonify({"ok": True, "deleted": 0})
    deleted = 0
    errors = []
    try:
        for root, dirs, files in os.walk(user_dir):
            # Do not delete chat_history.json
            for fname in files:
                if fname == "chat_history.json":
                    continue
                fpath = os.path.join(root, fname)
                try:
                    os.remove(fpath)
                    deleted += 1
                except Exception as e:
                    errors.append({"file": fpath, "error": str(e)})
            # Remove empty directories (skip the user_dir itself)
            for d in list(dirs):
                dpath = os.path.join(root, d)
                try:
                    # Only remove if empty
                    if not os.listdir(dpath):
                        os.rmdir(dpath)
                except Exception:
                    pass
        return jsonify({"ok": True, "deleted": deleted, "errors": errors}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def partial_response(path, start, end, mime):
    file_size = os.path.getsize(path)
    length = end - start + 1

    def generate():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            chunk_size = 64 * 1024
            while remaining > 0:
                read_size = min(chunk_size, remaining)
                data = f.read(read_size)
                if not data:
                    break
                remaining -= len(data)
                yield data

    rv = Response(generate(), status=206, mimetype=mime)
    rv.headers.add("Content-Range", f"bytes {start}-{end}/{file_size}")
    rv.headers.add("Accept-Ranges", "bytes")
    rv.headers.add("Content-Length", str(length))
    return rv


@app.route("/", defaults={"filename": None})
@app.route("/<path:filename>")
def serve_file(filename):
    if not filename:
        return {"message": "Specify a filename"}, 400

    path = safe_join(ROOT_DIR, filename)
    if not path or not os.path.exists(path) or not os.path.isfile(path):
        abort(404)

    mime, _ = mimetypes.guess_type(path)
    if mime is None:
        mime = "application/octet-stream"

    # Force download if ?download=1
    force_download = request.args.get("download") in ("1", "true", "yes")

    # Handle Range for media playback
    range_header = request.headers.get("Range")
    if range_header and not force_download:
        try:
            # Example: Range: bytes=0-1023
            units, rng = range_header.split("=", 1)
            if units.strip() != "bytes":
                raise ValueError("Only bytes range supported")
            start_str, end_str = rng.split("-", 1)
            file_size = os.path.getsize(path)
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else file_size - 1
            if start > end or end >= file_size:
                # Invalid range
                resp = make_response("", 416)
                resp.headers["Content-Range"] = f"bytes */{file_size}"
                return resp
            return partial_response(path, start, end, mime)
        except Exception:
            # Fall back to full file
            pass

    # Full file response
    if force_download:
        # Use send_file with as_attachment to trigger browser download
        return send_file(path, mimetype=mime, as_attachment=True, download_name=os.path.basename(path))
    else:
        # Stream full content; let the browser decide (images, pdf, html will open)
        resp = send_file(path, mimetype=mime, as_attachment=False)
        # Indicate support for ranges even if not requested
        resp.headers["Accept-Ranges"] = "bytes"
        return resp


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
