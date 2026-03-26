"""
resume_updater.py

Reads resume.yaml, creates a timestamped PDF copy, and applies all edits
(subheader, summary, core competencies, technical proficiencies, and all
company bullet sections) in a single pass.

Usage:
    /Applications/anaconda3/bin/python3 resume_updater.py

Requires: PyMuPDF (fitz), PyYAML
"""

import fitz
import os
import re
import shutil
import yaml
from datetime import datetime

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR      = '/Users/willmino/Library/Claude/Resume_Github_Project'
SRC_PDF       = os.path.join(BASE_DIR, 'Will Mino - Resume.pdf')
YAML_ORIGINAL = os.path.join(BASE_DIR, 'resume_original.yaml')
YAML_WORKING  = os.path.join(BASE_DIR, 'resume.yaml')

CALIBRI_REGULAR = '/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibri.ttf'
CALIBRI_ITALIC  = '/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibrii.ttf'
CALIBRI_BOLD    = '/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibrib.ttf'
ARIAL           = '/System/Library/Fonts/Supplemental/Arial.ttf'

# ── Spacing constants (measured from original PDF) ────────────────────────────
CALIBRI_ASCENDER      = 9.0
CALIBRI_INNER_LINE_HT = 14.65   # spacing between wrapped lines within a bullet
CALIBRI_BULLET_ADVANCE = 14.65  # y-advance from start of one bullet to next (single-line)
ARIAL11_ASCENDER      =  9.958
ARIAL12_ASCENDER      = 10.863

# ── Company section layout ────────────────────────────────────────────────────
COMPANY_SECTIONS = {
    "truecar": {
        "page": 0, "y_range": (453, 740), "y_start": 465.8,
        "x_text": 54.0, "arial_size": 11, "wrap_width": 522.0, "original_y_end": 740,
    },
    "ekn": {
        "page": 1, "y_range": (86, 300), "y_start": 98.1,
        "x_text": 54.0, "arial_size": 12, "wrap_width": 522.0, "original_y_end": 300,
    },
    "pfizer": {
        "page": 1, "y_range": (345, 545), "y_start": 357.1,
        "x_text": 54.0, "arial_size": 12, "wrap_width": 522.0, "original_y_end": 545,
    },
    "tanabe": {
        "page": 2, "y_range": (86, 200), "y_start": 98.1,
        "x_text": 54.0, "arial_size": 12, "wrap_width": 522.0, "original_y_end": 200,
    },
}

# ── Regex pattern for cm blocks ───────────────────────────────────────────────
STREAM_PATTERN = re.compile(
    r'\nq\n\.75 0 0 \.75 36 ([\d.]+) cm\n0 0 0 RG 0 0 0 rg\n.*?\nQ',
    re.DOTALL,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_yaml(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)


def get_target_xref(doc, page_num):
    """Return the xref of the content stream that contains the .75 cm blocks."""
    page = doc[page_num]
    for xref in page.get_contents():
        s = doc.xref_stream(xref).decode('latin-1')
        if '.75 0 0 .75 36' in s:
            return xref
    raise RuntimeError(f"Could not find cm-block stream on page {page_num}")


def remove_cm_blocks(doc, page_num, y_min, y_max):
    """Remove all q…Q cm blocks whose y falls in (y_min, y_max). Returns list of removed y values."""
    xref = get_target_xref(doc, page_num)
    stream = doc.xref_stream(xref).decode('latin-1')
    removed = []

    def replacer(m):
        y = float(m.group(1))
        if y_min < y < y_max:
            removed.append(round(y, 2))
            return ''
        return m.group(0)

    new_stream = STREAM_PATTERN.sub(replacer, stream)
    doc.update_stream(xref, new_stream.encode('latin-1'))
    return removed


def insert_centered(page, text, y, font_obj, fontname, fontfile, fontsize=12):
    """Insert text centered within the 36–576 content area (width=540)."""
    width = font_obj.text_length(text, fontsize=fontsize)
    x = 36.0 + (540.0 - width) / 2
    page.insert_text(
        fitz.Point(x, y), text,
        fontname=fontname, fontfile=fontfile,
        fontsize=fontsize, color=(0, 0, 0),
    )


def wrap_text(text, font_cal, max_width=529.0, fontsize=12):
    """Word-wrap text to fit within max_width using Calibri metrics."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        candidate = (cur + " " + w).strip()
        if font_cal.text_length(candidate, fontsize=fontsize) <= max_width:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def shift_blocks_in_y_range(doc, page_num, y_lo, y_hi, delta):
    """Shift all cm blocks (text + grey backgrounds) with y in [y_lo, y_hi] by delta."""
    xref = get_target_xref(doc, page_num)
    stream = doc.xref_stream(xref).decode('latin-1')
    cm_pattern = re.compile(r'(\.75 0 0 \.75 36 )([\d.]+)( cm\n)')

    def shifter(m):
        y = float(m.group(2))
        if y_lo <= y <= y_hi:
            return m.group(1) + f"{y + delta:.3f}" + m.group(3)
        return m.group(0)

    new_stream = cm_pattern.sub(shifter, stream)
    doc.update_stream(xref, new_stream.encode('latin-1'))
    print(f"  page {page_num}: shifted y={y_lo}–{y_hi} by delta={delta:+.2f}")


def render_company_section(doc, company, bullets, font_cal):
    """
    Remove all original bullets for a company and re-render from bullets list.
    Returns the actual y position after the last rendered bullet.
    """
    cfg    = COMPANY_SECTIONS[company]
    page   = doc[cfg["page"]]
    x_text = cfg["x_text"]
    a_asc  = ARIAL11_ASCENDER if cfg["arial_size"] == 11 else ARIAL12_ASCENDER
    y_lo, y_hi = cfg["y_range"]

    # Remove original cm blocks for this company
    removed = remove_cm_blocks(doc, cfg["page"], y_lo, y_hi)
    print(f"  {company}: removed cm blocks at y={removed}")

    # Re-render all non-empty bullets
    y = cfg["y_start"]
    for text in bullets:
        if not text.strip():
            continue
        lines = wrap_text(text, font_cal, max_width=cfg["wrap_width"])
        # Bullet marker ●
        page.insert_text(
            fitz.Point(36.0, y + a_asc), "●",
            fontname="ArialNew", fontfile=ARIAL,
            fontsize=cfg["arial_size"], color=(0, 0, 0),
        )
        # Text lines
        for i, line in enumerate(lines):
            page.insert_text(
                fitz.Point(x_text, y + CALIBRI_ASCENDER + i * CALIBRI_INNER_LINE_HT),
                line,
                fontname="Calibri", fontfile=CALIBRI_REGULAR,
                fontsize=12, color=(0, 0, 0),
            )
        y += (len(lines) - 1) * CALIBRI_INNER_LINE_HT + CALIBRI_BULLET_ADVANCE

    return y


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # ── Step 0: Load YAML ────────────────────────────────────────────────────
    data = load_yaml(YAML_WORKING)
    print("Loaded resume.yaml")

    subheader            = data.get("subheader", "")
    summary              = data.get("summary", "")
    core_competencies    = data.get("core_competencies", [])
    tech_proficiencies   = data.get("technical_proficiencies", [])
    bullets              = data.get("bullets", {})

    # ── Step 1: Create timestamped copy ─────────────────────────────────────
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    dest      = os.path.join(BASE_DIR, f'Will Mino - Resume_copy_{timestamp}.pdf')
    dest_yaml = os.path.join(BASE_DIR, f'resume_copy_{timestamp}.yaml')

    shutil.copy(SRC_PDF, dest)
    shutil.copy(YAML_ORIGINAL, dest_yaml)
    print(f"Created: {os.path.basename(dest)}")
    print(f"Created: {os.path.basename(dest_yaml)}")

    # ── Step 2: Open copy and load fonts ────────────────────────────────────
    doc      = fitz.open(dest)
    font_it  = fitz.Font(fontfile=CALIBRI_ITALIC)
    font_bold = fitz.Font(fontfile=CALIBRI_BOLD)
    font_cal  = fitz.Font(fontfile=CALIBRI_REGULAR)

    # ── Step 3: Remove page-0 header sections in a single pass ──────────────
    print("\nRemoving header section cm blocks (page 0)...")
    removed_sub  = remove_cm_blocks(doc, 0, y_min=98,  y_max=101)
    removed_sum  = remove_cm_blocks(doc, 0, y_min=118, y_max=121)
    removed_cc   = remove_cm_blocks(doc, 0, y_min=250, y_max=320)
    removed_tp   = remove_cm_blocks(doc, 0, y_min=350, y_max=380)
    print(f"  Subheader cm blocks removed: {removed_sub}")
    print(f"  Summary cm blocks removed:   {removed_sum}")
    print(f"  Core Comp cm blocks removed: {removed_cc}")
    print(f"  Tech Prof cm blocks removed: {removed_tp}")

    # ── Step 4: Render company bullet sections ───────────────────────────────
    print("\nRendering company bullet sections...")

    # TrueCar (page 0 — no reflow needed after, it's the last section on p0)
    render_company_section(doc, "truecar", bullets.get("truecar", []), font_cal)

    # EKN → possibly reflow Pfizer header (page 1)
    ekn_y_end = render_company_section(doc, "ekn", bullets.get("ekn", []), font_cal)
    delta_ekn = ekn_y_end - COMPANY_SECTIONS["ekn"]["original_y_end"]
    if delta_ekn != 0:
        print(f"  EKN delta={delta_ekn:+.2f} — reflowing Pfizer header...")
        shift_blocks_in_y_range(doc, 1, y_lo=300, y_hi=345, delta=delta_ekn)
        COMPANY_SECTIONS["pfizer"]["y_start"] += delta_ekn

    render_company_section(doc, "pfizer", bullets.get("pfizer", []), font_cal)

    # Tanabe → possibly reflow Education/Awards (page 2)
    tanabe_y_end = render_company_section(doc, "tanabe", bullets.get("tanabe", []), font_cal)
    delta_tanabe = tanabe_y_end - COMPANY_SECTIONS["tanabe"]["original_y_end"]
    if delta_tanabe != 0:
        print(f"  Tanabe delta={delta_tanabe:+.2f} — reflowing Education/Awards...")
        shift_blocks_in_y_range(doc, 2, y_lo=200, y_hi=400, delta=delta_tanabe)

    # ── Step 5: Insert header section text ──────────────────────────────────
    print("\nInserting header section text...")
    page0 = doc[0]

    # Subheader — centered, Calibri-Bold 16pt, y=118.683
    insert_centered(page0, subheader, 118.683, font_bold, "CalibriB", CALIBRI_BOLD, fontsize=16)
    print(f"  Subheader: {subheader!r}")

    # Summary — left-aligned, Calibri Regular 12pt, x=36.0, y=144.0
    page0.insert_text(
        fitz.Point(36.0, 144.0), summary,
        fontname="Calibri", fontfile=CALIBRI_REGULAR,
        fontsize=12, color=(0, 0, 0),
    )
    print(f"  Summary: {summary[:60]!r}{'...' if len(summary) > 60 else ''}")

    # Core Competencies — centered, Calibri Italic 12pt
    # Y insert rows: 269.0, 286.0, 303.0, 320.0
    cc_y_values = [269.0, 286.0, 303.0, 320.0]
    for i, row in enumerate(core_competencies[:4]):
        row_text = "  ".join(f"• {item}" for item in row)
        insert_centered(page0, row_text, cc_y_values[i], font_it, "CalibriIt", CALIBRI_ITALIC)
        print(f"  Core Comp row {i+1}: {row_text[:60]!r}")

    # Technical Proficiencies — centered, Calibri Italic 12pt
    # Y insert rows: 371.0, 388.0
    tp_y_values = [371.0, 388.0]
    for i, row in enumerate(tech_proficiencies[:2]):
        row_text = "  ".join(f"• {item}" for item in row)
        insert_centered(page0, row_text, tp_y_values[i], font_it, "CalibriIt", CALIBRI_ITALIC)
        print(f"  Tech Prof row {i+1}: {row_text[:60]!r}")

    # ── Step 6: Save ─────────────────────────────────────────────────────────
    tmp = '/tmp/resume_copy_out.pdf'
    doc.save(tmp, garbage=4, deflate=True)
    doc.close()
    os.replace(tmp, dest)
    print(f"\nSaved: {dest}")


if __name__ == "__main__":
    main()
