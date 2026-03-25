---
name: resume-test-copy
description: Creates a uniquely named test copy of Will Mino's resume PDF. Can edit any section (summary, core competencies, etc.) — removes existing text and writes replacement text in the correct font. Use when asked to make a test copy of the resume or update sections of a copy.
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

**How it works:**
- The PDF content stream stores text and grey background rectangles in **separate `q...Q` blocks**. Text blocks follow the pattern `q\n.75 0 0 .75 36 <y> cm\n0 0 0 RG 0 0 0 rg\n...BT...ET...\nQ`. Grey stripe blocks use `.949 .949 .949 rg` instead.
- We surgically remove only the text-containing `q...Q` blocks by manipulating the raw content stream directly — the grey stripes are untouched.
- **Critical regex detail:** the pattern ends at `Q` (not `\nQ\n`) so the trailing `\n` is preserved, keeping the next block's `\nq\n` delimiter intact.
- After removing the text, insert new content using `insert_textbox` with `align=1` (center).

```python
import fitz, os, re

font_path = '/System/Library/Fonts/Supplemental/Arial Italic.ttf'

doc  = fitz.open(dest)
xref = doc[0].get_contents()[0]
stream = doc.xref_stream(xref).decode('latin-1')

# Step 1 — remove Core Competencies text blocks from the content stream
# Pattern: black-text q/Q blocks (0 0 0 RG) with cm y in range 250–320
pattern = re.compile(
    r'\nq\n\.75 0 0 \.75 36 ([\d.]+) cm\n0 0 0 RG 0 0 0 rg\n.*?\nQ',
    re.DOTALL
)

removed = []
def replacer(m):
    y = float(m.group(1))
    if 250 < y < 320:   # adjust range for other sections
        removed.append(y)
        return ''       # trailing \n stays, preserving \nq\n for next block
    return m.group(0)

new_stream = pattern.sub(replacer, stream)
doc.update_stream(xref, new_stream.encode('latin-1'))
print(f"Removed text at y-values: {removed}")

# Step 2 — insert new centered text on the preserved grey stripes
# Use one insert_textbox per row; adjust items and row count as needed
page = doc[0]
for row_rect, items in [
    (fitz.Rect(36.0, 257.0, 576.0, 273.0), '• item1  • item2  • item3'),
    (fitz.Rect(36.0, 274.0, 576.0, 290.0), '• item4  • item5  • item6'),
]:
    page.insert_textbox(
        row_rect, items,
        fontname="ArialIt", fontfile=font_path,
        fontsize=12, color=(0, 0, 0), align=1
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
import fitz, os, re

font_path = '/System/Library/Fonts/Supplemental/Arial Italic.ttf'

doc  = fitz.open(dest)
xref = doc[0].get_contents()[0]
stream = doc.xref_stream(xref).decode('latin-1')

# Remove Tech Prof text blocks (y=356 and y=373) from content stream
pattern = re.compile(
    r'\nq\n\.75 0 0 \.75 36 ([\d.]+) cm\n0 0 0 RG 0 0 0 rg\n.*?\nQ',
    re.DOTALL
)
removed = []
def replacer(m):
    y = float(m.group(1))
    if 350 < y < 380:
        removed.append(round(y, 2))
        return ''
    return m.group(0)

new_stream = pattern.sub(replacer, stream)
doc.update_stream(xref, new_stream.encode('latin-1'))
print(f"Removed blocks at y: {removed}")

# Insert centered replacement text on preserved grey stripes
page = doc[0]
for row_rect, items in [
    (fitz.Rect(36.0, 359.0, 576.0, 375.0), '• item1  • item2  • item3  • item4'),
    (fitz.Rect(36.0, 376.0, 576.0, 392.0), '• item5  • item6'),
]:
    page.insert_textbox(
        row_rect, items,
        fontname="ArialIt", fontfile=font_path,
        fontsize=12, color=(0, 0, 0), align=1
    )

doc.save('/tmp/resume_copy_out.pdf', garbage=4, deflate=True)
doc.close()
os.replace('/tmp/resume_copy_out.pdf', dest)
```

### Summary — edit code

```python
import fitz, os, re

doc  = fitz.open(dest)
xref = doc[0].get_contents()[0]
stream = doc.xref_stream(xref).decode('latin-1')

# Remove Summary text block (single large block at y=119.449) from content stream
pattern = re.compile(
    r'\nq\n\.75 0 0 \.75 36 ([\d.]+) cm\n0 0 0 RG 0 0 0 rg\n.*?\nQ',
    re.DOTALL
)
removed = []
def replacer(m):
    y = float(m.group(1))
    if 118 < y < 121:
        removed.append(round(y, 3))
        return ''
    return m.group(0)

new_stream = pattern.sub(replacer, stream)
doc.update_stream(xref, new_stream.encode('latin-1'))
print(f"Removed blocks at y: {removed}")

# Extract Calibri regular font from the PDF for inserting new text
page = doc[0]
for f in doc.get_page_fonts(0):
    if 'Calibri' in f[3] and 'Bold' not in f[3] and 'Italic' not in f[3]:
        font_data = doc.extract_font(f[0])[3]
        with open('/tmp/Calibri.ttf', 'wb') as fp:
            fp.write(font_data)
        break

# Insert replacement text — left-aligned, Calibri 12pt, at summary position
page.insert_text(
    fitz.Point(36.0, 144.0),
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
