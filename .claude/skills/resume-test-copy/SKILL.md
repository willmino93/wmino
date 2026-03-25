---
name: resume-test-copy
description: Creates a uniquely named test copy of Will Mino's resume PDF. Can edit any section (subheader, summary, core competencies, technical proficiencies, or job bullet points for TrueCar, EKN Engineering, Pfizer, Tanabe) — removes existing text and writes replacement text in the correct font. Use when asked to make a test copy or update any resume section.
user-invocable: true
---

Follow these exact steps using `/Applications/anaconda3/bin/python3`.

**Important:** Create the unique copy ONCE at the start. All edits overwrite that same file — do not generate new filenames mid-task.

**Critical — single-pass edits:** When editing multiple sections, do ALL `update_stream` removals and ALL `insert_text`/`insert_textbox` insertions in a **single script** before saving. Running separate scripts per section causes `insert_textbox` content to accumulate as extra streams; subsequent `garbage=4` saves do not de-duplicate them, resulting in doubled text in the PDF.

**Stream index note:** After a prior edit session the PDF may have more than one content stream. Always find the stream that contains `.75 0 0 .75 36` cm blocks rather than assuming it is `get_contents()[0]`. Example: iterate `doc[0].get_contents()` and pick the xref whose decoded stream contains that pattern.

## Step 1 — Create the unique copy

Generate a unique filename and copy the source. Store the path in a variable — every subsequent step uses this same path.

```python
import shutil, os
from datetime import datetime

src      = '/Users/willmino/Library/Claude/Resume_Github_Project/Will Mino - Resume.pdf'
dest_dir = '/Users/willmino/Library/Claude/Resume_Github_Project'

timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
dest = os.path.join(dest_dir, f'Will Mino - Resume_copy_{timestamp}.pdf')
shutil.copy(src, dest)
print(f"Created: {os.path.basename(dest)}")
# Store dest — all further steps write to this path
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
| Summary | `118 < y < 121` (single block at y=119.449) | No | Calibri (extracted) |
| Core Competencies | `250 < y < 320` (4 blocks: y≈255, 272, 288, 305) | Yes — 4 stripes | Arial Italic |
| Technical Proficiencies | `350 < y < 380` (2 blocks: y≈356, 373) | Yes — 2 stripes | Arial Italic |

```python
import fitz, os, re

font_path_italic  = '/System/Library/Fonts/Supplemental/Arial Italic.ttf'

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

# Insert new text — use insert_textbox for centered sections (Core Comp / Tech Prof)
# Use insert_text for left-aligned sections (Summary)
page = doc[0]

# Example — Core Competencies (centered, Arial Italic, bullet items per row):
for row_rect, items in [
    (fitz.Rect(36.0, 257.0, 576.0, 273.0), '• item1  • item2  • item3'),
    (fitz.Rect(36.0, 274.0, 576.0, 290.0), '• item4  • item5  • item6'),
]:
    page.insert_textbox(
        row_rect, items,
        fontname="ArialIt", fontfile=font_path_italic,
        fontsize=12, color=(0, 0, 0), align=1
    )

# Example — Summary (left-aligned, Calibri regular, plain text):
# Extract Calibri from the PDF first, then:
# page.insert_text(fitz.Point(36.0, 144.0), "Replacement text here",
#     fontname="Calibri", fontfile="/tmp/Calibri.ttf", fontsize=12, color=(0,0,0))

doc.save('/tmp/resume_copy_out.pdf', garbage=4, deflate=True)
doc.close()
os.replace('/tmp/resume_copy_out.pdf', dest)
```

## Step 4 — Verify

```python
import pdfplumber
with pdfplumber.open(dest) as pdf:
    print(pdf.pages[0].extract_text()[:400])
```

Confirm "Test" appears after the header and before "Industries:".

## Section font reference

| Section | Font | Size | Style | Color | BBox (approx) |
|---|---|---|---|---|---|
| Summary | Calibri Regular | 12pt | Regular | Black | y: 132–203, x: 36–578 |
| Core Competencies | Calibri Italic | 12pt | Italic | Black | y: 257–322, x: 36–580 |
| Technical Proficiencies | Calibri Italic | 12pt | Italic | Black | y: 357–390, x: 36–580 |

### Font files

Do **not** use the Calibri-Italic subset embedded in the original PDF — it is a stripped subset and is missing bullet (`•`) and other glyphs.

Use the **full Calibri fonts from Microsoft Excel**:
- Regular: `/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibri.ttf` → `fontname="Calibri"`
- Italic:  `/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibrii.ttf` → `fontname="CalibriIt"`

**Important:** `insert_textbox` fails silently with these font files. Use `insert_text` instead and manually compute the centered x position using `fitz.Font.text_length()`.

### Centering helper

```python
font_obj = fitz.Font(fontfile='/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibrii.ttf')

def insert_centered(page, text, y, fontsize=12):
    width = font_obj.text_length(text, fontsize=fontsize)
    x = 36.0 + (540.0 - width) / 2   # content area: x=36 to x=576, width=540
    page.insert_text(
        fitz.Point(x, y),
        text,
        fontname="CalibriIt",
        fontfile='/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibrii.ttf',
        fontsize=fontsize, color=(0, 0, 0)
    )
```

### Core Competencies — known details
- **Bullet character:** `•`
- **Layout:** Items inline on each row, e.g. `• item1  • item2  • item3`
- **Grey stripe rows (y baselines):** 269, 286, 303, 320
- **Insert y-values:** 269.0, 286.0, 303.0 (use as many rows as needed)

### Technical Proficiencies — known details
- **Grey stripe rows (y baselines):** 371, 388
- **Insert y-values:** 371.0, 388.0

### Combined edit code (all three sections, single pass)

```python
import fitz, os, re

calibri_regular = '/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibri.ttf'
calibri_italic  = '/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibrii.ttf'

doc  = fitz.open(dest)
xref = doc[0].get_contents()[0]
stream = doc.xref_stream(xref).decode('latin-1')

pattern = re.compile(
    r'\nq\n\.75 0 0 \.75 36 ([\d.]+) cm\n0 0 0 RG 0 0 0 rg\n.*?\nQ',
    re.DOTALL
)
removed = []
def replacer(m):
    y = float(m.group(1))
    if 118 < y < 121:  removed.append(('Summary',  round(y,2))); return ''
    if 250 < y < 320:  removed.append(('CoreComp', round(y,2))); return ''
    if 350 < y < 380:  removed.append(('TechProf', round(y,2))); return ''
    return m.group(0)

new_stream = pattern.sub(replacer, stream)
doc.update_stream(xref, new_stream.encode('latin-1'))
print(f"Removed: {removed}")

page = doc[0]
font_obj = fitz.Font(fontfile=calibri_italic)

def insert_centered(text, y):
    width = font_obj.text_length(text, fontsize=12)
    x = 36.0 + (540.0 - width) / 2
    page.insert_text(fitz.Point(x, y), text,
        fontname="CalibriIt", fontfile=calibri_italic,
        fontsize=12, color=(0, 0, 0))

# Summary — left-aligned, Calibri Regular
page.insert_text(fitz.Point(36.0, 144.0), "Replacement summary text here",
    fontname="Calibri", fontfile=calibri_regular, fontsize=12, color=(0, 0, 0))

# Core Competencies — centered, Calibri Italic (add/remove rows as needed)
insert_centered('• item1  • item2', 269.0)
insert_centered('• item3  • item4', 286.0)
insert_centered('• item5',          303.0)

# Technical Proficiencies — centered, Calibri Italic
insert_centered('• item1  • item2  • item3', 371.0)
insert_centered('• item4  • item5',          388.0)

doc.save('/tmp/resume_copy_out.pdf', garbage=4, deflate=True)
doc.close()
os.replace('/tmp/resume_copy_out.pdf', dest)
```

---

## Updating Job Bullet Points

This method is **distinct** from the Summary / Core Competencies / Technical Proficiencies method.
Use it whenever the user asks to change bullet-point text under any of the four jobs.

### How bullets are stored in the PDF

Each bullet entry (marker + text, including all continuation lines) is stored as **one or more `q…Q` cm blocks** in the content stream. Bullet markers (`●`, U+25CF) and the text span are in the **same block** — they cannot be separated via stream manipulation. The text is in CIDFont encoding (Identity-H), not plain ASCII, so it cannot be substituted in-place.

**Method:** surgically remove the cm block(s) for a bullet, then re-insert both the bullet marker and new text using `insert_text`.

### Font + rendering details

| Element | Font file | fontname | Size | x |
|---|---|---|---|---|
| Bullet `●` (TrueCar) | `/System/Library/Fonts/Supplemental/Arial.ttf` | `"ArialNew"` | 11pt | 36.0 |
| Bullet `●` (EKN / Pfizer / Tanabe) | same Arial.ttf | `"ArialNew"` | 12pt | 36.0 |
| Bullet text (all companies) | `/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibri.ttf` | `"Calibri"` | 12pt | 45.7 (TrueCar) / 46.6 (others) |

**Font metrics (Calibri 12pt):** ascender = 11.426 pt, line height = 14.648 pt
**Font metrics (Arial 11pt):** ascender = 9.958 pt
**Font metrics (Arial 12pt):** ascender = 10.863 pt

**y_insert formula:** `y_insert = y_bbox_top_original + ascender`
(`insert_text` takes a baseline coordinate; span bboxes give the top of the glyph)

**Note on hyphens:** Calibri from Excel maps ASCII `-` (U+002D) to the Unicode hyphen `‐` (U+2010). This is purely typographic — the glyph renders identically.

### Bullet position map (all companies)

All values are derived from the **original** `Will Mino - Resume.pdf` and remain stable as long as the original is not rebuilt.

```python
CALIBRI_ASCENDER = 11.426
CALIBRI_LINE_HT  = 14.648
ARIAL11_ASCENDER =  9.958   # TrueCar
ARIAL12_ASCENDER = 10.863   # EKN, Pfizer, Tanabe

BULLETS = {
    "truecar": {
        "page": 0, "x_text": 45.7, "arial_size": 11,
        # entries: (cm_y_lo, cm_y_hi,  y_marker_fitz_top, y_text_fitz_top)
        "entries": [
            (453, 492,  465.8, 466.8),   # bullet 1
            (492, 521,  495.1, 496.1),   # bullet 2
            (521, 551,  524.4, 525.4),   # bullet 3
            (551, 565,  553.7, 554.6),   # bullet 4
            (565, 594,  568.3, 569.3),   # bullet 5
            (594, 624,  597.6, 598.6),   # bullet 6
            (624, 653,  626.9, 627.9),   # bullet 7
            (653, 682,  656.2, 657.2),   # bullet 8
            (682, 740,  685.5, 686.5),   # bullet 9 (includes trailing empty blocks)
        ],
    },
    "ekn": {
        "page": 1, "x_text": 46.6, "arial_size": 12,
        "entries": [
            (86,  125,   98.1,  99.9),   # bullet 1
            (125, 154,  127.4, 129.2),   # bullet 2
            (154, 184,  156.6, 158.5),   # bullet 3
            (184, 213,  185.9, 187.8),   # bullet 4
            (213, 242,  215.2, 217.1),   # bullet 5
            (242, 272,  244.5, 246.4),   # bullet 6
            (272, 300,  273.8, 275.7),   # bullet 7
        ],
    },
    "pfizer": {
        "page": 1, "x_text": 46.6, "arial_size": 12,
        "entries": [
            (345, 384,  357.1, 358.9),   # bullet 1
            (384, 413,  386.4, 388.2),   # bullet 2
            (413, 443,  415.7, 417.5),   # bullet 3
            (443, 472,  445.0, 446.8),   # bullet 4
            (472, 501,  474.3, 476.1),   # bullet 5
            (501, 545,  503.6, 505.4),   # bullet 6
        ],
    },
    "tanabe": {
        "page": 2, "x_text": 46.6, "arial_size": 12,
        "entries": [
            (86,  125,   98.1,  99.9),   # bullet 1
            (125, 140,  127.4, 129.2),   # bullet 2
            (140, 154,  142.0, 143.9),   # bullet 3
            (154, 200,  156.6, 158.5),   # bullet 4
        ],
    },
}
```

### Bullet update function

```python
import fitz, os, re

calibri = '/Applications/Microsoft Excel.app/Contents/Resources/DFonts/Calibri.ttf'
arial   = '/System/Library/Fonts/Supplemental/Arial.ttf'

# (paste BULLETS dict and constants from above)

stream_pattern = re.compile(
    r'\nq\n\.75 0 0 \.75 36 ([\d.]+) cm\n0 0 0 RG 0 0 0 rg\n.*?\nQ',
    re.DOTALL
)
font_cal = fitz.Font(fontfile=calibri)

def wrap_text(text, max_width=533.0, fontsize=12):
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

def update_bullets(doc, company, new_texts):
    """Replace bullet text for a company.
    new_texts: list of strings, one per bullet (in order).
    Only bullets with a corresponding entry in new_texts are replaced.
    """
    cfg    = BULLETS[company]
    x      = cfg["x_text"]
    a_size = cfg["arial_size"]
    a_asc  = ARIAL11_ASCENDER if a_size == 11 else ARIAL12_ASCENDER
    pg     = doc[cfg["page"]]

    # Find the main content stream
    target_xref = None
    for xref in pg.get_contents():
        s = doc.xref_stream(xref).decode('latin-1')
        if '.75 0 0 .75 36' in s:
            target_xref = xref; break

    stream = doc.xref_stream(target_xref).decode('latin-1')

    for i, (cm_lo, cm_hi, y_marker, y_text) in enumerate(cfg["entries"]):
        if i >= len(new_texts): break

        # Remove cm blocks (removes old bullet marker + text)
        def replacer(m, lo=cm_lo, hi=cm_hi):
            y = float(m.group(1))
            return '' if lo < y < hi else m.group(0)
        stream = stream_pattern.sub(replacer, stream)

        # Re-insert bullet marker ●
        pg.insert_text(
            fitz.Point(36.0, y_marker + a_asc),
            "●",
            fontname="ArialNew", fontfile=arial,
            fontsize=a_size, color=(0, 0, 0)
        )

        # Insert new text (word-wrapped)
        y_ins = y_text + CALIBRI_ASCENDER
        for j, line in enumerate(wrap_text(new_texts[i])):
            pg.insert_text(
                fitz.Point(x, y_ins + j * CALIBRI_LINE_HT),
                line, fontname="Calibri", fontfile=calibri,
                fontsize=12, color=(0, 0, 0)
            )

    doc.update_stream(target_xref, stream.encode('latin-1'))

# Example:
# doc = fitz.open(dest)
# update_bullets(doc, "truecar", ["Bullet 1 text.", "Bullet 2 text.", ...])
# update_bullets(doc, "ekn",     [...])
# update_bullets(doc, "pfizer",  [...])
# update_bullets(doc, "tanabe",  [...])
# doc.save('/tmp/resume_copy_out.pdf', garbage=4, deflate=True)
# doc.close()
# os.replace('/tmp/resume_copy_out.pdf', dest)
```

### Combining bullet updates with section updates in one run

When updating both headers (Summary / Core Comp / Tech Prof) AND bullets in the same script:

1. Stream-manipulate page 0 to remove Summary/CoreComp/TechProf cm blocks → call `doc.update_stream(...)`.
2. Call `update_bullets(doc, "truecar", ...)` — it reads the already-modified page 0 stream and further modifies it.
3. Call `update_bullets(doc, "ekn", ...)` then `update_bullets(doc, "pfizer", ...)` for page 1.
4. Call `update_bullets(doc, "tanabe", ...)` for page 2.
5. Insert Summary / Core Comp / Tech Prof text via `page.insert_text(...)`.
6. Save once: `doc.save(..., garbage=4, deflate=True)`.
