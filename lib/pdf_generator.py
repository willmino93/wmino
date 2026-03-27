"""
lib/pdf_generator.py

Generates a timestamped PDF resume copy from resume.yaml using layout_config.json.

Key design decisions vs. resume_updater_2.py:
  - All positions/constants come from the config dict, not module-level globals.
  - compute_content_heights() and compute_reflow_deltas() are pure functions
    (no PDF I/O) — reflow is fully calculated before any rendering begins.
  - Internal helpers accept config explicitly; no shared mutable state.

Usage:
  from lib.pdf_generator import generate_pdf
  path = generate_pdf(config)
"""

import os
import re
import shutil
from datetime import datetime

import fitz

from lib.yaml_handler import load_yaml


# ── Font registry ─────────────────────────────────────────────────────────────

def _load_fonts(config: dict) -> dict:
    """Return a dict of fitz.Font objects keyed by role name."""
    fp = config["paths"]["fonts"]
    return {
        "regular":    fitz.Font(fontfile=fp["calibri_regular"]),
        "italic":     fitz.Font(fontfile=fp["calibri_italic"]),
        "bold":       fitz.Font(fontfile=fp["calibri_bold"]),
        "bold_italic": fitz.Font(fontfile=fp["calibri_bold_italic"]),
    }


# ── Text utilities ────────────────────────────────────────────────────────────

def wrap_text(text: str, font: fitz.Font, max_width: float, fontsize: float = 12) -> list[str]:
    """Word-wrap text to fit within max_width; returns list of line strings."""
    words = text.split()
    lines, cur = [], ""
    for word in words:
        candidate = (cur + " " + word).strip()
        if font.text_length(candidate, fontsize=fontsize) <= max_width:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _bullet_rendered_height(bullets: list[str], cfg: dict, font: fitz.Font, sp: dict) -> float:
    """
    Compute the total y-advance of rendering a list of bullet strings.
    Returns the final y after the last bullet (i.e. y_start + total advance).
    Pure — no PDF I/O.
    """
    y = cfg["y_start"]
    for text in bullets:
        if not text.strip():
            continue
        lines = wrap_text(text, font, max_width=cfg["wrap_width"])
        y += (len(lines) - 1) * sp["calibri_inner_line_ht"] + sp["calibri_bullet_advance"]
    return y


# ── Pure reflow functions ─────────────────────────────────────────────────────

def compute_content_heights(data: dict, config: dict, fonts: dict) -> dict:
    """
    Compute the rendered height (final y after last item) for each
    variable-length section. Pure — no PDF I/O.

    Returns:
        {
          "summary_lines": int,          # number of wrapped summary lines
          "ekn_y_end": float,            # final y of EKN bullets
          "tanabe_y_end": float,         # final y of Tanabe bullets
        }
    """
    sp   = config["spacing"]
    font = fonts["regular"]

    summary_lines = wrap_text(
        data.get("summary", ""),
        font,
        max_width=config["layout"]["summary"]["max_width"],
        fontsize=config["layout"]["summary"]["fontsize"],
    )

    ekn_y_end = _bullet_rendered_height(
        data["bullets"].get("ekn", []),
        config["company_sections"]["ekn"],
        font, sp,
    )
    tanabe_y_end = _bullet_rendered_height(
        data["bullets"].get("tanabe", []),
        config["company_sections"]["tanabe"],
        font, sp,
    )

    return {
        "summary_lines": len(summary_lines),
        "ekn_y_end":     ekn_y_end,
        "tanabe_y_end":  tanabe_y_end,
    }


def compute_reflow_deltas(content_heights: dict, original_summary_lines: int, config: dict) -> dict:
    """
    Given actual content heights vs. original template values, return y-shift
    deltas per dependent section. Pure — no PDF I/O.

    Returns:
        {
          "summary": float,    # how much summary grew/shrank in pts
          "ekn": float,        # how much EKN section grew/shrank in pts
          "tanabe": float,     # how much Tanabe section grew/shrank in pts
        }
    """
    sp = config["spacing"]

    summary_delta = (
        (content_heights["summary_lines"] - original_summary_lines)
        * sp["calibri_inner_line_ht"]
    )

    ekn_delta    = content_heights["ekn_y_end"]    - config["company_sections"]["ekn"]["original_y_end"]
    tanabe_delta = content_heights["tanabe_y_end"] - config["company_sections"]["tanabe"]["original_y_end"]

    return {
        "summary": summary_delta,
        "ekn":     ekn_delta,
        "tanabe":  tanabe_delta,
    }


# ── Low-level PDF helpers ─────────────────────────────────────────────────────

def _get_target_xref(doc: fitz.Document, page_num: int) -> int:
    page = doc[page_num]
    for xref in page.get_contents():
        s = doc.xref_stream(xref).decode("latin-1")
        if ".75 0 0 .75 36" in s:
            return xref
    raise RuntimeError(f"Could not find cm-block stream on page {page_num}")


def _remove_cm_blocks(doc: fitz.Document, page_num: int, y_min: float, y_max: float, config: dict) -> list:
    """Remove cm-block graphics in the y range and return the removed y-values."""
    pattern = re.compile(config["stream_pattern"], re.DOTALL)
    xref    = _get_target_xref(doc, page_num)
    stream  = doc.xref_stream(xref).decode("latin-1")
    removed = []

    def replacer(m):
        y = float(m.group(1))
        if y_min < y < y_max:
            removed.append(round(y, 2))
            return ""
        return m.group(0)

    new_stream = pattern.sub(replacer, stream)
    doc.update_stream(xref, new_stream.encode("latin-1"))
    return removed


def _shift_blocks_in_y_range(
    doc: fitz.Document, page_num: int, y_lo: float, y_hi: float, delta: float, config: dict
) -> None:
    """Shift cm-block graphics within y_lo..y_hi by delta pts."""
    xref       = _get_target_xref(doc, page_num)
    stream     = doc.xref_stream(xref).decode("latin-1")
    cm_pattern = re.compile(r"(\.75 0 0 \.75 36 )([\d.]+)( cm\n)")

    def shifter(m):
        y = float(m.group(2))
        if y_lo <= y <= y_hi:
            return m.group(1) + f"{y + delta:.3f}" + m.group(3)
        return m.group(0)

    new_stream = cm_pattern.sub(shifter, stream)
    doc.update_stream(xref, new_stream.encode("latin-1"))
    print(f"  page {page_num}: shifted y={y_lo}–{y_hi} by delta={delta:+.2f}")


def _insert_centered(
    page: fitz.Page,
    text: str,
    y: float,
    font_obj: fitz.Font,
    fontname: str,
    fontfile: str,
    fontsize: float = 12,
) -> None:
    width = font_obj.text_length(text, fontsize=fontsize)
    x = 36.0 + (540.0 - width) / 2
    page.insert_text(
        fitz.Point(x, y), text,
        fontname=fontname, fontfile=fontfile,
        fontsize=fontsize, color=(0, 0, 0),
    )


# ── Section renderers ─────────────────────────────────────────────────────────

def _render_company_section(
    doc: fitz.Document,
    company: str,
    bullets: list[str],
    fonts: dict,
    config: dict,
) -> float:
    """
    Clear and re-render a company bullet section.
    Returns the final y position (used to compute downstream reflow).
    """
    sp      = config["spacing"]
    cfg     = config["company_sections"][company]
    fp      = config["paths"]["fonts"]
    page    = doc[cfg["page"]]
    x_text  = cfg["x_text"]
    a_asc   = sp["arial11_ascender"] if cfg["arial_size"] == 11 else sp["arial12_ascender"]
    y_lo, y_hi = cfg["y_range"]
    font    = fonts["regular"]

    removed = _remove_cm_blocks(doc, cfg["page"], y_lo, y_hi, config)
    print(f"  {company}: removed cm blocks at y={removed}")

    y = cfg["y_start"]
    for text in bullets:
        if not text.strip():
            continue
        lines = wrap_text(text, font, max_width=cfg["wrap_width"])
        page.insert_text(
            fitz.Point(36.0, y + a_asc), "●",
            fontname="ArialNew", fontfile=fp["arial"],
            fontsize=cfg["arial_size"], color=(0, 0, 0),
        )
        for i, line in enumerate(lines):
            page.insert_text(
                fitz.Point(x_text, y + sp["calibri_ascender"] + i * sp["calibri_inner_line_ht"]),
                line,
                fontname="Calibri", fontfile=fp["calibri_regular"],
                fontsize=12, color=(0, 0, 0),
            )
        y += (len(lines) - 1) * sp["calibri_inner_line_ht"] + sp["calibri_bullet_advance"]

    return y


def _render_header_sections(
    doc: fitz.Document,
    data: dict,
    summary_lines: list[str],
    industries_text: str,
    industries_new_y: float,
    cc_delta: float,
    deltas: dict,
    fonts: dict,
    config: dict,
    cc_bars: list | None = None,
    tp_bars: list | None = None,
) -> None:
    """Render subheader, summary, Industries line, Core Competencies, and Tech Proficiencies."""
    sp   = config["spacing"]
    lay  = config["layout"]
    fp   = config["paths"]["fonts"]
    page = doc[0]

    summary_delta = deltas["summary"]

    # Subheader
    _insert_centered(
        page,
        data["subheader"],
        lay["subheader"]["y"],
        fonts["bold"],
        "CalibriB", fp["calibri_bold"],
        fontsize=lay["subheader"]["fontsize"],
    )
    print(f"  Subheader: {data['subheader']!r}")

    # Summary
    y_first = lay["summary"]["y_first_line"]
    for i, line in enumerate(summary_lines):
        page.insert_text(
            fitz.Point(lay["summary"]["x"], y_first + i * sp["calibri_inner_line_ht"]),
            line,
            fontname="Calibri", fontfile=fp["calibri_regular"],
            fontsize=lay["summary"]["fontsize"], color=(0, 0, 0),
        )
    print(f"  Summary: {len(summary_lines)} line(s)")

    # Industries line
    page.insert_text(
        fitz.Point(lay["industries"]["x"], industries_new_y),
        industries_text,
        fontname="CalibriBI", fontfile=fp["calibri_bold_italic"],
        fontsize=lay["industries"]["fontsize"], color=(0, 0, 0),
    )
    print(f"  Industries at y={industries_new_y:.1f}")

    # Core Competencies label
    cc_cfg      = lay["core_competencies"]
    cc_label_y  = industries_new_y + cc_cfg["label_lines_below_industries"] * sp["calibri_inner_line_ht"]
    w_core      = fonts["bold_italic"].text_length("Core ",        fontsize=cc_cfg["label_fontsize"])
    w_comp      = fonts["bold"].text_length("Competencies",        fontsize=cc_cfg["label_fontsize"])
    page.insert_text(fitz.Point(36.0,               cc_label_y), "Core ",
                     fontname="CalibriBI", fontfile=fp["calibri_bold_italic"],
                     fontsize=cc_cfg["label_fontsize"], color=(0, 0, 0))
    page.insert_text(fitz.Point(36.0 + w_core,      cc_label_y), "Competencies",
                     fontname="CalibriB",  fontfile=fp["calibri_bold"],
                     fontsize=cc_cfg["label_fontsize"], color=(0, 0, 0))
    page.insert_text(fitz.Point(36.0 + w_core + w_comp, cc_label_y), ":",
                     fontname="CalibriBI", fontfile=fp["calibri_bold_italic"],
                     fontsize=cc_cfg["label_fontsize"], color=(0, 0, 0))

    # Core Competencies rows — vertically centered in each grey bar
    for k, row in enumerate(data.get("core_competencies", [])[:cc_cfg["max_rows"]]):
        row_text = "  ".join(f"• {item}" for item in row)
        if cc_bars and k < len(cc_bars):
            bar_center = (cc_bars[k].y0 + cc_bars[k].y1) / 2
            row_y = bar_center + sp["calibri_ascender"] / 2
        else:
            row_y = cc_label_y + (k + 1) * sp["calibri_inner_line_ht"]
        _insert_centered(page, row_text, row_y, fonts["italic"],
                         "CalibriIt", fp["calibri_italic"], fontsize=cc_cfg["fontsize"])
        print(f"  Core Comp row {k+1}: {row_text[:60]!r}")

    # Technical Proficiencies label
    tp_cfg     = lay["technical_proficiencies"]
    tp_label_y = tp_cfg["label_y_base"] + summary_delta
    page.insert_text(
        fitz.Point(36.0, tp_label_y),
        "Technical Proficiencies:",
        fontname="CalibriB", fontfile=fp["calibri_bold"],
        fontsize=tp_cfg["label_fontsize"], color=(0, 0, 0),
    )

    # Technical Proficiencies rows
    tp_row_y_base = tp_cfg["row_y_base"]
    for k, row in enumerate(data.get("technical_proficiencies", [])[:tp_cfg["max_rows"]]):
        row_text = "  ".join(f"• {item}" for item in row)
        row_y    = tp_row_y_base[k] + summary_delta
        _insert_centered(page, row_text, row_y, fonts["italic"],
                         "CalibriIt", fp["calibri_italic"], fontsize=tp_cfg["fontsize"])
        print(f"  Tech Prof row {k+1}: {row_text[:60]!r}")

    print("  Re-inserted: Core Competencies label + rows")
    print("  Re-inserted: Technical Proficiencies label + rows")


# ── Industries detection ──────────────────────────────────────────────────────

def _read_industries_from_pdf(src_pdf: str) -> tuple[str, float]:
    """Read the Industries line text and its original y from the source PDF."""
    src = fitz.open(src_pdf)
    industries_text = ""
    industries_orig_y = None

    for block in src[0].get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                if "Industries" in span["text"] and industries_orig_y is None:
                    industries_orig_y = span["origin"][1]
                if industries_orig_y is not None and abs(span["origin"][1] - industries_orig_y) < 3:
                    industries_text += span["text"]

    src.close()
    industries_text = industries_text.strip()

    if industries_orig_y is None:
        raise RuntimeError("Could not find Industries line in source PDF")

    return industries_text, industries_orig_y


# ── Main orchestrator ─────────────────────────────────────────────────────────

def generate_pdf(config: dict) -> str:
    """
    Orchestrate: load YAML → compute reflow → open PDF → clear → render → save.

    Steps:
      1. Load current resume.yaml and resume_original.yaml
      2. Load fonts
      3. Compute content heights (pure)
      4. Compute reflow deltas (pure)
      5. Open a timestamped copy of the source PDF
      6. Clear old content (cm-blocks + redactions)
      7. Shift cm-blocks for reflow
      8. Redraw grey bars at shifted positions
      9. Render company bullet sections
     10. Render header sections (subheader, summary, Industries, CC, TP)
     11. Save

    Returns:
        Absolute path to the saved PDF copy.
    """
    base_dir    = config["paths"]["base_dir"]
    src_pdf     = os.path.join(base_dir, config["paths"]["src_pdf"])
    yaml_path   = os.path.join(base_dir, config["paths"]["yaml_working"])
    orig_path   = os.path.join(base_dir, config["paths"]["yaml_original"])
    sp          = config["spacing"]
    lay         = config["layout"]
    reflow_cfg  = config["reflow"]

    # ── 1. Load YAML ──────────────────────────────────────────────────────────
    data      = load_yaml(yaml_path)
    orig_data = load_yaml(orig_path)

    # ── 2. Load fonts ─────────────────────────────────────────────────────────
    fonts = _load_fonts(config)

    # ── 3. Compute content heights (pure) ─────────────────────────────────────
    orig_summary_lines_count = len(wrap_text(
        orig_data.get("summary", ""),
        fonts["regular"],
        max_width=lay["summary"]["max_width"],
        fontsize=lay["summary"]["fontsize"],
    ))
    content_heights = compute_content_heights(data, config, fonts)

    # ── 4. Compute reflow deltas (pure) ───────────────────────────────────────
    deltas = compute_reflow_deltas(content_heights, orig_summary_lines_count, config)
    summary_delta = deltas["summary"]
    ekn_delta     = deltas["ekn"]
    tanabe_delta  = deltas["tanabe"]

    # ── 5. Read Industries from source PDF ────────────────────────────────────
    industries_text, industries_orig_y = _read_industries_from_pdf(src_pdf)

    # Compute where Industries should land given the new summary length
    y_first_summary = lay["summary"]["y_first_line"]
    industries_new_y = (
        y_first_summary
        + (content_heights["summary_lines"] - 1) * sp["calibri_inner_line_ht"]
        + sp["summary_to_industries_gap"]
    )
    cc_delta = industries_new_y - industries_orig_y

    if summary_delta != 0:
        print(f"  Summary delta={summary_delta:+.2f} — reflowing page 0 content...")

    # ── 6. Create timestamped output files ────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest      = os.path.join(base_dir, f"Will Mino - Resume_copy_{timestamp}.pdf")

    shutil.copy(src_pdf, dest)
    print(f"\nCreated: {os.path.basename(dest)}")

    doc = fitz.open(dest)

    # Mutate y_start for TrueCar in-place (summary reflow shifts it on page 0)
    # We use a local copy so config stays unmodified between calls.
    truecar_y_start = config["company_sections"]["truecar"]["y_start"] + summary_delta
    pfizer_y_start  = config["company_sections"]["pfizer"]["y_start"]  + ekn_delta

    # ── 7. Clear cm-blocks ────────────────────────────────────────────────────
    print("\nRemoving header section cm blocks (page 0)...")
    removed_sub = _remove_cm_blocks(doc, 0, **lay["subheader"]["cm_remove"],    config=config)
    removed_sum = _remove_cm_blocks(doc, 0, **lay["summary"]["cm_remove"],      config=config)
    removed_cc  = _remove_cm_blocks(doc, 0, **lay["core_competencies"]["cm_remove"], config=config)
    removed_tp  = _remove_cm_blocks(doc, 0, **lay["technical_proficiencies"]["cm_remove"], config=config)
    _remove_cm_blocks(doc, 0, **lay["industries"]["cm_remove"], config=config)

    truecar_yr = config["company_sections"]["truecar"]["y_range"]
    _remove_cm_blocks(doc, 0, y_min=truecar_yr[0], y_max=truecar_yr[1], config=config)

    print(f"  Subheader cm blocks removed: {removed_sub}")
    print(f"  Summary cm blocks removed:   {removed_sum}")
    print(f"  Core Comp cm blocks removed: {removed_cc}")
    print(f"  Tech Prof cm blocks removed: {removed_tp}")

    # ── 8. Capture grey bars, apply redactions, restore bars at shifted y ─────
    p0        = doc[0]
    grey_bars = [
        {"rect": p["rect"], "fill": p["fill"]}
        for p in p0.get_drawings()
        if p.get("fill") and lay["grey_bars"]["y_lo"] < p["rect"].y0 < lay["grey_bars"]["y_hi"]
    ]

    orig_summary_bottom = (
        y_first_summary
        + (orig_summary_lines_count - 1) * sp["calibri_inner_line_ht"]
        + 8
    )
    p0.add_redact_annot(fitz.Rect(0, lay["summary"]["redact_y_top"], p0.rect.width, orig_summary_bottom))
    p0.add_redact_annot(fitz.Rect(0, industries_orig_y - 8, p0.rect.width, industries_orig_y + 16))
    p0.add_redact_annot(fitz.Rect(*lay["core_competencies"]["redact_rect"]))
    p0.add_redact_annot(fitz.Rect(*lay["technical_proficiencies"]["redact_rect"]))
    p0.apply_redactions()

    # Shift middle-of-page cm-blocks (between TP and TrueCar) if summary changed
    if summary_delta != 0:
        y_lo, y_hi = reflow_cfg["summary_page0_shift_range"]
        _shift_blocks_in_y_range(doc, 0, y_lo, y_hi, summary_delta, config)

    # Restore grey bars at shifted positions; collect shifted rects for centering text
    cc_bars: list = []
    tp_bars: list = []
    cc_threshold = lay["core_competencies"]["grey_bar_y_threshold"]
    for bar in grey_bars:
        r = bar["rect"]
        d = cc_delta if r.y0 < cc_threshold else summary_delta
        shifted = fitz.Rect(r.x0, r.y0 + d, r.x1, r.y1 + d)
        p0.draw_rect(shifted, color=None, fill=bar["fill"])
        if r.y0 < cc_threshold:
            cc_bars.append(shifted)
        else:
            tp_bars.append(shifted)
    cc_bars.sort(key=lambda r: r.y0)
    tp_bars.sort(key=lambda r: r.y0)

    # ── 9. Render company bullet sections ─────────────────────────────────────
    print("\nRendering company bullet sections...")

    # TrueCar (page 0) — y_start shifted by summary_delta
    truecar_cfg = dict(config["company_sections"]["truecar"])
    truecar_cfg["y_start"] = truecar_y_start
    config_with_truecar = dict(config)
    config_with_truecar["company_sections"] = dict(config["company_sections"])
    config_with_truecar["company_sections"]["truecar"] = truecar_cfg
    _render_company_section(doc, "truecar", data["bullets"].get("truecar", []), fonts, config_with_truecar)

    # EKN (page 1)
    _render_company_section(doc, "ekn", data["bullets"].get("ekn", []), fonts, config)

    # Shift Pfizer header area if EKN changed height
    if ekn_delta != 0:
        print(f"  EKN delta={ekn_delta:+.2f} — reflowing Pfizer header...")
        y_lo, y_hi = reflow_cfg["ekn_page1_shift_range"]
        _shift_blocks_in_y_range(doc, 1, y_lo, y_hi, ekn_delta, config)

    # Pfizer (page 1) — y_start shifted by ekn_delta
    pfizer_cfg = dict(config["company_sections"]["pfizer"])
    pfizer_cfg["y_start"] = pfizer_y_start
    config_with_pfizer = dict(config)
    config_with_pfizer["company_sections"] = dict(config["company_sections"])
    config_with_pfizer["company_sections"]["pfizer"] = pfizer_cfg
    _render_company_section(doc, "pfizer", data["bullets"].get("pfizer", []), fonts, config_with_pfizer)

    # Tanabe (page 2)
    _render_company_section(doc, "tanabe", data["bullets"].get("tanabe", []), fonts, config)

    # Shift Education/Awards if Tanabe changed height
    if tanabe_delta != 0:
        print(f"  Tanabe delta={tanabe_delta:+.2f} — reflowing Education/Awards...")
        y_lo, y_hi = reflow_cfg["tanabe_page2_shift_range"]
        _shift_blocks_in_y_range(doc, 2, y_lo, y_hi, tanabe_delta, config)

    # ── 10. Render header sections ────────────────────────────────────────────
    print("\nInserting header section text...")
    summary_lines = wrap_text(
        data.get("summary", ""),
        fonts["regular"],
        max_width=lay["summary"]["max_width"],
        fontsize=lay["summary"]["fontsize"],
    )
    _render_header_sections(
        doc, data, summary_lines,
        industries_text, industries_new_y, cc_delta,
        deltas, fonts, config,
        cc_bars=cc_bars, tp_bars=tp_bars,
    )

    # ── 11. Save ──────────────────────────────────────────────────────────────
    tmp = "/tmp/resume_copy_out.pdf"
    doc.save(tmp, garbage=4, deflate=True)
    doc.close()
    os.replace(tmp, dest)
    print(f"\nSaved: {dest}")

    return dest
