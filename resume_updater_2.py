"""
resume_updater_2.py

Interactive resume editor. Prompts the user to select which sections to update,
collects new content, confirms changes, then applies all edits in a single pass.

Usage:
    /Applications/anaconda3/bin/python3 resume_updater_2.py

Requires: PyMuPDF (fitz), PyYAML
"""

import copy
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
CALIBRI_ASCENDER       = 9.0
CALIBRI_INNER_LINE_HT  = 14.65
CALIBRI_BULLET_ADVANCE = 14.65
ARIAL11_ASCENDER       =  9.958
ARIAL12_ASCENDER       = 10.863

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

STREAM_PATTERN = re.compile(
    r'\nq\n\.75 0 0 \.75 36 ([\d.]+) cm\n0 0 0 RG 0 0 0 rg\n.*?\nQ',
    re.DOTALL,
)

# ── Section menu ──────────────────────────────────────────────────────────────
MENU = [
    ("1", "subheader",           "Subheader"),
    ("2", "summary",             "Summary"),
    ("3", "core_competencies",   "Core Competencies"),
    ("4", "technical_proficiencies", "Technical Proficiencies"),
    ("5", "truecar",             "TrueCar Bullets"),
    ("6", "ekn",                 "EKN Bullets"),
    ("7", "pfizer",              "Pfizer Bullets"),
    ("8", "tanabe",              "Tanabe Bullets"),
]

HEADER_SECTIONS  = {"subheader", "summary", "core_competencies", "technical_proficiencies"}
BULLET_COMPANIES = {"truecar", "ekn", "pfizer", "tanabe"}


# ═══════════════════════════════════════════════════════════════════════════════
# PDF helpers (same as resume_updater.py)
# ═══════════════════════════════════════════════════════════════════════════════

def load_yaml(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)


def save_yaml(path, data):
    with open(path, 'w') as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def get_target_xref(doc, page_num):
    for xref in doc[page_num].get_contents():
        s = doc.xref_stream(xref).decode('latin-1')
        if '.75 0 0 .75 36' in s:
            return xref
    raise RuntimeError(f"Could not find cm-block stream on page {page_num}")


def remove_cm_blocks(doc, page_num, y_min, y_max):
    xref   = get_target_xref(doc, page_num)
    stream = doc.xref_stream(xref).decode('latin-1')
    removed = []

    def replacer(m):
        y = float(m.group(1))
        if y_min < y < y_max:
            removed.append(round(y, 2))
            return ''
        return m.group(0)

    doc.update_stream(xref, STREAM_PATTERN.sub(replacer, stream).encode('latin-1'))
    return removed


def insert_centered(page, text, y, font_obj, fontname, fontfile, fontsize=12):
    width = font_obj.text_length(text, fontsize=fontsize)
    x = 36.0 + (540.0 - width) / 2
    page.insert_text(fitz.Point(x, y), text,
        fontname=fontname, fontfile=fontfile, fontsize=fontsize, color=(0, 0, 0))


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
    xref   = get_target_xref(doc, page_num)
    stream = doc.xref_stream(xref).decode('latin-1')
    pat    = re.compile(r'(\.75 0 0 \.75 36 )([\d.]+)( cm\n)')

    def shifter(m):
        y = float(m.group(2))
        if y_lo <= y <= y_hi:
            return m.group(1) + f"{y + delta:.3f}" + m.group(3)
        return m.group(0)

    doc.update_stream(xref, pat.sub(shifter, stream).encode('latin-1'))
    print(f"  page {page_num}: shifted y={y_lo}–{y_hi} by delta={delta:+.2f}")


def render_company_section(doc, company, bullets, font_cal):
    cfg   = COMPANY_SECTIONS[company]
    page  = doc[cfg["page"]]
    a_asc = ARIAL11_ASCENDER if cfg["arial_size"] == 11 else ARIAL12_ASCENDER
    y_lo, y_hi = cfg["y_range"]

    removed = remove_cm_blocks(doc, cfg["page"], y_lo, y_hi)
    print(f"  {company}: removed cm blocks at y={removed}")

    y = cfg["y_start"]
    for text in bullets:
        if not text.strip():
            continue
        lines = wrap_text(text, font_cal, max_width=cfg["wrap_width"])
        page.insert_text(fitz.Point(36.0, y + a_asc), "●",
            fontname="ArialNew", fontfile=ARIAL,
            fontsize=cfg["arial_size"], color=(0, 0, 0))
        for i, line in enumerate(lines):
            page.insert_text(
                fitz.Point(cfg["x_text"], y + CALIBRI_ASCENDER + i * CALIBRI_INNER_LINE_HT),
                line, fontname="Calibri", fontfile=CALIBRI_REGULAR,
                fontsize=12, color=(0, 0, 0))
        y += (len(lines) - 1) * CALIBRI_INNER_LINE_HT + CALIBRI_BULLET_ADVANCE

    return y


# ═══════════════════════════════════════════════════════════════════════════════
# Interactive prompting
# ═══════════════════════════════════════════════════════════════════════════════

def hr(char="─", width=60):
    print(char * width)


def show_current(data):
    """Print a formatted view of the current resume.yaml content."""
    hr("═")
    print("  CURRENT resume.yaml CONTENT")
    hr("═")

    print(f"\n[1] Subheader:\n    {data.get('subheader', '')}\n")

    summary = data.get('summary', '')
    print(f"[2] Summary:\n    {summary}\n")

    print("[3] Core Competencies:")
    for i, row in enumerate(data.get('core_competencies', []), 1):
        print(f"    Row {i}: {' | '.join(row)}")
    print()

    print("[4] Technical Proficiencies:")
    for i, row in enumerate(data.get('technical_proficiencies', []), 1):
        print(f"    Row {i}: {' | '.join(row)}")
    print()

    bullets = data.get('bullets', {})
    for num, key, label in [("5","truecar","TrueCar"), ("6","ekn","EKN"),
                             ("7","pfizer","Pfizer"), ("8","tanabe","Tanabe")]:
        items = bullets.get(key, [])
        print(f"[{num}] {label} Bullets ({len(items)} bullets):")
        for j, b in enumerate(items, 1):
            preview = b[:80] + ("..." if len(b) > 80 else "")
            print(f"    {j}. {preview}")
        print()


def prompt_selection():
    """Ask which sections to update. Returns a set of section keys."""
    hr()
    print("Which sections do you want to update?")
    print("Enter numbers separated by commas (e.g. 1,3,5), or 'all':")
    print("  1=Subheader  2=Summary  3=Core Comp  4=Tech Prof")
    print("  5=TrueCar    6=EKN      7=Pfizer      8=Tanabe")
    hr()

    raw = input("> ").strip().lower()
    if raw == "all":
        return {key for _, key, _ in MENU}

    chosen = set()
    num_to_key = {num: key for num, key, _ in MENU}
    for token in raw.split(","):
        token = token.strip()
        if token in num_to_key:
            chosen.add(num_to_key[token])
        else:
            print(f"  (ignoring unrecognized option: {token!r})")

    return chosen


def prompt_text(label, current):
    """Prompt for a single-line text field. Empty input keeps current value."""
    print(f"\n{label}")
    print(f"  Current: {current!r}")
    print("  Enter new text (or press Enter to keep current):")
    val = input("  > ").strip()
    return val if val else current


def prompt_rows(label, current_rows, max_rows, hint):
    """
    Prompt for a list-of-lists section (core comp or tech prof).
    Each row's items are entered pipe-separated.
    Returns a list of lists.
    """
    print(f"\n{label}  (max {max_rows} rows, items separated by |)")
    print(f"  {hint}")
    print("  Press Enter on a row to keep it. Type 'clear' to remove a row.")

    new_rows = []
    # Prompt for each existing row
    for i, row in enumerate(current_rows, 1):
        current_str = " | ".join(row)
        print(f"  Row {i} current: {current_str}")
        val = input(f"  Row {i} new    : ").strip()
        if val.lower() == "clear":
            print(f"    (row {i} cleared)")
        elif val:
            items = [item.strip() for item in val.split("|") if item.strip()]
            new_rows.append(items)
        else:
            new_rows.append(row)  # keep current

    # Offer additional rows if under the max
    next_row = len(current_rows) + 1
    while next_row <= max_rows:
        print(f"  Row {next_row} (new, press Enter to stop adding rows):")
        val = input("  > ").strip()
        if not val:
            break
        items = [item.strip() for item in val.split("|") if item.strip()]
        if items:
            new_rows.append(items)
        next_row += 1

    return new_rows


def prompt_bullets(label, current_bullets):
    """
    Prompt for a bullet list. Shows current bullets numbered; user can
    edit each, clear individual ones, or add new ones at the end.
    Returns a list of strings.
    """
    print(f"\n{label}")
    print("  For each bullet: enter new text, press Enter to keep, or type 'clear' to remove.")

    new_bullets = []

    # Edit / keep / clear existing bullets
    for i, bullet in enumerate(current_bullets, 1):
        preview = bullet[:80] + ("..." if len(bullet) > 80 else "")
        print(f"\n  [{i}] Current: {preview}")
        if len(bullet) > 80:
            print(f"       (full)  : {bullet}")
        val = input("        New    : ").strip()
        if val.lower() == "clear":
            print(f"    (bullet {i} removed)")
        elif val:
            new_bullets.append(val)
        else:
            new_bullets.append(bullet)  # keep current

    # Add new bullets
    print("\n  Add new bullets (one per line, press Enter on blank line to finish):")
    while True:
        val = input("  + ").strip()
        if not val:
            break
        new_bullets.append(val)

    return new_bullets


def collect_changes(data, selected):
    """Walk through selected sections and collect new values from the user."""
    changes = {}

    if "subheader" in selected:
        changes["subheader"] = prompt_text("SUBHEADER", data.get("subheader", ""))

    if "summary" in selected:
        changes["summary"] = prompt_text("SUMMARY", data.get("summary", ""))

    if "core_competencies" in selected:
        changes["core_competencies"] = prompt_rows(
            "CORE COMPETENCIES",
            data.get("core_competencies", []),
            max_rows=4,
            hint="Example row: Funnel & Conversion Analysis | A/B Testing | Data Modeling",
        )

    if "technical_proficiencies" in selected:
        changes["technical_proficiencies"] = prompt_rows(
            "TECHNICAL PROFICIENCIES",
            data.get("technical_proficiencies", []),
            max_rows=2,
            hint="Example row: SQL | Python | Tableau | Excel",
        )

    bullet_labels = {
        "truecar": "TRUECAR BULLETS",
        "ekn":     "EKN BULLETS",
        "pfizer":  "PFIZER BULLETS",
        "tanabe":  "TANABE BULLETS",
    }
    for company, label in bullet_labels.items():
        if company in selected:
            current = data.get("bullets", {}).get(company, [])
            changes[company] = prompt_bullets(label, current)

    return changes


def confirm_changes(changes, data):
    """Show a diff-style summary and ask the user to confirm."""
    hr("═")
    print("  CHANGES TO APPLY")
    hr("═")

    if "subheader" in changes:
        print(f"\nSubheader:\n  OLD: {data.get('subheader','')!r}\n  NEW: {changes['subheader']!r}")

    if "summary" in changes:
        print(f"\nSummary:\n  OLD: {data.get('summary','')!r}\n  NEW: {changes['summary']!r}")

    if "core_competencies" in changes:
        print("\nCore Competencies:")
        for i, row in enumerate(changes["core_competencies"], 1):
            print(f"  Row {i}: {' | '.join(row)}")

    if "technical_proficiencies" in changes:
        print("\nTechnical Proficiencies:")
        for i, row in enumerate(changes["technical_proficiencies"], 1):
            print(f"  Row {i}: {' | '.join(row)}")

    for company in ("truecar", "ekn", "pfizer", "tanabe"):
        if company in changes:
            print(f"\n{company.upper()} Bullets ({len(changes[company])} total):")
            for j, b in enumerate(changes[company], 1):
                print(f"  {j}. {b[:80]}{'...' if len(b) > 80 else ''}")

    hr()
    answer = input("Apply these changes? (y/n): ").strip().lower()
    return answer == "y"


# ═══════════════════════════════════════════════════════════════════════════════
# Apply changes to PDF
# ═══════════════════════════════════════════════════════════════════════════════

def apply_changes(dest, data, changes):
    font_it   = fitz.Font(fontfile=CALIBRI_ITALIC)
    font_bold = fitz.Font(fontfile=CALIBRI_BOLD)
    font_cal  = fitz.Font(fontfile=CALIBRI_REGULAR)

    doc = fitz.open(dest)

    # ── Header section removals (all in one stream pass per section) ──────────
    header_keys = {"subheader", "summary", "core_competencies", "technical_proficiencies"}
    changing_headers = header_keys & changes.keys()

    if changing_headers:
        print("\nRemoving header section cm blocks...")
        ranges = {
            "subheader":               (0, 98,  101),
            "summary":                 (0, 118, 121),
            "core_competencies":       (0, 250, 320),
            "technical_proficiencies": (0, 350, 380),
        }
        for key in header_keys:
            if key in changes:
                page_num, y_min, y_max = ranges[key]
                removed = remove_cm_blocks(doc, page_num, y_min, y_max)
                print(f"  {key}: removed {removed}")

    # ── Bullet sections ───────────────────────────────────────────────────────
    # Must handle EKN→Pfizer reflow and Tanabe→Education reflow if those change.
    # Even if only one of EKN/Pfizer is selected, we still need to reflow correctly.
    # Strategy: render in order; if EKN changes, adjust Pfizer y_start regardless
    # of whether Pfizer bullets are being changed (so the header reflow is correct).

    updating_bullets = BULLET_COMPANIES & changes.keys()

    if updating_bullets:
        print("\nRendering bullet sections...")

    if "truecar" in changes:
        render_company_section(doc, "truecar", changes["truecar"], font_cal)

    # EKN and Pfizer are coupled via reflow
    if "ekn" in changes or "pfizer" in changes:
        ekn_bullets = changes.get("ekn") or data.get("bullets", {}).get("ekn", [])
        ekn_y_end   = render_company_section(doc, "ekn", ekn_bullets, font_cal)
        delta_ekn   = ekn_y_end - COMPANY_SECTIONS["ekn"]["original_y_end"]
        if delta_ekn != 0:
            print(f"  EKN delta={delta_ekn:+.2f} — reflowing Pfizer header...")
            shift_blocks_in_y_range(doc, 1, y_lo=300, y_hi=345, delta=delta_ekn)
            COMPANY_SECTIONS["pfizer"]["y_start"] += delta_ekn
        pfizer_bullets = changes.get("pfizer") or data.get("bullets", {}).get("pfizer", [])
        render_company_section(doc, "pfizer", pfizer_bullets, font_cal)
    elif "ekn" in changes:
        pass  # already handled above

    if "tanabe" in changes:
        tanabe_y_end  = render_company_section(doc, "tanabe", changes["tanabe"], font_cal)
        delta_tanabe  = tanabe_y_end - COMPANY_SECTIONS["tanabe"]["original_y_end"]
        if delta_tanabe != 0:
            print(f"  Tanabe delta={delta_tanabe:+.2f} — reflowing Education/Awards...")
            shift_blocks_in_y_range(doc, 2, y_lo=200, y_hi=400, delta=delta_tanabe)

    # ── Insert header text ────────────────────────────────────────────────────
    if changing_headers:
        print("\nInserting header section text...")
        page0 = doc[0]

        if "subheader" in changes:
            insert_centered(page0, changes["subheader"], 118.683,
                font_bold, "CalibriB", CALIBRI_BOLD, fontsize=16)
            print(f"  Subheader: {changes['subheader']!r}")

        if "summary" in changes:
            page0.insert_text(fitz.Point(36.0, 144.0), changes["summary"],
                fontname="Calibri", fontfile=CALIBRI_REGULAR,
                fontsize=12, color=(0, 0, 0))
            summary_preview = changes["summary"][:60]
            print(f"  Summary: {summary_preview!r}{'...' if len(changes['summary']) > 60 else ''}")

        cc_y_values = [269.0, 286.0, 303.0, 320.0]
        if "core_competencies" in changes:
            for i, row in enumerate(changes["core_competencies"][:4]):
                row_text = "  ".join(f"• {item}" for item in row)
                insert_centered(page0, row_text, cc_y_values[i],
                    font_it, "CalibriIt", CALIBRI_ITALIC)
                print(f"  Core Comp row {i+1}: {row_text[:60]!r}")

        tp_y_values = [371.0, 388.0]
        if "technical_proficiencies" in changes:
            for i, row in enumerate(changes["technical_proficiencies"][:2]):
                row_text = "  ".join(f"• {item}" for item in row)
                insert_centered(page0, row_text, tp_y_values[i],
                    font_it, "CalibriIt", CALIBRI_ITALIC)
                print(f"  Tech Prof row {i+1}: {row_text[:60]!r}")

    # ── Save ──────────────────────────────────────────────────────────────────
    tmp = '/tmp/resume_copy_out.pdf'
    doc.save(tmp, garbage=4, deflate=True)
    doc.close()
    os.replace(tmp, dest)
    print(f"\nSaved: {dest}")


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    # Load current state
    data = load_yaml(YAML_WORKING)

    # Show current content
    show_current(data)

    # User picks sections
    selected = prompt_selection()
    if not selected:
        print("No sections selected. Exiting.")
        return

    # Collect new values
    changes = collect_changes(data, selected)
    if not changes:
        print("No changes entered. Exiting.")
        return

    # Confirm
    if not confirm_changes(changes, data):
        print("Cancelled.")
        return

    # Create timestamped PDF + YAML copy
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    dest      = os.path.join(BASE_DIR, f'Will Mino - Resume_copy_{timestamp}.pdf')
    dest_yaml = os.path.join(BASE_DIR, f'resume_copy_{timestamp}.yaml')

    shutil.copy(SRC_PDF, dest)
    shutil.copy(YAML_ORIGINAL, dest_yaml)
    print(f"\nCreated: {os.path.basename(dest)}")
    print(f"Created: {os.path.basename(dest_yaml)}")

    # Apply PDF edits
    apply_changes(dest, data, changes)

    # Update resume.yaml with changed values
    new_data = copy.deepcopy(data)
    for key in ("subheader", "summary", "core_competencies", "technical_proficiencies"):
        if key in changes:
            new_data[key] = changes[key]
    for company in BULLET_COMPANIES:
        if company in changes:
            new_data.setdefault("bullets", {})[company] = changes[company]

    save_yaml(YAML_WORKING, new_data)
    print(f"Updated: resume.yaml")

    # Update the copy YAML to reflect what was actually written
    save_yaml(dest_yaml, new_data)
    print(f"Updated: {os.path.basename(dest_yaml)}")

    print("\nDone.")


if __name__ == "__main__":
    main()
