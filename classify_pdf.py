import json
import os
import re
from collections import Counter

import fitz
import pdfplumber
from PIL import Image, ImageDraw

PDF_PATH = "2603.25723v11.pdf"
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

CATEGORY_COLORS = {
    "title":          (220,  50,  50),
    "authors":        (230, 100,  30),
    "affiliation":    (240, 150,  60),
    "section_header": (200,  80,   0),
    "abstract":       (50,  100, 200),
    "paragraph":      (50,  120, 220),
    "figure":         (30,  160,  70),
    "figure_caption": (80,  200, 120),
    "table":          (140,  40, 180),
    "table_row":      (160,  80, 200),
    "table_caption":  (180, 110, 220),
    "equation":       (180, 160,   0),
    "footnote":       (100, 140, 140),
    "footer":         (120, 120, 120),
    "page_number":    (150, 150, 150),
    "reference":      (0,   160, 180),
    "list_item":      (0,   130, 170),
    "watermark":      (180, 180, 180),
    "other":          (100, 100, 100),
}


def get_block_text(block):
    if block["type"] != 0:
        return ""
    return " ".join(
        span["text"]
        for line in block.get("lines", [])
        for span in line.get("spans", [])
    ).strip()


def get_block_spans(block):
    if block["type"] != 0:
        return []
    return [
        span
        for line in block.get("lines", [])
        for span in line.get("spans", [])
    ]


def is_watermark_block(block):
    """Rotated/narrow tall block (e.g. arXiv sidebar stamp)."""
    x0, y0, x1, y1 = block["bbox"]
    return (x1 - x0) < 30 and (y1 - y0) > 100


def compute_font_sizes(blocks):
    """
    Return (title_size, body_size) excluding watermark-like blocks.
    title_size = max span size among real content blocks.
    body_size  = most common (mode) span size.
    """
    content_spans = [
        span
        for b in blocks
        if b["type"] == 0 and not is_watermark_block(b)
        for line in b["lines"]
        for span in line["spans"]
    ]
    if not content_spans:
        return 12.0, 10.0
    sizes = [s["size"] for s in content_spans]
    title_size = max(sizes)
    size_counts = Counter(round(s, 1) for s in sizes)
    body_size = size_counts.most_common(1)[0][0]
    return title_size, body_size


def classify_block(
    block, page_height, page_width, page_num,
    table_rects, title_size, body_size,
):
    if block["type"] == 1:
        return "figure"

    text = get_block_text(block)
    if not text:
        return "other"

    if is_watermark_block(block):
        return "watermark"

    spans = get_block_spans(block)
    sizes = [s["size"] for s in spans]
    flags_list = [s["flags"] for s in spans]
    avg_size = sum(sizes) / len(sizes) if sizes else 0
    is_bold = any(f & 16 for f in flags_list)

    x0, y0, x1, y1 = block["bbox"]
    rel_y0 = y0 / page_height
    rel_y1 = y1 / page_height
    block_w = x1 - x0

    # Inside a detected table → table_row
    in_table = any(
        tx0 <= x0 + 2
        and ty0 <= y0 + 2
        and tx1 >= x1 - 2
        and ty1 >= y1 - 2
        for tx0, ty0, tx1, ty1 in table_rects
    )
    if in_table:
        return "table_row"

    # Page number: digit-only near bottom, small font
    if (
        rel_y1 > 0.90
        and len(text) <= 6
        and text.strip().lstrip("-").isdigit()
    ):
        return "page_number"

    # Footnote: small text near bottom, often starts with * or †
    if rel_y0 > 0.82 and avg_size < body_size * 0.85:
        return "footnote"

    # Footer: small at very bottom
    if rel_y1 > 0.92 and avg_size < body_size * 0.85:
        return "footer"

    # Named section labels — checked first so they're never misclassified
    _SECTION_NAMES = {
        "abstract", "introduction", "conclusion", "conclusions",
        "references", "acknowledgments", "acknowledgements",
        "related work", "background", "methodology", "experiments",
        "results", "discussion", "appendix",
    }
    if text.strip().lower() in _SECTION_NAMES:
        return "section_header"

    # Numbered section headers (e.g. "1 Introduction", "2.1 Method")
    if is_bold and len(text) < 120 and re.match(r"^\d+(\.\d+)*[\s.]", text):
        return "section_header"

    # --- Academic paper header region (top ~35% of first page) ---
    if page_num == 0 and rel_y0 < 0.35:
        # Title: largest-font bold block near top
        if is_bold and avg_size >= title_size * 0.85:
            return "title"

        # Affiliation: institution/university keywords
        aff_keywords = (
            "university", "institute", "school", "college",
            "laboratory", "department", "tsinghua", "harbin",
            "peking", "mit", "stanford", "carnegie", "berkeley",
        )
        if any(k in text.lower() for k in aff_keywords):
            return "affiliation"

        # Affiliation: email or domain
        if "@" in text or ".edu" in text or ".ac." in text:
            return "affiliation"

        # Authors: bold, smaller than title
        if is_bold and avg_size < title_size * 0.85:
            return "authors"

    # Figure caption
    if re.match(r"^fig(ure)?\.?\s*\d", text.lower()):
        return "figure_caption"

    # Table caption
    if re.match(r"^table\s*\d", text.lower()):
        return "table_caption"

    # Reference entry: [N] Author, Title...
    if re.match(r"^\[\d+\]", text.strip()):
        return "reference"

    # List item
    if (
        re.match(r"^[•\-–—·*]\s", text.strip())
        or re.match(r"^\d+\.\s", text.strip())
    ):
        return "list_item"

    # Equation: high ratio of math symbols, narrow block
    math_chars = set(
        "∑∫∂∇αβγδεζηθλμνξπρστφψω=≈≤≥±×÷→←↔∈∉⊂⊃∪∩‖"
    )
    math_ratio = (
        sum(1 for c in text if c in math_chars) / max(len(text), 1)
    )
    if math_ratio > 0.05 and block_w < page_width * 0.5:
        return "equation"

    return "paragraph"


def detect_tables(page_num):
    try:
        with pdfplumber.open(PDF_PATH) as pdf:
            if page_num < len(pdf.pages):
                return [t.bbox for t in pdf.pages[page_num].find_tables()]
    except Exception:
        pass
    return []


def label_abstract_blocks(blocks, classified):
    """Relabel paragraph blocks between 'abstract' and next section."""
    abstract_idx = next(
        (
            i for i, (b, c) in enumerate(zip(blocks, classified))
            if c == "section_header"
            and get_block_text(b).strip().lower() == "abstract"
        ),
        None,
    )
    if abstract_idx is None:
        return classified

    intro_idx = next(
        (
            i for i, (_, c) in enumerate(zip(blocks, classified))
            if i > abstract_idx and c == "section_header"
        ),
        len(classified),
    )

    # Any non-image body block between abstract header and next section
    # is abstract content, regardless of its initial label.
    _NOT_ABSTRACT = {"section_header", "figure", "figure_caption", "table"}
    result = list(classified)
    for i in range(abstract_idx + 1, intro_idx):
        if result[i] not in _NOT_ABSTRACT:
            result[i] = "abstract"
    return result


def draw_legend(draw, x, y, categories_used):
    pad = 4
    row_h = 16
    max_label = max(len(c) for c in categories_used) if categories_used else 8
    box_w = 14 + max_label * 7 + pad * 2
    box_h = len(categories_used) * row_h + pad * 2

    draw.rectangle(
        [x, y, x + box_w, y + box_h],
        fill=(255, 255, 255, 220),
        outline=(0, 0, 0, 180),
    )
    for i, cat in enumerate(sorted(categories_used)):
        color = CATEGORY_COLORS.get(cat, CATEGORY_COLORS["other"])
        cy = y + pad + i * row_h
        draw.rectangle(
            [x + pad, cy + 2, x + pad + 12, cy + 12],
            fill=color + (230,),
        )
        draw.text((x + pad + 16, cy), cat, fill=(0, 0, 0, 255))


def process_page(page, page_num, scale=2.5):
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    draw = ImageDraw.Draw(img, "RGBA")

    page_height = page.rect.height
    page_width = page.rect.width

    # Use default flags so image blocks (type=1) are included
    blocks = page.get_text("dict")["blocks"]
    table_rects = detect_tables(page_num)
    title_size, body_size = compute_font_sizes(blocks)

    classified = [
        classify_block(
            b, page_height, page_width, page_num,
            table_rects, title_size, body_size,
        )
        for b in blocks
    ]
    classified = label_abstract_blocks(blocks, classified)

    results = []
    categories_used = set()

    # Draw table outlines first (as background layer)
    for bb in table_rects:
        sx0, sy0, sx1, sy1 = [c * scale for c in bb]
        color = CATEGORY_COLORS["table"]
        draw.rectangle(
            [sx0, sy0, sx1, sy1],
            fill=color + (18,),
            outline=color + (220,),
            width=3,
        )
        lbl = "table"
        lw = len(lbl) * 7 + 6
        draw.rectangle(
            [sx0, sy0 - 16, sx0 + lw, sy0],
            fill=color + (220,),
        )
        draw.text((sx0 + 3, sy0 - 15), lbl, fill=(255, 255, 255, 255))
        categories_used.add("table")
        results.append({
            "category": "table",
            "bbox": list(bb),
            "text": "[TABLE]",
        })

    for block, category in zip(blocks, classified):
        color = CATEGORY_COLORS.get(category, CATEGORY_COLORS["other"])
        bx0, by0, bx1, by1 = block["bbox"]
        rx0 = bx0 * scale
        ry0 = by0 * scale
        rx1 = bx1 * scale
        ry1 = by1 * scale

        draw.rectangle(
            [rx0, ry0, rx1, ry1],
            fill=color + (28,),
            outline=color + (210,),
            width=2,
        )

        lbl = category
        lw = len(lbl) * 7 + 6
        tag_y = max(ry0 - 16, 0)
        draw.rectangle(
            [rx0, tag_y, rx0 + lw, tag_y + 14],
            fill=color + (220,),
        )
        draw.text((rx0 + 3, tag_y + 1), lbl, fill=(255, 255, 255, 255))

        categories_used.add(category)
        text_content = (
            get_block_text(block)[:200]
            if block["type"] == 0
            else "[IMAGE]"
        )
        results.append({
            "category": category,
            "bbox": [round(c, 2) for c in block["bbox"]],
            "text": text_content,
        })

    legend_x = img.width - 200
    legend_y = img.height - (len(categories_used) * 16 + 12)
    draw_legend(draw, legend_x, legend_y, categories_used)

    return img, results


def main():
    doc = fitz.open(PDF_PATH)
    total_pages = len(doc)
    all_results = {}

    plural = "s" if total_pages > 1 else ""
    print(f"PDF: '{PDF_PATH}'  ({total_pages} page{plural})\n")

    for page_num in range(total_pages):
        page = doc[page_num]
        print(f"  Page {page_num + 1}...", end=" ", flush=True)
        img, results = process_page(page, page_num, scale=2.5)

        out_path = os.path.join(
            OUTPUT_DIR, f"page_{page_num + 1:03d}_classified.png"
        )
        img.save(out_path)
        all_results[f"page_{page_num + 1}"] = results
        cats = Counter(r["category"] for r in results)
        print(f"saved → {out_path}  |  {dict(cats)}")

    json_path = os.path.join(OUTPUT_DIR, "elements.json")
    with open(json_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nJSON → {json_path}")

    all_cats = [
        r["category"] for pdata in all_results.values() for r in pdata
    ]
    print("\nOverall category distribution:")
    for cat, cnt in Counter(all_cats).most_common():
        bar = "█" * cnt
        print(f"  {cat:20s} {cnt:3d}  {bar}")


if __name__ == "__main__":
    main()
