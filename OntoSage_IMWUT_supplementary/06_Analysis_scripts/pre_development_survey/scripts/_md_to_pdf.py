#!/usr/bin/env python3
"""
_md_to_pdf.py — tooling. Convert a Markdown report to PDF.

Primary backend: fpdf2 (pure Python, no system libraries needed on Windows).
Fallback backend: xhtml2pdf (requires libcairo on Windows — skip if unavailable).

Usage:
  python scripts/_md_to_pdf.py "outputs/SURVEY_ANALYSIS_REPORT.md" [out.pdf]
If out.pdf is omitted, writes alongside the .md with a .pdf extension.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# ── fpdf2 backend (pure Python, always available) ──────────────────────────
from fpdf import FPDF

MARGIN_L = 18
MARGIN_R = 18
MARGIN_T = 20
PAGE_W = 210  # A4 mm

# Map heading level → (font-size, bold, top-spacing-mm, colour-rgb)
_H_STYLE = {
    1: (18, True, 8, (20, 54, 92)),
    2: (13, True, 6, (20, 54, 92)),
    3: (11, True, 4, (32, 80, 128)),
    4: (10, True, 3, (32, 80, 128)),
}
_BODY_SIZE = 9.5
_CODE_SIZE = 8.5
_TABLE_SIZE = 8.0
_LINE_H = 5.0
_TABLE_LINE_H = 4.5


_UNICODE_MAP = str.maketrans({
    "—": "--", "–": "-", "‒": "-",
    "’": "'", "‘": "'", "′": "'",
    "“": '"', "”": '"',
    "•": "*", "‣": "*", "⁃": "*",
    "κ": "k", "α": "a", "β": "b",
    "≥": ">=", "≤": "<=", "≠": "!=",
    "×": "x", "±": "+/-", "²": "^2",
    "→": "->", "←": "<-", "↔": "<->",
    "✓": "[v]", "✗": "[x]", "✔": "[v]",
    "é": "e", "è": "e", "ê": "e",
    "à": "a", "â": "a", "ü": "u",
    "°": "deg", "№": "No.", "§": "S",
    "⁻": "-",  # superscript minus
})


def _ascii(text: str) -> str:
    """Transliterate known Unicode to ASCII; drop the rest."""
    text = text.translate(_UNICODE_MAP)
    return text.encode("ascii", errors="replace").decode("ascii")


def _strip_md_inline(text: str) -> str:
    """Strip inline markdown (bold, italic, code, links) to plain text."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return _ascii(text)


def _parse_table(lines: list[str]) -> list[list[str]]:
    rows = []
    for ln in lines:
        if re.match(r"^\s*\|[-: |]+\|\s*$", ln):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        rows.append(cells)
    return rows


def convert_fpdf(md_path: Path, pdf_path: Path) -> bool:
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    pdf = FPDF(format="A4")
    pdf.set_margins(MARGIN_L, MARGIN_T, MARGIN_R)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    usable_w = PAGE_W - MARGIN_L - MARGIN_R

    i = 0
    in_code = False
    code_buf: list[str] = []
    table_buf: list[str] = []
    in_table = False

    def r(text: str) -> str:
        """Render-safe: strip markdown inline + ASCII-safe + truncate for cells."""
        return _strip_md_inline(text)

    def flush_table() -> None:
        if not table_buf:
            return
        rows = _parse_table(table_buf)
        if not rows:
            return
        ncols = max(len(r) for r in rows)
        col_w = usable_w / ncols
        pdf.set_font("Courier", size=_TABLE_SIZE)
        for ri, row in enumerate(rows):
            for ci, cell in enumerate(row):
                pdf.set_fill_color(232, 238, 244) if ri == 0 else pdf.set_fill_color(255, 255, 255)
                pdf.set_x(MARGIN_L + ci * col_w)
                pdf.cell(col_w, _TABLE_LINE_H, r(cell)[:60], border=1, fill=(ri == 0))
            pdf.ln()
        pdf.set_font("Helvetica", size=_BODY_SIZE)

    while i < len(lines):
        ln = lines[i]

        # Fenced code blocks
        if ln.strip().startswith("```"):
            if in_code:
                in_code = False
                pdf.set_font("Courier", size=_CODE_SIZE)
                pdf.set_fill_color(242, 244, 246)
                for cl in code_buf:
                    pdf.set_x(MARGIN_L)
                    pdf.cell(usable_w, _LINE_H - 1, _ascii(cl[:120]), border=0, fill=True)
                    pdf.ln()
                code_buf = []
                pdf.set_font("Helvetica", size=_BODY_SIZE)
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(ln)
            i += 1
            continue

        # Table rows
        if ln.strip().startswith("|"):
            if not in_table:
                in_table = True
                if table_buf:
                    flush_table()
                    table_buf = []
            table_buf.append(ln)
            i += 1
            continue
        if in_table:
            flush_table()
            table_buf = []
            in_table = False

        stripped = ln.strip()

        # Headings
        m = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if m:
            level = min(len(m.group(1)), 4)
            title = r(m.group(2))
            sz, bold, sp, col = _H_STYLE[level]
            pdf.ln(sp)
            pdf.set_text_color(*col)
            pdf.set_font("Helvetica", style="B" if bold else "", size=sz)
            pdf.multi_cell(usable_w, sz * 0.45, title)
            if level == 2:
                pdf.line(MARGIN_L, pdf.get_y(), PAGE_W - MARGIN_R, pdf.get_y())
                pdf.ln(1)
            pdf.set_text_color(26, 26, 26)
            pdf.set_font("Helvetica", size=_BODY_SIZE)
            i += 1
            continue

        # Horizontal rule
        if re.match(r"^-{3,}$", stripped) or re.match(r"^\*{3,}$", stripped):
            pdf.ln(2)
            pdf.line(MARGIN_L, pdf.get_y(), PAGE_W - MARGIN_R, pdf.get_y())
            pdf.ln(2)
            i += 1
            continue

        # Bullet / list
        m_bullet = re.match(r"^[-*+]\s+(.+)$", stripped) or re.match(r"^\d+\.\s+(.+)$", stripped)
        if m_bullet:
            body = r(m_bullet.group(1))
            pdf.set_font("Helvetica", size=_BODY_SIZE)
            pdf.set_x(MARGIN_L + 4)
            pdf.multi_cell(usable_w - 4, _LINE_H, "* " + body)
            i += 1
            continue

        # Blockquote
        if stripped.startswith(">"):
            body = r(stripped.lstrip(">").strip())
            pdf.set_text_color(68, 82, 94)
            pdf.set_font("Helvetica", style="I", size=_BODY_SIZE)
            pdf.set_x(MARGIN_L + 5)
            pdf.multi_cell(usable_w - 5, _LINE_H, body)
            pdf.set_text_color(26, 26, 26)
            pdf.set_font("Helvetica", size=_BODY_SIZE)
            i += 1
            continue

        # Empty line
        if not stripped:
            pdf.ln(_LINE_H * 0.4)
            i += 1
            continue

        # Normal paragraph
        pdf.set_font("Helvetica", size=_BODY_SIZE)
        pdf.multi_cell(usable_w, _LINE_H, r(stripped))
        i += 1

    # Flush any trailing table
    if in_table:
        flush_table()

    pdf.output(str(pdf_path))
    return True


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: _md_to_pdf.py <in.md> [out.pdf]")
        return 2
    md = Path(sys.argv[1])
    if not md.is_absolute():
        md = Path.cwd() / md
    pdf = Path(sys.argv[2]) if len(sys.argv) > 2 else md.with_suffix(".pdf")
    ok = convert_fpdf(md, pdf)
    size = pdf.stat().st_size if pdf.exists() else 0
    print(f"{'OK' if ok else 'WARN'}: {md.name} -> {pdf.name} ({size:,} bytes)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
