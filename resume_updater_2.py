"""
resume_updater_2.py

Interactive CLI to update any section of Will Mino's resume.
Prompts the user to select a section and input new content,
updates resume.yaml, then generates a new timestamped PDF copy.

Usage:
    /Applications/anaconda3/bin/python3 resume_updater_2.py

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

# ── Spacing constants ─────────────────────────────────────────────────────────
CALIBRI_ASCENDER       = 9.0
CALIBRI_INNER_LINE_HT  = 14.65
CALIBRI_BULLET_ADVANCE = 14.65
ARIAL11_ASCENDER       = 9.958
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

COMPANY_LABELS = {
    "truecar": "TrueCar",
    "ekn":     "EKN Engineering",
    "pfizer":  "Pfizer",
    "tanabe":  "Tanabe",
}


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
    xref   = get_target_xref(doc, page_num)
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


# ── Interactive prompts ───────────────────────────────────────────────────────

MAIN_MENU = """
╔══════════════════════════════════════╗
║       RESUME UPDATER — MAIN MENU     ║
╠══════════════════════════════════════╣
║  1. Subheader                        ║
║  2. Summary                          ║
║  3. Core Competencies                ║
║  4. Technical Proficiencies          ║
║  5. TrueCar bullets                  ║
║  6. EKN Engineering bullets          ║
║  7. Pfizer bullets                   ║
║  8. Tanabe bullets                   ║
╠══════════════════════════════════════╣
║  9. Save YAML & generate PDF         ║
║  0. Quit without saving              ║
╚══════════════════════════════════════╝"""

BULLET_HELP = """
  Commands:
    A       — Add a new bullet at the end
    E <#>   — Edit bullet number # (e.g. "E 3")
    D <#>   — Delete bullet number #
    R       — Replace all bullets (enter fresh list)
    K / ↵   — Keep as-is and return to main menu
"""


def _input(prompt=""):
    """Thin wrapper so prompts are visually distinct."""
    return input(prompt)


def show_current(label, value):
    print(f"\n  Current {label}:")
    if isinstance(value, str):
        print(f"    {value}")
    elif isinstance(value, list):
        for i, item in enumerate(value, 1):
            if isinstance(item, list):
                print(f"    Row {i}: {', '.join(item)}")
            else:
                print(f"    {i}. {item}")


def edit_subheader(data):
    show_current("Subheader", data["subheader"])
    val = _input("\n  New subheader (Enter to keep): ").strip()
    if val:
        data["subheader"] = val
        print(f"  ✓ Subheader updated.")
    else:
        print("  No change.")


def edit_summary(data):
    show_current("Summary", data["summary"])
    print("  (Enter a single paragraph; press Enter with no text to keep current)")
    val = _input("\n  New summary: ").strip()
    if val:
        data["summary"] = val
        print("  ✓ Summary updated.")
    else:
        print("  No change.")


def edit_row_section(data, key, label, max_rows):
    """Generic editor for core_competencies and technical_proficiencies."""
    current = data.get(key, [])
    show_current(label, current)

    print(f"\n  Enter items for each row as comma-separated values.")
    print(f"  Press Enter to keep a row unchanged. Type 'clear' to remove a row.")
    print(f"  (Max {max_rows} rows)\n")

    new_rows = []
    for i in range(max_rows):
        current_row = current[i] if i < len(current) else []
        row_display = ', '.join(current_row) if current_row else "empty"
        raw = _input(f"  Row {i+1} [{row_display}]: ").strip()

        if raw == '':
            if current_row:
                new_rows.append(current_row)
            # else: row was already empty — skip it
        elif raw.lower() == 'clear':
            print(f"    Row {i+1} cleared.")
        else:
            items = [x.strip() for x in raw.split(',') if x.strip()]
            if items:
                new_rows.append(items)

    data[key] = new_rows
    print(f"  ✓ {label} updated ({len(new_rows)} row(s)).")


def _parse_bullet_num(cmd_tail, bullets):
    """Extract integer index from command tail or prompt the user."""
    num_str = cmd_tail.strip()
    if not num_str:
        num_str = _input("  Bullet #: ").strip()
    try:
        idx = int(num_str) - 1
        if 0 <= idx < len(bullets):
            return idx
        print(f"  Invalid number. Enter 1–{len(bullets)}.")
    except ValueError:
        print("  Please enter a valid number.")
    return None


def show_bullets(bullets):
    if not bullets:
        print("  (no bullets)")
        return
    for i, b in enumerate(bullets, 1):
        print(f"  {i}. {b}")


def edit_bullets(data, company):
    label   = COMPANY_LABELS[company]
    bullets = list(data["bullets"].get(company, []))

    print(f"\n  ── {label} ──")
    show_bullets(bullets)
    print(BULLET_HELP)

    while True:
        raw = _input("  Action: ").strip()
        cmd = raw.upper()

        # Keep / done
        if cmd in ('', 'K'):
            break

        # Add
        elif cmd == 'A':
            text = _input("  New bullet text: ").strip()
            if text:
                bullets.append(text)
                print(f"  ✓ Added as bullet {len(bullets)}.")
                show_bullets(bullets)

        # Edit
        elif cmd.startswith('E'):
            idx = _parse_bullet_num(cmd[1:], bullets)
            if idx is not None:
                print(f"  Current: {bullets[idx]}")
                text = _input("  New text (Enter to cancel): ").strip()
                if text:
                    bullets[idx] = text
                    print(f"  ✓ Bullet {idx+1} updated.")
                    show_bullets(bullets)

        # Delete
        elif cmd.startswith('D'):
            idx = _parse_bullet_num(cmd[1:], bullets)
            if idx is not None:
                removed = bullets.pop(idx)
                print(f"  ✓ Deleted: {removed}")
                show_bullets(bullets)

        # Replace all
        elif cmd == 'R':
            print("  Enter bullets one per line. Empty line when done.")
            new_bullets = []
            while True:
                line = _input(f"  [{len(new_bullets)+1}]: ").strip()
                if not line:
                    break
                new_bullets.append(line)
            if new_bullets:
                bullets = new_bullets
                print(f"  ✓ Replaced with {len(bullets)} bullet(s).")
                show_bullets(bullets)
            else:
                print("  No bullets entered — keeping original.")

        else:
            print("  Unknown command. Use A, E <#>, D <#>, R, or K.")

    data["bullets"][company] = bullets
    print(f"  ✓ {label} bullets saved.")


# ── PDF generation (same logic as resume_updater.py) ─────────────────────────

def generate_pdf(data):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    dest      = os.path.join(BASE_DIR, f'Will Mino - Resume_copy_{timestamp}.pdf')
    dest_yaml = os.path.join(BASE_DIR, f'resume_copy_{timestamp}.yaml')

    shutil.copy(SRC_PDF, dest)
    shutil.copy(YAML_ORIGINAL, dest_yaml)
    print(f"\nCreated: {os.path.basename(dest)}")
    print(f"Created: {os.path.basename(dest_yaml)}")

    doc       = fitz.open(dest)
    font_it   = fitz.Font(fontfile=CALIBRI_ITALIC)
    font_bold = fitz.Font(fontfile=CALIBRI_BOLD)
    font_cal  = fitz.Font(fontfile=CALIBRI_REGULAR)

    subheader          = data.get("subheader", "")
    summary            = data.get("summary", "")
    core_competencies  = data.get("core_competencies", [])
    tech_proficiencies = data.get("technical_proficiencies", [])
    bullets            = data.get("bullets", {})

    # Remove header cm blocks
    print("\nRemoving header section cm blocks (page 0)...")
    removed_sub = remove_cm_blocks(doc, 0, y_min=98,  y_max=101)
    removed_sum = remove_cm_blocks(doc, 0, y_min=118, y_max=121)
    removed_cc  = remove_cm_blocks(doc, 0, y_min=250, y_max=320)
    removed_tp  = remove_cm_blocks(doc, 0, y_min=350, y_max=380)
    print(f"  Subheader cm blocks removed: {removed_sub}")
    print(f"  Summary cm blocks removed:   {removed_sum}")
    print(f"  Core Comp cm blocks removed: {removed_cc}")
    print(f"  Tech Prof cm blocks removed: {removed_tp}")

    # Render company bullet sections
    print("\nRendering company bullet sections...")

    render_company_section(doc, "truecar", bullets.get("truecar", []), font_cal)

    ekn_y_end  = render_company_section(doc, "ekn", bullets.get("ekn", []), font_cal)
    delta_ekn  = ekn_y_end - COMPANY_SECTIONS["ekn"]["original_y_end"]
    if delta_ekn != 0:
        print(f"  EKN delta={delta_ekn:+.2f} — reflowing Pfizer header...")
        shift_blocks_in_y_range(doc, 1, y_lo=300, y_hi=345, delta=delta_ekn)
        COMPANY_SECTIONS["pfizer"]["y_start"] += delta_ekn

    render_company_section(doc, "pfizer", bullets.get("pfizer", []), font_cal)

    tanabe_y_end  = render_company_section(doc, "tanabe", bullets.get("tanabe", []), font_cal)
    delta_tanabe  = tanabe_y_end - COMPANY_SECTIONS["tanabe"]["original_y_end"]
    if delta_tanabe != 0:
        print(f"  Tanabe delta={delta_tanabe:+.2f} — reflowing Education/Awards...")
        shift_blocks_in_y_range(doc, 2, y_lo=200, y_hi=400, delta=delta_tanabe)

    # Insert header text
    print("\nInserting header section text...")
    page0 = doc[0]

    insert_centered(page0, subheader, 118.683, font_bold, "CalibriB", CALIBRI_BOLD, fontsize=16)
    print(f"  Subheader: {subheader!r}")

    page0.insert_text(
        fitz.Point(36.0, 144.0), summary,
        fontname="Calibri", fontfile=CALIBRI_REGULAR,
        fontsize=12, color=(0, 0, 0),
    )
    print(f"  Summary: {summary[:60]!r}{'...' if len(summary) > 60 else ''}")

    cc_y_values = [269.0, 286.0, 303.0, 320.0]
    for i, row in enumerate(core_competencies[:4]):
        row_text = "  ".join(f"• {item}" for item in row)
        insert_centered(page0, row_text, cc_y_values[i], font_it, "CalibriIt", CALIBRI_ITALIC)
        print(f"  Core Comp row {i+1}: {row_text[:60]!r}")

    tp_y_values = [371.0, 388.0]
    for i, row in enumerate(tech_proficiencies[:2]):
        row_text = "  ".join(f"• {item}" for item in row)
        insert_centered(page0, row_text, tp_y_values[i], font_it, "CalibriIt", CALIBRI_ITALIC)
        print(f"  Tech Prof row {i+1}: {row_text[:60]!r}")

    tmp = '/tmp/resume_copy_out.pdf'
    doc.save(tmp, garbage=4, deflate=True)
    doc.close()
    os.replace(tmp, dest)
    print(f"\nSaved: {dest}")


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    data = load_yaml(YAML_WORKING)
    print("Loaded resume.yaml")

    while True:
        print(MAIN_MENU)
        choice = _input("  Enter choice: ").strip()

        if choice == '1':
            edit_subheader(data)
        elif choice == '2':
            edit_summary(data)
        elif choice == '3':
            edit_row_section(data, "core_competencies", "Core Competencies", max_rows=4)
        elif choice == '4':
            edit_row_section(data, "technical_proficiencies", "Technical Proficiencies", max_rows=2)
        elif choice == '5':
            edit_bullets(data, "truecar")
        elif choice == '6':
            edit_bullets(data, "ekn")
        elif choice == '7':
            edit_bullets(data, "pfizer")
        elif choice == '8':
            edit_bullets(data, "tanabe")
        elif choice == '9':
            print("\nSaving resume.yaml...")
            save_yaml(YAML_WORKING, data)
            print("Saved.")
            generate_pdf(data)
            print("\nDone.")
            break
        elif choice == '0':
            print("\nQuitting without saving.")
            break
        else:
            print("  Invalid choice — enter 0–9.")


if __name__ == "__main__":
    main()
