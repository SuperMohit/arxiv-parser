# pdf-parser

Classifies and annotates the structural elements of an **academic research paper PDF** — titles, authors, abstracts, section headers, figures, tables, equations, references, and more — and renders each page as a color-coded PNG with a legend.

Built for arXiv-style papers. The classifier understands academic conventions: numbered sections, `[N]` bibliography entries, institutional affiliations, abstract boundaries, and arXiv watermarks.

## What it does

For every page in a PDF it:

1. Extracts text blocks and font metadata via **PyMuPDF**
2. Detects table bounding boxes via **pdfplumber**
3. Classifies each block into one of 19 categories (see below)
4. Renders an annotated PNG with colored overlays and a per-page legend
5. Writes all results to a JSON file (`output/elements.json`)

### Categories

| Category | Description |
|---|---|
| `title` | Document title (largest bold text near top of page 1) |
| `authors` | Author names |
| `affiliation` | Institutional affiliations and emails |
| `abstract` | Abstract body text |
| `section_header` | Numbered or named section headings |
| `paragraph` | Body text |
| `figure` | Image blocks |
| `figure_caption` | "Figure N …" captions |
| `table` | Table bounding region (detected by pdfplumber) |
| `table_row` | Text block inside a detected table |
| `table_caption` | "Table N …" captions |
| `equation` | Math-heavy narrow blocks |
| `reference` | `[N] Author …` bibliography entries |
| `list_item` | Bulleted or numbered list items |
| `footnote` | Small text near bottom of page |
| `footer` | Footer lines |
| `page_number` | Digit-only text near page bottom |
| `watermark` | Rotated narrow blocks (e.g. arXiv sidebar) |
| `other` | Anything that doesn't match above |

## Setup

Requires Python ≥ 3.12. Uses [uv](https://github.com/astral-sh/uv) for dependency management.

```bash
uv sync
```

## Usage

Set `PDF_PATH` at the top of [classify_pdf.py](classify_pdf.py) to point at your PDF, then run:

```bash
uv run python classify_pdf.py
```

Outputs:

- `output/page_001_classified.png`, `page_002_classified.png`, … — annotated page images
- `output/elements.json` — all classified blocks with category, bounding box, and truncated text

## Dependencies

- [PyMuPDF](https://pymupdf.readthedocs.io/) — PDF rendering and text extraction
- [pdfplumber](https://github.com/jsvine/pdfplumber) — table detection
- [Pillow](https://python-pillow.org/) — image rendering and annotation
# arxiv-parser
