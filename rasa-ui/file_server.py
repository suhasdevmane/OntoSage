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

ROOT_DIR = os.environ.get("ROOT_DIR", "/data")
app = Flask(__name__)

# Security / CORS config
JWT_SECRET = os.environ.get("JWT_SECRET", "dev_secret_change_me")
JWT_EXPIRES_DAYS = int(os.environ.get("JWT_EXPIRES_DAYS", "7"))
SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "false").lower() in ("1", "true", "yes")
# Support a single origin (FRONTEND_ORIGIN) or comma-separated list (ALLOWED_ORIGINS)
_origins_env = os.environ.get("ALLOWED_ORIGINS") or os.environ.get("FRONTEND_ORIGIN") or "http://localhost:3000"
ALLOWED_ORIGINS = {o.strip() for o in _origins_env.split(",") if o.strip()}


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
