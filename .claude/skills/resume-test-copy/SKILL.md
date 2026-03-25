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

## Font info to store

After running, record the following:
- **Source file:** `Will Mino - Resume.pdf`
- **Summary section font:** Calibri
- **Font size:** 12pt
- **Color:** Black (RGB 0, 0, 0)
- **Replacement text:** Test
