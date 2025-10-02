import os
import shutil
import time
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import subprocess
import json

PROJECT_ROOT = os.environ.get("RASA_PROJECT_ROOT", "/srv/rasa")
PORT = int(os.environ.get("PORT", "6080"))
_origins_env = os.environ.get("ALLOWED_ORIGINS") or os.environ.get("FRONTEND_ORIGIN") or "http://localhost:3000"
ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()]

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _safe_path(rel_or_abs: str) -> Path:
    base = Path(PROJECT_ROOT).resolve()
    target = (base / rel_or_abs).resolve() if not str(rel_or_abs).startswith(str(base)) else Path(rel_or_abs).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="path outside project root")
    return target


@app.get("/health")
def health():
    return {"status": "ok"}


class FileEntry(BaseModel):
    name: str
    path: str
    is_dir: bool
    size: int
    mtime: float


@app.get("/files", response_model=List[FileEntry])
def list_files(dir: Optional[str] = Query(default="")):
    root = Path(PROJECT_ROOT).resolve()
    base = _safe_path(dir or ".")
    if not base.exists() or not base.is_dir():
        raise HTTPException(status_code=404, detail="directory not found")
    entries: List[FileEntry] = []
    for p in sorted(base.iterdir(), key=lambda x: x.name.lower()):
        st = p.stat()
        entries.append(
            FileEntry(
                name=p.name,
                path=str(p.resolve()),
                is_dir=p.is_dir(),
                size=0 if p.is_dir() else st.st_size,
                mtime=st.st_mtime,
            )
        )
    return entries


@app.get("/file")
def read_file(path: str):
    p = _safe_path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    try:
        content = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="file is not utf-8 text")
    return {"path": str(p), "content": content}


class WriteBody(BaseModel):
    path: str
    content: str


@app.put("/file")
def write_file(body: WriteBody):
    p = _safe_path(body.path)
    # Ensure parent exists
    p.parent.mkdir(parents=True, exist_ok=True)
    # Backup previous version
    if p.exists() and p.is_file():
        backup_dir = Path(PROJECT_ROOT) / ".backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        rel = p.resolve().relative_to(Path(PROJECT_ROOT).resolve())
        ts = time.strftime("%Y%m%d-%H%M%S")
        bpath = backup_dir / f"{str(rel).replace(os.sep,'__')}.{ts}.bak"
        try:
            shutil.copy2(str(p), str(bpath))
        except Exception:
            pass
    # Atomic write
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(body.content, encoding="utf-8")
    tmp.replace(p)
    return {"ok": True, "path": str(p)}


@app.post("/validate")
def validate_project():
    cmd = [
        "bash",
        "-lc",
        "rasa data validate --config /srv/rasa/config.yml --domain /srv/rasa/domain.yml --data /srv/rasa/data",
    ]
    try:
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600, text=True)
        out = proc.stdout
        return {"ok": proc.returncode == 0, "returncode": proc.returncode, "output": out[-40000:]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/lint-actions")
def lint_actions():
    actions_dir = Path(PROJECT_ROOT) / "actions"
    if not actions_dir.exists():
        return {"ok": True, "results": [], "note": "no actions directory"}
    cmd = ["bash", "-lc", "ruff --format json /srv/rasa/actions || true"]
    try:
        proc = subprocess.run(cmd, cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300, text=True)
        out = proc.stdout.strip()
        results = []
        try:
            if out:
                results = json.loads(out)
        except Exception:
            results = []
        ok = len(results) == 0
        return {"ok": ok, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
