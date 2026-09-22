# -*- coding: utf-8 -*-
"""Screenshot the REAL system answering, one PNG per question, through Open WebUI.

Why this exists: a written claim that the system answers a shape of question is worth little on its
own. This drives the actual browser against the running stack, asks each question in a FRESH chat,
waits for the whole answer, and saves a full-page screenshot plus the answer text. The result is
evidence a reader can check, not a transcript anyone could have typed.

It is building-agnostic: nothing here names a building. The questions come from a file
(``--questions``), the login from a credentials CSV, and the model from whatever Open WebUI offers.

    python scripts/capture_evidence_screenshots.py --user facility01 --out docs/supervisor_evidence

Needs: the stack up, Open WebUI reachable, and ``playwright install chromium`` done once.
The password is read from the CSV and never printed, logged or written to any output file.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests

REPO = Path(__file__).resolve().parent.parent
_SLUG = re.compile(r"[^a-z0-9]+")


def slug(text: str, n: int = 48) -> str:
    return _SLUG.sub("-", text.lower()).strip("-")[:n] or "question"


def read_login(csv_path: Path, username: str) -> Dict[str, str]:
    with csv_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("username") == username:
                return row
    raise SystemExit(f"no row for {username} in {csv_path}")


def sign_in(base: str, email: str, password: str) -> str:
    r = requests.post(f"{base}/api/v1/auths/signin",
                      json={"email": email, "password": password}, timeout=30)
    if r.status_code != 200:
        raise SystemExit(f"sign-in failed: HTTP {r.status_code}")
    return r.json()["token"]


def pick_model(base: str, token: str, prefer: str = "") -> str:
    r = requests.get(f"{base}/api/models", headers={"Authorization": f"Bearer {token}"}, timeout=30)
    ids = [m.get("id") for m in (r.json().get("data") or []) if m.get("id")]
    if prefer and prefer in ids:
        return prefer
    for mid in ids:                       # the arena model is a chooser, never the system itself
        if mid != "arena-model":
            return mid
    raise SystemExit(f"no usable model in {ids}")


def load_questions(path: Path) -> List[Dict[str, str]]:
    """One question per line: ``shape | question``; ``#`` comments and blank lines ignored."""
    out: List[Dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        shape, _, question = line.partition("|")
        out.append({"shape": shape.strip() if question else "", "question": (question or shape).strip()})
    return out


# --------------------------------------------------------------------------------------- browser

def _new_chat(page, base: str, model: str) -> None:
    page.goto(f"{base}/?models={model}", wait_until="domcontentloaded")
    page.wait_for_selector("#chat-input", timeout=60_000)
    page.wait_for_timeout(700)


def _send(page, question: str) -> None:
    box = page.locator("#chat-input")
    box.click()
    box.fill("") if box.get_attribute("contenteditable") is None else page.keyboard.press("Control+A")
    page.keyboard.type(question, delay=8)
    page.wait_for_timeout(250)
    page.keyboard.press("Enter")


def _is_streaming(text: str) -> bool:
    """True while the answer is still being produced.

    MEASURED, not guessed (DOM probe, 2026-09-21). While the pipeline streams, the container shows
    its status as RAW markdown, so the literal string ``<details>`` is in innerText and the tail is a
    status line ending in an ellipsis. The moment the turn completes the markdown is rendered, so
    ``<details>`` becomes an element and that literal string is gone.

    Getting this wrong is not a cosmetic bug: an earlier version keyed on a stop button that never
    matched, and 21 of 25 screenshots caught the words "Analyzing your question..." instead of an
    answer -- evidence that would have been wrong in the reader's favour.
    """
    if not text:
        return True
    t = text.strip()
    return "<details>" in t or t.endswith("…") or t.endswith("...")


def _wait_for_answer(page, timeout_s: int) -> Dict[str, object]:
    """Wait for a COMPLETE answer. Returns {seconds, complete, text}."""
    t0 = time.time()
    last, stable = "", 0
    while time.time() - t0 < timeout_s:
        page.wait_for_timeout(2000)
        text = _answer_text(page)
        if _is_streaming(text):
            stable, last = 0, text
            continue
        stable = stable + 1 if text == last else 0
        last = text
        if stable >= 3:                     # settled for ~6 s with nothing still streaming
            return {"seconds": time.time() - t0, "complete": True, "text": text}
    return {"seconds": time.time() - t0, "complete": False, "text": last}


_EXPAND_JS = """
() => {
  // The chat scrolls INSIDE a container, so a full-page screenshot would cut a long answer off at
  // the fold and the evidence would silently show only its first screen. Grow every scrolling
  // ancestor of the last message to its full content height first. Screenshot only; nothing is sent.
  const msgs = document.querySelectorAll('.chat-assistant, [id^="message-"]');
  let node = msgs.length ? msgs[msgs.length - 1] : null;
  let grown = 0;
  while (node && node !== document.body) {
    if (node.scrollHeight > node.clientHeight + 4) {
      node.style.height = node.scrollHeight + 'px';
      node.style.maxHeight = 'none';
      node.style.overflow = 'visible';
      grown++;
    }
    node.scrollTop = 0;   // the chat sits scrolled to the BOTTOM; the question is above the fold
    node = node.parentElement;
  }
  // The header floats over the top of the conversation, so without this the first line of the
  // QUESTION sits behind it and a reader cannot see what was asked (evidence screenshot 05).
  const head = document.querySelector('header, [class*="sticky"]');
  const pad = head ? head.getBoundingClientRect().height + 16 : 72;
  const first = document.querySelector('.chat-user, [id^="message-"]');
  if (first && first.parentElement) first.parentElement.style.paddingTop = pad + 'px';
  window.scrollTo(0, 0);
  return grown;
}
"""


#: Tallest screenshot we will produce. A very long answer is still cut, but at a stated point
#: rather than silently at one screen.
MAX_SHOT_HEIGHT = 12000

_CONTENT_HEIGHT_JS = """
() => {
  // How tall the conversation actually is. The chat scrolls INSIDE a container, so the document
  // stays one viewport high however long the answer is -- which is why `full_page` produced a
  // 1800px image for every answer, cutting the question off the top of the long ones.
  const nodes = document.querySelectorAll('.chat-user, .chat-assistant, [id^="message-"]');
  let top = Infinity, bottom = -Infinity;
  nodes.forEach(n => {
    const r = n.getBoundingClientRect();
    if (r.height === 0) return;
    top = Math.min(top, r.top);
    bottom = Math.max(bottom, r.bottom);
  });
  if (!isFinite(top) || !isFinite(bottom)) return 0;
  return Math.ceil(bottom - top);
}
"""


def _expand_for_screenshot(page, width: int = 1440) -> None:
    """Grow the page until the WHOLE conversation is on it, then screenshot that.

    Growing the inner container is not enough on its own: the document height never changes, so
    a full-page screenshot still captures one screen. Resizing the viewport to the content is
    what actually renders the rest.
    """
    try:
        page.evaluate(_EXPAND_JS)
        page.wait_for_timeout(300)
        needed = int(page.evaluate(_CONTENT_HEIGHT_JS) or 0)
        height = max(900, min(needed + 420, MAX_SHOT_HEIGHT))
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_timeout(700)
        page.evaluate(_EXPAND_JS)      # the taller viewport may re-lay-out the container
        page.wait_for_timeout(400)
    except Exception:
        pass


def _answer_text(page) -> str:
    """The assistant's rendered reply. `#response-content-container` is the element that holds it;
    `.chat-assistant` matched an empty wrapper and reported every answer as blank."""
    try:
        msgs = page.locator("#response-content-container")
        return msgs.last.inner_text().strip() if msgs.count() else ""
    except Exception:
        return ""


def capture(args) -> int:
    from playwright.sync_api import sync_playwright

    creds = read_login(Path(args.credentials), args.user)
    token = sign_in(args.base, creds["email"], creds["password"])
    model = pick_model(args.base, token, args.model)
    questions = load_questions(Path(args.questions))
    out_dir = Path(args.out)
    (out_dir / "screenshots").mkdir(parents=True, exist_ok=True)
    print(f"{len(questions)} questions | model={model} | user={creds['username']} -> {out_dir}")

    records: List[Dict[str, object]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        # The light theme is what the reader will see, and the session token is what makes the UI
        # genuinely logged in -- both must exist before the app's first paint.
        ctx.add_init_script(
            "localStorage.setItem('token', %s);"
            "localStorage.setItem('theme', 'light');"
            "document.documentElement.classList.remove('dark');"
            "document.documentElement.classList.add('light');" % json.dumps(token)
        )
        ctx.add_cookies([{"name": "token", "value": token, "url": args.base}])
        page = ctx.new_page()

        for i, item in enumerate(questions, 1):
            q = item["question"]
            name = f"{i:02d}_{slug(q)}"
            try:
                page.set_viewport_size({"width": 1440, "height": 900})
                _new_chat(page, args.base, model)
                _send(page, q)
                res = _wait_for_answer(page, args.timeout)
                took, complete = float(res["seconds"]), bool(res["complete"])
                answer = str(res["text"])            # read BEFORE the DOM is grown for the shot
                page.wait_for_timeout(1200)
                _expand_for_screenshot(page)
                shot = out_dir / "screenshots" / f"{name}.png"
                page.screenshot(path=str(shot), full_page=True)
                flag = "OK        " if complete else "INCOMPLETE"
                print(f"[{i:2d}/{len(questions)}] {took:6.1f}s {flag} {q[:56]}")
            except Exception as exc:                       # one bad question must not lose the rest
                took, complete = -1.0, False
                answer, shot = f"CAPTURE ERROR: {exc}", out_dir / "screenshots" / f"{name}.png"
                print(f"[{i:2d}/{len(questions)}] FAILED {q[:56]} :: {exc}")
            records.append({"n": i, "shape": item["shape"], "question": q,
                            "seconds": round(took, 1), "complete": complete, "answer": answer,
                            "screenshot": f"screenshots/{shot.name}"})
            (out_dir / "answers.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
        browser.close()

    (out_dir / "answers.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
    bad = [r for r in records if not r["complete"]]
    print(f"\nwrote {len(records)} records to {out_dir/'answers.jsonl'}")
    if bad:                     # say it loudly: an incomplete shot must never be filed as evidence
        print(f"WARNING: {len(bad)} of {len(records)} did NOT complete — re-run these before using "
              f"the pack: {[r['n'] for r in bad]}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:3000")
    ap.add_argument("--credentials", default=str(REPO / "user_credentials_bldg1.csv"))
    ap.add_argument("--user", default="facility01")
    ap.add_argument("--model", default="", help="Open WebUI model id; default = the first non-arena one")
    ap.add_argument("--questions", default=str(REPO / "docs" / "evidence_questions.txt"))
    ap.add_argument("--out", default=str(REPO / "docs" / "supervisor_evidence"))
    ap.add_argument("--timeout", type=int, default=300, help="seconds to wait for one answer")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return capture(args)


if __name__ == "__main__":
    sys.exit(main())
