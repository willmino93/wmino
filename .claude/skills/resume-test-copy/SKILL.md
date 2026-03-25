---
name: resume-test-copy
description: Creates a uniquely named test copy of Will Mino's resume PDF. Can edit any section (summary, core competencies, etc.) — removes existing text and writes replacement text in the correct font. Use when asked to make a test copy of the resume or update sections of a copy.
user-invocable: true
---

Follow these exact steps using `/Applications/anaconda3/bin/python3`.

**Important:** Create the unique copy ONCE at the start. All edits overwrite that same file — do not generate new filenames mid-task.

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

## Step 3 — Remove summary text and insert "Test" (overwrites the copy)

```python
import fitz, os

# Extract Calibri font from the copy to a temp file
doc = fitz.open(dest)
for f in doc.get_page_fonts(0):
    if 'Calibri' in f[3] and 'Bold' not in f[3] and 'Italic' not in f[3]:
        font_data = doc.extract_font(f[0])[3]
        with open('/tmp/Calibri.ttf', 'wb') as fp:
            fp.write(font_data)
        break

page = doc[0]

# Find summary block
summary_rect = None
for b in page.get_text("blocks"):
    if 'Results-driven' in b[4]:
        summary_rect = fitz.Rect(b[0], b[1], b[2], b[3])
        break

if summary_rect:
    page.add_redact_annot(summary_rect, fill=(1, 1, 1))
    page.apply_redactions()

    page.insert_text(
        fitz.Point(summary_rect.x0, summary_rect.y0 + 12),
        "Test",
        fontname="Calibri",
        fontfile="/tmp/Calibri.ttf",
        fontsize=12,
        color=(0, 0, 0)
    )

# Overwrite the same copy — no new file
doc.save('/tmp/resume_copy_out.pdf', garbage=4, deflate=True)
doc.close()
os.replace('/tmp/resume_copy_out.pdf', dest)
print(f"Updated: {os.path.basename(dest)}")
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
| Summary | Calibri | 12pt | Regular | Black | y: 132–203, x: 36–578 |
| Core Competencies | Calibri-Italic | 12pt | Italic | Black | y: 257–322, x: 36–580 |

### Core Competencies — known details
- **Bullet character:** `•`
- **Layout:** Items inline on each row separated by spaces, e.g. `• item1  • item2  • item3`
- **Rows span:** `fitz.Rect(36.0, 257.0, 580.0, 322.0)` covers all 4 competency rows
- **Insert point:** `fitz.Point(36.0, 269.0)`
- **Font note:** The Calibri-Italic subset embedded in the PDF is missing number glyphs and the bullet character. Use Arial Italic from the system instead:
  - Font file: `/System/Library/Fonts/Supplemental/Arial Italic.ttf`
  - fontname: `"ArialIt"`

### Core Competencies — edit code

**Important rules:**
- Use `add_redact_annot` + `apply_redactions(graphics=fitz.PDF_REDACT_LINE_ART_NONE)` to remove text only — this preserves the original grey stripe backgrounds automatically.
- Do NOT use `draw_rect` with white fill — it covers the grey stripes.
- Use `insert_textbox` with `align=1` (center) to match the original centered layout.
- Grey stripes cover y=254–325. Each stripe row is ~18pt tall. Place text in the first stripe rect (y=257–273).

```python
import fitz, os

font_path = '/System/Library/Fonts/Supplemental/Arial Italic.ttf'

doc  = fitz.open(dest)
page = doc[0]

# Step 1 — remove text only, preserve grey stripe backgrounds
page.add_redact_annot(fitz.Rect(36.0, 254.0, 580.0, 325.0), fill=(1, 1, 1))
page.apply_redactions(graphics=fitz.PDF_REDACT_LINE_ART_NONE)

# Step 2 — insert centered replacement text (adjust items as needed)
# Use one insert_textbox per row if you need multiple lines
page.insert_textbox(
    fitz.Rect(36.0, 257.0, 576.0, 273.0),
    '• item1  • item2  • item3  • item4',
    fontname="ArialIt",
    fontfile=font_path,
    fontsize=12,
    color=(0, 0, 0),
    align=1  # 1 = center
)

doc.save('/tmp/resume_copy_out.pdf', garbage=4, deflate=True)
doc.close()
os.replace('/tmp/resume_copy_out.pdf', dest)
```

### Technical Proficiencies — known details
- **Font:** Arial Italic 12pt (same Calibri-Italic subset glyph issue applies)
- **Grey stripes:** 2 rows — y=357–375 and y=374–392
- **Redact rect:** `fitz.Rect(36.0, 356.0, 580.0, 393.0)`
- **Insert rect (row 1):** `fitz.Rect(36.0, 359.0, 576.0, 375.0)`

### Technical Proficiencies — edit code

```python
import fitz, os

font_path = '/System/Library/Fonts/Supplemental/Arial Italic.ttf'

doc  = fitz.open(dest)
page = doc[0]

# Step 1 — remove text only, preserve grey stripe backgrounds
page.add_redact_annot(fitz.Rect(36.0, 356.0, 580.0, 393.0), fill=(1, 1, 1))
page.apply_redactions(graphics=fitz.PDF_REDACT_LINE_ART_NONE)

# Step 2 — insert centered replacement text
page.insert_textbox(
    fitz.Rect(36.0, 359.0, 576.0, 375.0),
    '• item1  • item2  • item3  • item4',
    fontname="ArialIt",
    fontfile=font_path,
    fontsize=12,
    color=(0, 0, 0),
    align=1  # 1 = center
)

doc.save('/tmp/resume_copy_out.pdf', garbage=4, deflate=True)
doc.close()
os.replace('/tmp/resume_copy_out.pdf', dest)
```

### Summary — edit code

```python
import fitz, os

# Extract Calibri regular from the PDF
doc = fitz.open(dest)
for f in doc.get_page_fonts(0):
    if 'Calibri' in f[3] and 'Bold' not in f[3] and 'Italic' not in f[3]:
        font_data = doc.extract_font(f[0])[3]
        with open('/tmp/Calibri.ttf', 'wb') as fp:
            fp.write(font_data)
        break

page = doc[0]

# Find and redact summary block
summary_rect = None
for b in page.get_text("blocks"):
    if 'Results-driven' in b[4]:
        summary_rect = fitz.Rect(b[0], b[1], b[2], b[3])
        break

if summary_rect:
    page.add_redact_annot(summary_rect, fill=(1, 1, 1))
    page.apply_redactions()

    page.insert_text(
        fitz.Point(summary_rect.x0, summary_rect.y0 + 12),
        "Replacement text here",
        fontname="Calibri",
        fontfile="/tmp/Calibri.ttf",
        fontsize=12,
        color=(0, 0, 0)
    )

doc.save('/tmp/resume_copy_out.pdf', garbage=4, deflate=True)
doc.close()
os.replace('/tmp/resume_copy_out.pdf', dest)
```
