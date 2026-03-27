"""
resume_updater_2.py

Single-prompt resume updater. Paste all changes at once using labeled
sections, then the script parses them, updates resume.yaml, and generates
a new timestamped PDF copy.

Usage:
    /Applications/anaconda3/bin/python3 resume_updater_2.py

Requires: PyMuPDF (fitz), PyYAML
"""

import fitz
import os
import re
import shutil
import tkinter as tk
import yaml
from datetime import datetime

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR      = '/Users/willmino/Library/Claude/Resume_Github_Project'
SRC_PDF       = os.path.join(BASE_DIR, 'Will Mino - Resume.pdf')
YAML_ORIGINAL = os.path.join(BASE_DIR, 'resume_original.yaml')
YAML_WORKING  = os.path.join(BASE_DIR, 'resume.yaml')

CALIBRI_REGULAR   = '/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibri.ttf'
CALIBRI_ITALIC    = '/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibrii.ttf'
CALIBRI_BOLD      = '/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibrib.ttf'
CALIBRI_BOLD_ITAL = '/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibriz.ttf'
ARIAL             = '/System/Library/Fonts/Supplemental/Arial.ttf'

# ── Spacing constants ─────────────────────────────────────────────────────────
CALIBRI_ASCENDER       = 9.0
CALIBRI_INNER_LINE_HT  = 14.65
CALIBRI_BULLET_ADVANCE = 14.65
ARIAL11_ASCENDER       = 9.958
ARIAL12_ASCENDER       = 10.863

# ── Fixed anchor positions (page 0) ───────────────────────────────────────────
# Industries line is pre-removed before apply_redactions to avoid duplication,
# then re-inserted at its original y + summary_delta so it tracks summary length.
# CC label is always 2 line-heights below Industries and shifts by the same delta.
# INDUSTRIES_Y is read dynamically from SRC_PDF at runtime — not hardcoded here.
CC_LINES_BELOW_INDUSTRIES = 2   # CC label is always this many lines below Industries

# ── Company section layout ────────────────────────────────────────────────────
COMPANY_SECTIONS = {
    "truecar": {
        "page": 0, "y_range": (453, 740), "y_start": 480.45,
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

STREAM_PATTERN = re.compile(
    r'\nq\n\.75 0 0 \.75 36 ([\d.]+) cm\n0 0 0 RG 0 0 0 rg\n.*?\nQ',
    re.DOTALL,
)


# ── Parsing ───────────────────────────────────────────────────────────────────

# Each entry: (normalized label, internal key, section type)
# Ordered longest-first so "ekn engineering" matches before "ekn",
# and "core competencies" matches before a hypothetical shorter overlap.
LABEL_MAP = [
    ('technical proficiencies', 'technical_proficiencies', 'rows'),
    ('technical_proficiencies', 'technical_proficiencies', 'rows'),
    ('tech proficiencies',      'technical_proficiencies', 'rows'),
    ('core competencies',       'core_competencies',       'rows'),
    ('core_competencies',       'core_competencies',       'rows'),
    ('ekn engineering',         'ekn',                     'bullets'),
    ('subheader',               'subheader',               'string'),
    ('summary',                 'summary',                 'string'),
    ('truecar',                 'truecar',                 'bullets'),
    ('true car',                'truecar',                 'bullets'),
    ('ekn',                     'ekn',                     'bullets'),
    ('pfizer',                  'pfizer',                  'bullets'),
    ('tanabe',                  'tanabe',                  'bullets'),
]

BULLET_COMPANIES = {'truecar', 'ekn', 'pfizer', 'tanabe'}


def match_label(line):
    """Return (internal_key, section_type, inline_text) if line starts with a known label, else None."""
    normalized = line.lower().strip()
    for label, key, stype in LABEL_MAP:
        prefix = label + ':'
        if normalized.startswith(prefix):
            inline = line[line.lower().find(prefix) + len(prefix):].strip()
            return key, stype, inline
    return None


def parse_updates(text):
    """
    Parse labeled input into a dict of updates.
    Only sections present in the input are included.
    """
    current_key  = None
    current_type = None
    inline       = ''
    body_lines   = []
    updates      = {}

    def flush():
        if current_key is None:
            return
        all_lines = []
        if inline:
            all_lines.append(inline)
        all_lines.extend(ln for ln in body_lines if ln.strip())

        if current_type == 'string':
            updates[current_key] = ' '.join(all_lines)

        elif current_type == 'rows':
            rows = []
            for ln in all_lines:
                items = [x.strip() for x in ln.split(',') if x.strip()]
                if items:
                    rows.append(items)
            updates[current_key] = rows

        elif current_type == 'bullets':
            bullets = []
            for ln in all_lines:
                b = ln.lstrip('-•').strip()
                if b:
                    bullets.append(b)
            updates[current_key] = bullets

    for line in text.split('\n'):
        match = match_label(line)
        if match:
            flush()
            current_key, current_type, inline = match
            body_lines = []
        elif current_key is not None:
            body_lines.append(line)

    flush()
    return updates


def split_even_rows(items, n_rows):
    """Split a flat list of items into n_rows as evenly as possible."""
    total = len(items)
    base, extra = divmod(total, n_rows)
    rows, i = [], 0
    for r in range(n_rows):
        size = base + (1 if r < extra else 0)
        rows.append(items[i:i + size])
        i += size
    return [r for r in rows if r]


def apply_updates(data, updates):
    """Merge parsed updates into the loaded YAML data dict."""
    for key in ('subheader', 'summary', 'core_competencies', 'technical_proficiencies'):
        if key in updates:
            if key == 'technical_proficiencies':
                # Flatten all items then split evenly across 2 rows
                all_items = [item for row in updates[key] for item in row]
                updates[key] = split_even_rows(all_items, 2)
            elif key == 'core_competencies':
                # Flatten all items then enforce exactly 3 per row
                all_items = [item for row in updates[key] for item in row]
                updates[key] = [all_items[i:i+3] for i in range(0, len(all_items), 3)]
            data[key] = updates[key]
            print(f"  Updated: {key}")

    for company in BULLET_COMPANIES:
        if company in updates:
            data['bullets'][company] = updates[company]
            print(f"  Updated: bullets/{company}")


# ── PDF helpers ───────────────────────────────────────────────────────────────

def load_yaml(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)


def save_yaml(path, data):
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def get_target_xref(doc, page_num):
    page = doc[page_num]
    for xref in page.get_contents():
        s = doc.xref_stream(xref).decode('latin-1')
        if '.75 0 0 .75 36' in s:
            return xref
    raise RuntimeError(f"Could not find cm-block stream on page {page_num}")


def remove_cm_blocks(doc, page_num, y_min, y_max):
    xref    = get_target_xref(doc, page_num)
    stream  = doc.xref_stream(xref).decode('latin-1')
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
    width = font_obj.text_length(text, fontsize=fontsize)
    x = 36.0 + (540.0 - width) / 2
    page.insert_text(
        fitz.Point(x, y), text,
        fontname=fontname, fontfile=fontfile,
        fontsize=fontsize, color=(0, 0, 0),
    )


def wrap_text(text, font_cal, max_width=529.0, fontsize=12):
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
    xref       = get_target_xref(doc, page_num)
    stream     = doc.xref_stream(xref).decode('latin-1')
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
    cfg    = COMPANY_SECTIONS[company]
    page   = doc[cfg["page"]]
    x_text = cfg["x_text"]
    a_asc  = ARIAL11_ASCENDER if cfg["arial_size"] == 11 else ARIAL12_ASCENDER
    y_lo, y_hi = cfg["y_range"]

    removed = remove_cm_blocks(doc, cfg["page"], y_lo, y_hi)
    print(f"  {company}: removed cm blocks at y={removed}")

    y = cfg["y_start"]
    for text in bullets:
        if not text.strip():
            continue
        lines = wrap_text(text, font_cal, max_width=cfg["wrap_width"])
        page.insert_text(
            fitz.Point(36.0, y + a_asc), "●",
            fontname="ArialNew", fontfile=ARIAL,
            fontsize=cfg["arial_size"], color=(0, 0, 0),
        )
        for i, line in enumerate(lines):
            page.insert_text(
                fitz.Point(x_text, y + CALIBRI_ASCENDER + i * CALIBRI_INNER_LINE_HT),
                line,
                fontname="Calibri", fontfile=CALIBRI_REGULAR,
                fontsize=12, color=(0, 0, 0),
            )
        y += (len(lines) - 1) * CALIBRI_INNER_LINE_HT + CALIBRI_BULLET_ADVANCE

    return y


def generate_pdf(data):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    dest      = os.path.join(BASE_DIR, f'Will Mino - Resume_copy_{timestamp}.pdf')
    dest_yaml = os.path.join(BASE_DIR, f'resume_copy_{timestamp}.yaml')

    shutil.copy(SRC_PDF, dest)
    shutil.copy(YAML_ORIGINAL, dest_yaml)
    print(f"\nCreated: {os.path.basename(dest)}")
    print(f"Created: {os.path.basename(dest_yaml)}")

    # Read Industries line text and y-position dynamically from the source PDF.
    # This makes the script robust to changes in the original PDF layout.
    _src = fitz.open(SRC_PDF)
    industries_text = ""
    industries_orig_y = None
    for _b in _src[0].get_text('dict')['blocks']:
        if _b['type'] == 0:
            for _ln in _b['lines']:
                for _sp in _ln['spans']:
                    if 'Industries' in _sp['text'] and industries_orig_y is None:
                        industries_orig_y = _sp['origin'][1]
                    if industries_orig_y is not None and abs(_sp['origin'][1] - industries_orig_y) < 3:
                        industries_text += _sp['text']
    _src.close()
    industries_text = industries_text.strip()
    if industries_orig_y is None:
        raise RuntimeError("Could not find Industries line in source PDF")

    doc          = fitz.open(dest)
    font_it      = fitz.Font(fontfile=CALIBRI_ITALIC)
    font_bold    = fitz.Font(fontfile=CALIBRI_BOLD)
    font_bold_it = fitz.Font(fontfile=CALIBRI_BOLD_ITAL)
    font_cal     = fitz.Font(fontfile=CALIBRI_REGULAR)

    subheader          = data.get("subheader", "")
    summary            = data.get("summary", "")
    core_competencies  = data.get("core_competencies", [])
    tech_proficiencies = data.get("technical_proficiencies", [])
    bullets            = data.get("bullets", {})

    # Compute summary delta early — needed before redaction (grey bar shifts) and TrueCar render
    summary_lines  = wrap_text(summary, font_cal, max_width=540.0)
    orig_sum_lines = wrap_text(load_yaml(YAML_ORIGINAL).get("summary", ""), font_cal, max_width=540.0)
    summary_delta  = (len(summary_lines) - len(orig_sum_lines)) * CALIBRI_INNER_LINE_HT
    if summary_delta != 0:
        COMPANY_SECTIONS["truecar"]["y_start"] += summary_delta
        print(f"  Summary delta={summary_delta:+.2f} — reflowing page 0 content...")

    print("\nRemoving header section cm blocks (page 0)...")
    removed_sub = remove_cm_blocks(doc, 0, y_min=98,  y_max=101)
    removed_sum = remove_cm_blocks(doc, 0, y_min=118, y_max=121)
    removed_cc  = remove_cm_blocks(doc, 0, y_min=250, y_max=320)
    removed_tp  = remove_cm_blocks(doc, 0, y_min=350, y_max=380)
    # Pre-remove cm blocks before apply_redactions so they are not duplicated when
    # apply_redactions copies the content stream into a new stream.
    # Both are re-inserted at their correct (possibly shifted) positions afterward.
    remove_cm_blocks(doc, 0, y_min=210, y_max=240)   # Industries
    remove_cm_blocks(doc, 0, y_min=453, y_max=740)   # TrueCar

    # Capture grey bar graphics before redaction, then restore them at shifted positions
    _p0 = doc[0]
    grey_bars = [{"rect": p["rect"], "fill": p["fill"]}
                 for p in _p0.get_drawings()
                 if p.get("fill") and 240 < p["rect"].y0 < 400]
    _p0.add_redact_annot(fitz.Rect(0, industries_orig_y - 8, _p0.rect.width, industries_orig_y + 16))  # Industries line + spacer
    _p0.add_redact_annot(fitz.Rect(0, 248, _p0.rect.width, 332))   # Core Competencies
    _p0.add_redact_annot(fitz.Rect(0, 348, _p0.rect.width, 396))   # Technical Proficiencies
    _p0.apply_redactions()
    for bar in grey_bars:
        r = bar["rect"]
        _p0.draw_rect(fitz.Rect(r.x0, r.y0 + summary_delta, r.x1, r.y1 + summary_delta),
                      color=None, fill=bar["fill"])

    # Re-insert section labels, shifted with summary so spacing is preserved
    cc_label_y = CC_LABEL_BASE_Y + summary_delta
    tp_label_y = 353.3 + summary_delta
    w_core = font_bold_it.text_length("Core ",        fontsize=14)
    w_comp = font_bold.text_length("Competencies", fontsize=14)
    _p0.insert_text(fitz.Point(36.0,                   cc_label_y), "Core ",        fontname="CalibriBI", fontfile=CALIBRI_BOLD_ITAL, fontsize=14, color=(0, 0, 0))
    _p0.insert_text(fitz.Point(36.0 + w_core,          cc_label_y), "Competencies", fontname="CalibriB",  fontfile=CALIBRI_BOLD,     fontsize=14, color=(0, 0, 0))
    _p0.insert_text(fitz.Point(36.0 + w_core + w_comp, cc_label_y), ":",            fontname="CalibriBI", fontfile=CALIBRI_BOLD_ITAL, fontsize=14, color=(0, 0, 0))
    _p0.insert_text(fitz.Point(36.0,                   tp_label_y), "Technical Proficiencies:", fontname="CalibriB", fontfile=CALIBRI_BOLD, fontsize=14, color=(0, 0, 0))
    _p0.insert_text(fitz.Point(36.0, INDUSTRIES_Y + summary_delta), industries_text,
                    fontname="CalibriBI", fontfile=CALIBRI_BOLD_ITAL, fontsize=12, color=(0, 0, 0))
    print("  Re-inserted: Core Competencies label")
    print("  Re-inserted: Technical Proficiencies label")
    print(f"  Re-inserted: Industries line at y={INDUSTRIES_Y + summary_delta:.1f}")

    print(f"  Subheader cm blocks removed: {removed_sub}")
    print(f"  Summary cm blocks removed:   {removed_sum}")
    print(f"  Core Comp cm blocks removed: {removed_cc}")
    print(f"  Tech Prof cm blocks removed: {removed_tp}")

    print("\nRendering company bullet sections...")
    render_company_section(doc, "truecar", bullets.get("truecar", []), font_cal)

    ekn_y_end = render_company_section(doc, "ekn", bullets.get("ekn", []), font_cal)
    delta_ekn = ekn_y_end - COMPANY_SECTIONS["ekn"]["original_y_end"]
    if delta_ekn != 0:
        print(f"  EKN delta={delta_ekn:+.2f} — reflowing Pfizer header...")
        shift_blocks_in_y_range(doc, 1, y_lo=300, y_hi=345, delta=delta_ekn)
        COMPANY_SECTIONS["pfizer"]["y_start"] += delta_ekn

    render_company_section(doc, "pfizer", bullets.get("pfizer", []), font_cal)

    tanabe_y_end = render_company_section(doc, "tanabe", bullets.get("tanabe", []), font_cal)
    delta_tanabe = tanabe_y_end - COMPANY_SECTIONS["tanabe"]["original_y_end"]
    if delta_tanabe != 0:
        print(f"  Tanabe delta={delta_tanabe:+.2f} — reflowing Education/Awards...")
        shift_blocks_in_y_range(doc, 2, y_lo=200, y_hi=400, delta=delta_tanabe)

    print("\nInserting header section text...")
    page0 = doc[0]

    insert_centered(page0, subheader, 118.683, font_bold, "CalibriB", CALIBRI_BOLD, fontsize=16)
    print(f"  Subheader: {subheader!r}")

    for i, line in enumerate(summary_lines):
        page0.insert_text(
            fitz.Point(36.0, 144.0 + i * CALIBRI_INNER_LINE_HT), line,
            fontname="Calibri", fontfile=CALIBRI_REGULAR,
            fontsize=12, color=(0, 0, 0),
        )
    print(f"  Summary: {len(summary_lines)} line(s)")

    cc_row_y = [cc_label_y + k * CALIBRI_INNER_LINE_HT for k in range(1, 5)]
    for i, row in enumerate(core_competencies[:4]):
        row_text = "  ".join(f"• {item}" for item in row)
        insert_centered(page0, row_text, cc_row_y[i], font_it, "CalibriIt", CALIBRI_ITALIC)
        print(f"  Core Comp row {i+1}: {row_text[:60]!r}")

    tp_row_y = [371.0 + summary_delta, 388.0 + summary_delta]
    for i, row in enumerate(tech_proficiencies[:2]):
        row_text = "  ".join(f"• {item}" for item in row)
        insert_centered(page0, row_text, tp_row_y[i], font_it, "CalibriIt", CALIBRI_ITALIC)
        print(f"  Tech Prof row {i+1}: {row_text[:60]!r}")

    tmp = '/tmp/resume_copy_out.pdf'
    doc.save(tmp, garbage=4, deflate=True)
    doc.close()
    os.replace(tmp, dest)
    print(f"\nSaved: {dest}")


# ── Main ──────────────────────────────────────────────────────────────────────

INSTRUCTIONS = """
Paste your resume updates below using section labels.
Only the sections you include will be updated — everything else stays the same.
When finished, type END on its own line and press Enter.

  Subheader:               text on the same line
  Summary:                 text on the same line (or next line)
  Core Competencies:       one row per line, items comma-separated (max 4 rows)
  Technical Proficiencies: one row per line, items comma-separated (max 2 rows)
  TrueCar:                 one bullet per line, leading dash optional
  EKN Engineering:         one bullet per line
  Pfizer:                  one bullet per line
  Tanabe:                  one bullet per line

Example:
  Subheader: Senior Data Analyst | 9 Years Experience
  TrueCar:
  - Led pricing analytics for OEM incentive programs.
  - Built dashboards tracking $7M in annual revenue.
──────────────────────────────────────────────────────
"""


def read_input():
    result = []

    root = tk.Tk()
    root.title("Resume Updater")
    root.geometry("700x600")
    root.resizable(True, True)

    # Instructions label at top
    tk.Label(root, text=INSTRUCTIONS, justify="left", font=("Courier", 10),
             anchor="w").pack(fill="x", padx=10, pady=(10, 0))

    # Text box in the middle
    text_box = tk.Text(root, font=("Courier", 12), wrap="word", height=15)
    text_box.pack(fill="both", expand=True, padx=10, pady=10)
    text_box.focus_set()

    # Submit button pinned at the bottom
    def submit():
        result.append(text_box.get("1.0", "end-1c"))
        root.after(1, root.destroy)

    btn = tk.Button(root, text="Submit", font=("Arial", 14, "bold"),
                    bg="#4CAF50", fg="white", height=2, command=submit)
    btn.pack(fill="x", padx=10, pady=(0, 10))

    root.mainloop()
    return result[0] if result else ""


def main():
    data = load_yaml(YAML_WORKING)
    print("Loaded resume.yaml")

    raw = read_input()
    updates = parse_updates(raw)

    if not updates:
        print("\nNo recognized sections found — nothing to update.")
        return

    print("\nApplying updates...")
    apply_updates(data, updates)

    print("\nSaving resume.yaml...")
    save_yaml(YAML_WORKING, data)

    generate_pdf(data)
    print("\nDone.")


if __name__ == "__main__":
    main()
