---
name: resume-test-copy
description: Creates a uniquely named test copy of Will Mino's resume PDF. Can edit any section (subheader, summary, core competencies, technical proficiencies, or job bullet points for TrueCar, EKN Engineering, Pfizer, Tanabe) — removes existing text and writes replacement text in the correct font. Use when asked to make a test copy or update any resume section.
user-invocable: true
---

## Phase 0 — Plan (ALWAYS do this first)

Before touching any PDF, read the current resume content and draft the proposed changes.

**File reference:**

| File | Purpose |
|---|---|
| `resume_original.yaml` | ORIGINAL unedited text from `Will Mino - Resume.pdf`. **Never edit directly.** Used as the template for per-copy YAMLs. |
| `resume.yaml` | Working file — reflects the desired changes for the NEXT copy. Update this after approval. |
| `resume_copy_TIMESTAMP.yaml` | Created automatically in Step 1 alongside each PDF copy. Tracks exactly what text is in that specific copy. Update it after applying edits (same values you write to resume.yaml). |

**Step 0a — Read current content from `resume.yaml`**

```
/Users/willmino/Library/Claude/Resume_Github_Project/resume.yaml
```

This file is the source of truth for all editable resume text. Read it to understand what is currently in each section.

**Step 0b — Draft the changes**

Based on the user's requirements, determine:
- Which sections need to change (subheader, summary, core_competencies, technical_proficiencies, and/or which company bullets)
- What the new text should be for each affected section

**Step 0c — Update `resume.yaml` with new text**

After approval, write the new values into `resume.yaml` so it stays in sync with the PDF.

---

## Phase 1 — Execute PDF edits

Follow these exact steps using `/Applications/anaconda3/bin/python3`.

**Important:** Create the unique copy ONCE at the start. All edits overwrite that same file — do not generate new filenames mid-task.

**Critical — single-pass edits:** When editing multiple sections, do ALL `update_stream` removals and ALL `insert_text`/`insert_centered` insertions in a **single script** before saving. Running separate scripts per section causes inserted content to accumulate as extra streams; subsequent `garbage=4` saves do not de-duplicate them, resulting in doubled text in the PDF.

**Stream index note:** After a prior edit session the PDF may have more than one content stream. Always find the stream that contains `.75 0 0 .75 36` cm blocks rather than assuming it is `get_contents()[0]`. Example: iterate `doc[0].get_contents()` and pick the xref whose decoded stream contains that pattern.

## Step 1 — Create the unique copy

Generate a unique filename and copy the source. Store the path in a variable — every subsequent step uses this same path.

```python
import shutil, os
from datetime import datetime

src           = '/Users/willmino/Library/Claude/Resume_Github_Project/Will Mino - Resume.pdf'
yaml_original = '/Users/willmino/Library/Claude/Resume_Github_Project/resume_original.yaml'
dest_dir      = '/Users/willmino/Library/Claude/Resume_Github_Project'

timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
dest      = os.path.join(dest_dir, f'Will Mino - Resume_copy_{timestamp}.pdf')
dest_yaml = os.path.join(dest_dir, f'resume_copy_{timestamp}.yaml')

shutil.copy(src, dest)
shutil.copy(yaml_original, dest_yaml)
print(f"Created: {os.path.basename(dest)}")
print(f"Created: {os.path.basename(dest_yaml)}")
# Store dest and dest_yaml — all further steps write to these same paths.
# After applying edits, update dest_yaml to match the final state of the copy
# (same values written to resume.yaml in Step 0c).
```

## Step 2 — Extract font info from the copy

```python
import fitz

doc = fitz.open(dest)
for b in doc[0].get_text("dict")["blocks"]:
    if b.get("type") != 0:
        continue
    for line in b["lines"]:
        for span in line["spans"]:
            if "Results-driven" in span["text"]:
                print(f"Font: {span['font']}, Size: {span['size']}, Color: {span['color']}")
                break
doc.close()
```

**Expected result:** Font: Calibri, Size: 12.0, Color: 0 (black)

## Step 3 — Remove and replace section text via content stream manipulation

All sections (Summary, Core Competencies, Technical Proficiencies) use the same approach:
surgically remove the text `q...Q` blocks from the raw content stream, then insert new text.

**How it works:**
- Every text block in the PDF follows the pattern: `q\n.75 0 0 .75 36 <y> cm\n0 0 0 RG 0 0 0 rg\n...BT...ET...\nQ`
- Grey background rectangles use `.949 .949 .949 rg` instead — so they are never touched
- The regex ends at `Q` (not `\nQ\n`) to preserve the trailing `\n`, keeping adjacent blocks valid

**Section cm y-values (used to target specific blocks):**

| Section | cm y-range to remove | Grey stripes? | Insert font |
|---|---|---|---|
| Subheader | `98 < y < 101` (single block at y=99.918) | No | Calibri-Bold |
| Summary | `118 < y < 121` (single block at y=119.449) | No | Calibri Regular |
| Core Competencies | `250 < y < 320` (4 blocks: y≈255, 272, 288, 305) | Yes — 4 stripes | Calibri Italic |
| Technical Proficiencies | `350 < y < 380` (2 blocks: y≈356, 373) | Yes — 2 stripes | Calibri Italic |

```python
import fitz, os, re

calibri_italic  = '/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibrii.ttf'
calibri_regular = '/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibri.ttf'
calibri_bold    = '/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibrib.ttf'
font_it   = fitz.Font(fontfile=calibri_italic)
font_bold = fitz.Font(fontfile=calibri_bold)

doc  = fitz.open(dest)
xref = doc[0].get_contents()[0]
stream = doc.xref_stream(xref).decode('latin-1')

pattern = re.compile(
    r'\nq\n\.75 0 0 \.75 36 ([\d.]+) cm\n0 0 0 RG 0 0 0 rg\n.*?\nQ',
    re.DOTALL
)

# Set y_min / y_max to target the section you want to edit
Y_MIN, Y_MAX = 250, 320   # Core Competencies example — adjust per section

removed = []
def replacer(m):
    y = float(m.group(1))
    if Y_MIN < y < Y_MAX:
        removed.append(round(y, 2))
        return ''
    return m.group(0)

new_stream = pattern.sub(replacer, stream)
doc.update_stream(xref, new_stream.encode('latin-1'))
print(f"Removed blocks at y: {removed}")

# insert_centered: computes x from content area (x=36 to x=576, width=540), inserts at y.
# Use for all centered sections (Subheader, Core Comp, Tech Prof).
# Use insert_text directly for left-aligned sections (Summary: x=36.0, y=144.0).
page = doc[0]

def insert_centered(text, y, font_obj, fontname, fontfile, fontsize=12):
    width = font_obj.text_length(text, fontsize=fontsize)
    x = 36.0 + (540.0 - width) / 2
    page.insert_text(fitz.Point(x, y), text,
        fontname=fontname, fontfile=fontfile,
        fontsize=fontsize, color=(0, 0, 0))

# Example — Subheader (centered, Calibri-Bold 16pt, y=118.683):
insert_centered("Your new subheader text here", 118.683, font_bold, "CalibriB", calibri_bold, fontsize=16)

# Example — Core Competencies (centered, Calibri Italic 12pt, y rows: 269.0, 286.0, 303.0):
insert_centered('• item1  • item2  • item3', 269.0, font_it, "CalibriIt", calibri_italic)
insert_centered('• item4  • item5  • item6', 286.0, font_it, "CalibriIt", calibri_italic)

# Example — Technical Proficiencies (centered, Calibri Italic 12pt, y rows: 371.0, 388.0):
insert_centered('• item1  • item2  • item3', 371.0, font_it, "CalibriIt", calibri_italic)

# Example — Summary (left-aligned, Calibri Regular 12pt, x=36.0, y=144.0):
# page.insert_text(fitz.Point(36.0, 144.0), "Replacement text here",
#     fontname="Calibri", fontfile=calibri_regular, fontsize=12, color=(0,0,0))

doc.save('/tmp/resume_copy_out.pdf', garbage=4, deflate=True)
doc.close()
os.replace('/tmp/resume_copy_out.pdf', dest)
```

## Section font reference

| Section | Font | Size | Style | Color | BBox (approx) |
|---|---|---|---|---|---|
| Subheader | Calibri-Bold | 16pt | Bold | Black | y: 103–119, x: centered (≈119–499) |
| Summary | Calibri Regular | 12pt | Regular | Black | y: 132–203, x: 36–578 |
| Core Competencies | Calibri Italic | 12pt | Italic | Black | y: 257–322, x: 36–580 |
| Technical Proficiencies | Calibri Italic | 12pt | Italic | Black | y: 357–390, x: 36–580 |

### Font files

Do **not** use the Calibri subset embedded in the original PDF — it is a stripped subset and may be missing glyphs.

Use the **full Calibri fonts from Microsoft Excel**:
- Regular: `/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibri.ttf` → `fontname="Calibri"`
- Italic:  `/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibrii.ttf` → `fontname="CalibriIt"`
- Bold:    `/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibrib.ttf` → `fontname="CalibriB"`

### Subheader — known details

- **Original text:** `Senior Data Analyst | eCommerce & Business Intelligence`
- **cm y-range:** `98 < y < 101` (single block at y=99.918)
- **Font:** Calibri-Bold, 16pt, black, **centered**
- **Calibri-Bold ascender at 16pt:** 15.234 pt
- **y_insert:** `103.449 + 15.234 = 118.683` (bbox_top + ascender)

```python
calibri_bold = '/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibrib.ttf'

# Remove subheader block
def replacer(m):
    y = float(m.group(1))
    if 98 < y < 101:
        return ''
    return m.group(0)
stream = stream_pattern.sub(replacer, stream)
doc.update_stream(target_xref, stream.encode('latin-1'))

# Insert new subheader — centered, Calibri-Bold 16pt, y=118.683
font_bold = fitz.Font(fontfile=calibri_bold)
insert_centered("Your new subheader text here", 118.683, font_bold, "CalibriB", calibri_bold, fontsize=16)
```

### Core Competencies — known details
- **Bullet character:** `•`
- **Layout:** Items inline on each row, e.g. `• item1  • item2  • item3`
- **Grey stripe rows (y baselines):** 269, 286, 303, 320
- **Insert y-values:** 269.0, 286.0, 303.0 (use as many rows as needed)

### Technical Proficiencies — known details
- **Grey stripe rows (y baselines):** 371, 388
- **Insert y-values:** 371.0, 388.0

### Combined edit code (all four sections, single pass)

```python
import fitz, os, re

calibri_regular = '/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibri.ttf'
calibri_italic  = '/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibrii.ttf'
calibri_bold    = '/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibrib.ttf'

doc  = fitz.open(dest)
# Always find the stream containing the cm blocks — do not assume index [0]
target_xref = None
for xref in doc[0].get_contents():
    s = doc.xref_stream(xref).decode('latin-1')
    if '.75 0 0 .75 36' in s:
        target_xref = xref; break
stream = doc.xref_stream(target_xref).decode('latin-1')

pattern = re.compile(
    r'\nq\n\.75 0 0 \.75 36 ([\d.]+) cm\n0 0 0 RG 0 0 0 rg\n.*?\nQ',
    re.DOTALL
)
removed = []
def replacer(m):
    y = float(m.group(1))
    if  98 < y < 101:  removed.append(('Subheader', round(y,2))); return ''
    if 118 < y < 121:  removed.append(('Summary',   round(y,2))); return ''
    if 250 < y < 320:  removed.append(('CoreComp',  round(y,2))); return ''
    if 350 < y < 380:  removed.append(('TechProf',  round(y,2))); return ''
    return m.group(0)

new_stream = pattern.sub(replacer, stream)
doc.update_stream(target_xref, new_stream.encode('latin-1'))
print(f"Removed: {removed}")

page = doc[0]
font_it   = fitz.Font(fontfile=calibri_italic)
font_bold = fitz.Font(fontfile=calibri_bold)

def insert_centered(text, y, font_obj, fontname, fontfile, fontsize=12):
    width = font_obj.text_length(text, fontsize=fontsize)
    x = 36.0 + (540.0 - width) / 2   # content area: x=36 to x=576, width=540
    page.insert_text(fitz.Point(x, y), text,
        fontname=fontname, fontfile=fontfile,
        fontsize=fontsize, color=(0, 0, 0))

# Subheader — centered, Calibri-Bold 16pt, y=118.683
insert_centered("Your new subheader text here", 118.683, font_bold, "CalibriB", calibri_bold, fontsize=16)

# Summary — left-aligned, Calibri Regular, x=36.0, y=144.0
page.insert_text(fitz.Point(36.0, 144.0), "Replacement summary text here",
    fontname="Calibri", fontfile=calibri_regular, fontsize=12, color=(0, 0, 0))

# Core Competencies — centered, Calibri Italic 12pt, y rows: 269.0, 286.0, 303.0 (add/remove as needed)
insert_centered('• item1  • item2', 269.0, font_it, "CalibriIt", calibri_italic)
insert_centered('• item3  • item4', 286.0, font_it, "CalibriIt", calibri_italic)
insert_centered('• item5',          303.0, font_it, "CalibriIt", calibri_italic)

# Technical Proficiencies — centered, Calibri Italic 12pt, y rows: 371.0, 388.0
insert_centered('• item1  • item2  • item3', 371.0, font_it, "CalibriIt", calibri_italic)
insert_centered('• item4  • item5',          388.0, font_it, "CalibriIt", calibri_italic)

doc.save('/tmp/resume_copy_out.pdf', garbage=4, deflate=True)
doc.close()
os.replace('/tmp/resume_copy_out.pdf', dest)
```

---

## Updating Job Bullet Points

**Critical rule:** When any bullet changes for a company, **always re-render ALL bullets for that company** from `resume.yaml`. Never edit individual bullets in isolation — doing so mixes the original embedded PDF font with the Excel TTF, causing alignment and spacing inconsistencies. Only render bullets that have non-empty text — skip any blank entries so no empty bullet markers appear in the PDF.

### Why full-section replacement

The original PDF bullets use an embedded Calibri subset with different em-box metrics than the full Excel Calibri TTF. Replacing only some bullets creates a font system mismatch. Replacing all bullets in one pass means every bullet uses the same font/metrics → consistent alignment and spacing throughout.

### How bullets are stored in the PDF

Each bullet (marker + text) is stored as one or more `q…Q` cm blocks in the content stream. The text is in CIDFont encoding (Identity-H) — it cannot be edited in-place. The method is: remove all cm blocks for the company's y-range, then re-render all bullets from scratch.

### Font + rendering details

| Element | Font file | fontname | Size | x |
|---|---|---|---|---|
| Bullet `●` (TrueCar) | `/System/Library/Fonts/Supplemental/Arial.ttf` | `"ArialNew"` | 11pt | 36.0 |
| Bullet `●` (EKN / Pfizer / Tanabe) | same Arial.ttf | `"ArialNew"` | 12pt | 36.0 |
| Bullet text (all companies) | `/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibri.ttf` | `"Calibri"` | 12pt | 54.0 (all companies) |

**Note on hyphens:** Calibri from Excel maps ASCII `-` (U+002D) to the Unicode hyphen `‐` (U+2010). Purely typographic — renders identically.

### Company section constants

```python
CALIBRI_ASCENDER = 9.0
# CALIBRI_INNER_LINE_HT: spacing between lines within a multi-line bullet.
# CALIBRI_BULLET_ADVANCE: y-advance from start of one bullet to start of next (single-line case).
# Both derived from original PDF measurements (run the diagnostic above to verify/recalibrate).
# Excel Calibri TTF bbox height at 12pt = 14.640pt (original PDF's embedded Calibri = 12.000pt).
CALIBRI_INNER_LINE_HT  = 17.3
CALIBRI_BULLET_ADVANCE = 17.3
ARIAL11_ASCENDER =  9.958
ARIAL12_ASCENDER = 10.863

# y_range:       full cm y-range to remove all original bullets for this company
# y_start:       y_marker_fitz_top of the FIRST bullet (anchor for dynamic rendering)
# original_y_end: expected y position after last bullet in the ORIGINAL layout;
#                 used to compute delta for dynamic reflow of sections below
COMPANY_SECTIONS = {
    "truecar": {"page": 0, "y_range": (453, 740), "y_start": 465.8,
                "x_text": 54.0, "arial_size": 11, "wrap_width": 522.0, "original_y_end": 740},
    "ekn":     {"page": 1, "y_range": ( 86, 300), "y_start":  98.1,
                "x_text": 54.0, "arial_size": 12, "wrap_width": 522.0, "original_y_end": 300},
    "pfizer":  {"page": 1, "y_range": (345, 545), "y_start": 357.1,
                "x_text": 54.0, "arial_size": 12, "wrap_width": 522.0, "original_y_end": 545},
    "tanabe":  {"page": 2, "y_range": ( 86, 200), "y_start":  98.1,
                "x_text": 54.0, "arial_size": 12, "wrap_width": 522.0, "original_y_end": 200},
}
```

### Dynamic y-spacing formula

```
y_next_bullet = y_current + (n_lines_in_current_bullet - 1) × CALIBRI_INNER_LINE_HT + CALIBRI_BULLET_ADVANCE
```

- Single-line bullet → 0 × INNER + ADVANCE = **CALIBRI_BULLET_ADVANCE pt**
- Two-line bullet → 1 × INNER + ADVANCE

`CALIBRI_INNER_LINE_HT` controls spacing between lines *within* a multi-line bullet.
`CALIBRI_BULLET_ADVANCE` controls the gap from the start of one bullet to the start of the next (single-line baseline).

**Known spacing issue:** When updated bullet text wraps to a different number of lines than the original (due to Excel Calibri TTF having different metrics than the original embedded subset), spacing with the next bullet appears incorrect. If this occurs, run the diagnostic below to re-measure `CALIBRI_BULLET_ADVANCE` and `CALIBRI_INNER_LINE_HT` from the original PDF.

**Known gap issue:** The space between ● and the first word of updated bullets may appear too small vs. non-updated bullets. If this occurs, increase `x_text` in `COMPANY_SECTIONS` (e.g., try 56.0 or 58.0) and re-measure from the diagnostic below.

**Overflow note:** If bullet content is too long or there are too many bullets, text will overflow into the next section. There is no automatic guard — keep the total content reasonable relative to the original.

### Diagnostic — measure original bullet positions

Run this against the original PDF (not a copy) to get correct `y_start`, `CALIBRI_BULLET_ADVANCE`, `CALIBRI_INNER_LINE_HT`, and `x_text` values:

```python
import fitz

src = '/Users/willmino/Library/Claude/Resume_Github_Project/Will Mino - Resume.pdf'
doc = fitz.open(src)

for page_num in range(3):
    page = doc[page_num]
    spans = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0: continue
        for line in b["lines"]:
            for span in line["spans"]:
                spans.append((span["bbox"][1], span["bbox"][0], span["text"][:60]))
    spans.sort()
    print(f"\n--- Page {page_num} ---")
    for y, x, text in spans:
        print(f"  y={y:.2f}  x={x:.2f}  {text!r}")

doc.close()
# From output: find ● markers and their corresponding text spans.
# CALIBRI_BULLET_ADVANCE = y of second bullet − y of first bullet (single-line bullets)
# CALIBRI_INNER_LINE_HT  = y of second line − y of first line within a wrapped bullet
# x_text = x of the first word after the ● marker
```

### `render_company_section()` function

```python
import fitz, os, re

calibri_regular = '/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibri.ttf'
arial           = '/System/Library/Fonts/Supplemental/Arial.ttf'

stream_pattern = re.compile(
    r'\nq\n\.75 0 0 \.75 36 ([\d.]+) cm\n0 0 0 RG 0 0 0 rg\n.*?\nQ',
    re.DOTALL
)
font_cal = fitz.Font(fontfile=calibri_regular)

def wrap_text(text, max_width=529.0, fontsize=12):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if font_cal.text_length(t, fontsize=fontsize) <= max_width:
            cur = t
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines

def render_company_section(doc, company, bullets):
    """Remove all original bullets for a company and re-render from the provided list.
    bullets: complete list of bullet strings from resume.yaml — any count is supported.
    Returns: actual y position after the last rendered bullet (used for dynamic reflow).
    """
    cfg    = COMPANY_SECTIONS[company]
    page   = doc[cfg["page"]]
    x_text = cfg["x_text"]
    a_asc  = ARIAL11_ASCENDER if cfg["arial_size"] == 11 else ARIAL12_ASCENDER
    y_lo, y_hi = cfg["y_range"]

    # 1. Remove ALL original bullet cm blocks for this company
    target_xref = None
    for xref in page.get_contents():
        s = doc.xref_stream(xref).decode('latin-1')
        if '.75 0 0 .75 36' in s:
            target_xref = xref; break
    stream = doc.xref_stream(target_xref).decode('latin-1')

    removed = []
    def replacer(m):
        y = float(m.group(1))
        if y_lo < y < y_hi:
            removed.append(round(y, 2)); return ''
        return m.group(0)
    stream = stream_pattern.sub(replacer, stream)
    doc.update_stream(target_xref, stream.encode('latin-1'))
    print(f"{company}: removed cm blocks at y={removed}")

    # 2. Re-render all bullets dynamically from y_start — skip blank entries
    y = cfg["y_start"]
    for text in bullets:
        if not text.strip():
            continue
        lines = wrap_text(text, max_width=cfg["wrap_width"])
        # Bullet marker ●
        page.insert_text(fitz.Point(36.0, y + a_asc), "●",
            fontname="ArialNew", fontfile=arial,
            fontsize=cfg["arial_size"], color=(0, 0, 0))
        # Text lines — all lines at same x_text (indent from bullet marker)
        # If gap between ● and text looks too small, increase x_text in COMPANY_SECTIONS.
        for i, line in enumerate(lines):
            page.insert_text(
                fitz.Point(x_text, y + CALIBRI_ASCENDER + i * CALIBRI_INNER_LINE_HT),
                line, fontname="Calibri", fontfile=calibri_regular,
                fontsize=12, color=(0, 0, 0))
        # Advance y to next bullet: inner spacing for extra lines + fixed bullet advance
        y += (len(lines) - 1) * CALIBRI_INNER_LINE_HT + CALIBRI_BULLET_ADVANCE

    return y  # actual y end — compare to cfg["original_y_end"] for reflow delta


def shift_blocks_in_y_range(doc, page_num, y_lo, y_hi, delta):
    """Shift ALL cm blocks (text + grey backgrounds) with y in [y_lo, y_hi] by delta.

    Works by modifying only the y-value in the `.75 0 0 .75 36 <y> cm` transform line,
    leaving all block content intact. Used to reflow section headers and static blocks
    when bullet content on the same page grows or shrinks.

    y_lo / y_hi: inclusive range of cm y-values to shift.
    delta:       positive = shift down (content grew), negative = shift up (content shrank).
    """
    page = doc[page_num]
    target_xref = None
    for xref in page.get_contents():
        s = doc.xref_stream(xref).decode('latin-1')
        if '.75 0 0 .75 36' in s:
            target_xref = xref; break

    stream = doc.xref_stream(target_xref).decode('latin-1')

    cm_pattern = re.compile(r'(\.75 0 0 \.75 36 )([\d.]+)( cm\n)')

    def shifter(m):
        y = float(m.group(2))
        if y_lo <= y <= y_hi:
            return m.group(1) + f"{y + delta:.3f}" + m.group(3)
        return m.group(0)

    new_stream = cm_pattern.sub(shifter, stream)
    doc.update_stream(target_xref, new_stream.encode('latin-1'))
    print(f"page {page_num}: shifted y={y_lo}–{y_hi} by delta={delta:+.1f}")


# Example — render all companies with dynamic reflow:
#
# doc = fitz.open(dest)
#
# render_company_section(doc, "truecar", yaml_data["bullets"]["truecar"])
# # (TrueCar is the last section on page 0 — no reflow needed on page 0)
#
# # Page 1: render EKN, then reflow Pfizer header if EKN height changed
# ekn_y_end = render_company_section(doc, "ekn", yaml_data["bullets"]["ekn"])
# delta_ekn = ekn_y_end - COMPANY_SECTIONS["ekn"]["original_y_end"]
# if delta_ekn != 0:
#     # Shift Pfizer header blocks (company name, dates, title at cm y≈317–345)
#     shift_blocks_in_y_range(doc, 1, y_lo=300, y_hi=345, delta=delta_ekn)
#     COMPANY_SECTIONS["pfizer"]["y_start"] += delta_ekn
# render_company_section(doc, "pfizer", yaml_data["bullets"]["pfizer"])
#
# # Page 2: render Tanabe, then reflow Education/Awards if Tanabe height changed
# tanabe_y_end = render_company_section(doc, "tanabe", yaml_data["bullets"]["tanabe"])
# delta_tanabe = tanabe_y_end - COMPANY_SECTIONS["tanabe"]["original_y_end"]
# if delta_tanabe != 0:
#     # Shift Education (y≈219–307) and Awards (y≈324–353)
#     shift_blocks_in_y_range(doc, 2, y_lo=200, y_hi=400, delta=delta_tanabe)
#
# doc.save('/tmp/resume_copy_out.pdf', garbage=4, deflate=True)
# doc.close()
# os.replace('/tmp/resume_copy_out.pdf', dest)
```

### Combining bullet updates with section updates in one run

When updating Subheader / Summary / Core Comp / Tech Prof AND bullets in the same script:

1. Stream-manipulate page 0 to remove Subheader/Summary/CoreComp/TechProf cm blocks → call `doc.update_stream(...)`.
2. Call `render_company_section(doc, "truecar", ...)` — reads the already-modified page 0 stream and further modifies it.
3. Call `render_company_section(doc, "ekn", ...)` then `render_company_section(doc, "pfizer", ...)` for page 1.
4. Call `render_company_section(doc, "tanabe", ...)` for page 2.
5. Insert Subheader / Summary / Core Comp / Tech Prof text via `page.insert_text(...)`.
6. Save once: `doc.save(..., garbage=4, deflate=True)`.
