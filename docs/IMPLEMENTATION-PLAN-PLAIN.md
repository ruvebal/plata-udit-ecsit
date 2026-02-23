# PLATA Extract: Plain Extraction — Implementation Plan

**Project:** PDF extraction for Digital Humanities
**Scope:** `/Users/ruvebal/src/plata`
**Parent project:** PLATA (digitaLización de Archivos con Tecnología interactivA)
**Status:** Planned
**Depends on:** [IMPLEMENTATION-PLAN.md](./IMPLEMENTATION-PLAN.md) (neural backend, already implemented)

**Environment:** Python 3.10–3.12 only. Install with `python -m pip install -e .` (plain is default). If neural fails on a PDF (marker/surya errors), use plain for that file; see [TROUBLESHOOTING.md](./TROUBLESHOOTING.md).

---

## 1. Objective

Add a **plain (non-neural) extraction backend** to `plata-extract` that runs **instantly on any machine** without GPU, ~3 GB of model downloads, or multi-minute startup times. The existing marker-pdf backend is renamed **"neural"** and the new backend is called **"plain"**.

| Property         | Neural (`--backend neural`)        | Plain (`--backend plain`)              |
| ---------------- | ---------------------------------- | -------------------------------------- |
| Engine           | marker-pdf (surya models)          | **pymupdf4llm + PyMuPDF**              |
| Startup          | ~3–5 min (model download + load)   | **< 1 s**                              |
| GPU required     | No (but 10× faster)                | **No**                                 |
| RAM required     | ~8 GB+                             | **< 500 MB**                           |
| Tables           | ML table detection (high accuracy) | Heuristic line-based (`lines_strict`)  |
| OCR              | surya (state-of-art)               | Optional Tesseract via PyMuPDF         |
| Image extraction | From rendered pages                | **Direct from PDF objects** (lossless) |
| Reading order    | ML ordering model                  | Font-size / position heuristic         |
| Math/equations   | LaTeX via Texify model             | Raw text (no LaTeX)                    |
| Accuracy         | Best-in-class (95.67)              | Good for digitally-authored PDFs       |
| Speed (CPU)      | ~5–30 s/page                       | **< 0.1 s/page**                       |
| Best for         | Scanned docs, complex layouts      | Clean, modern, digitally-authored PDFs |

**When to use which:**

- **Plain:** Fast first pass; modern PDFs; scholar laptops with limited resources; CI/CD pipelines; batch of thousands of files.
- **Neural:** Scanned manuscripts; complex multi-column layouts; heritage publications with figures/tables that need ML to parse correctly.

---

## 2. Architecture: Design

### 2.1 Backend Selection via CLI

```bash
# Default: plain (fast, no models needed)
plata-extract paper.pdf

# Explicit plain
plata-extract paper.pdf --backend plain

# Neural (current marker-pdf)
plata-extract paper.pdf --backend neural --force-ocr
```

**Default is `plain`** because:

- Most scholars just want text out of a PDF quickly.
- No model download / GPU / memory surprise on first run.
- Neural is opt-in for when quality matters more than speed.

### 2.2 Shared Infrastructure

Both backends share the **same pipeline** — only the extraction engine differs:

```
PDF → check.py (integrity) → [backend].extract_file() → save(index.md + images/) → ExtractResult
```

Shared code:

- `check.py` — PDF integrity checks (unchanged).
- `ExtractResult`, `BatchResult` dataclasses (unchanged).
- `cli.py` — CLI entry point; dispatches to the selected backend.
- Output structure: `FILENAME/index.md` + `FILENAME/images/NNN.jpeg` (identical for both).

### 2.3 Module Layout (after implementation)

```
plata_extract/
├── __init__.py                  # Version, public API
├── check.py                     # PDF integrity (shared, unchanged)
├── extract.py                   # Neural backend (PlatExtractor, renamed from generic)
├── extract_plain.py             # NEW: Plain backend (PlainExtractor)
└── cli.py                       # CLI (updated: --backend flag, dispatching)
```

---

## 3. New Module: `extract_plain.py`

### 3.1 Class Design

```python
class PlainExtractor:
    """
    Non-neural PDF extraction using pymupdf4llm + PyMuPDF.

    No model loading, no GPU, instant startup.
    Best for digitally-authored PDFs.
    """

    def __init__(self, force_ocr: bool = False):
        """No heavy init — just store config."""
        self.force_ocr = force_ocr

    def extract_file(
        self,
        pdf_path: Path,
        output_dir: Path,
        max_pages: Optional[int] = None,
    ) -> ExtractResult:
        """Same contract as PlatExtractor.extract_file()."""
        ...

    def extract_batch(
        self,
        input_dir: Path,
        output_dir: Path,
        max_pages: Optional[int] = None,
    ) -> BatchResult:
        """Same contract as PlatExtractor.extract_batch()."""
        ...
```

### 3.2 Extraction Logic

```python
import pymupdf4llm

# 1. Convert PDF to Markdown with image extraction
md_text = pymupdf4llm.to_markdown(
    doc=str(pdf_path),
    pages=list(range(max_pages)) if max_pages else None,
    write_images=True,
    image_path=str(images_dir),
    image_format="jpeg",
    dpi=150,
    use_ocr=self.force_ocr,
)

# 2. Rewrite image paths to match our layout (images/NNN.jpeg)
#    pymupdf4llm saves images with original names; renumber to 001.jpeg, 002.jpeg

# 3. Write index.md
md_path.write_text(md_content, encoding="utf-8")
```

### 3.3 Key Differences from Neural Backend

| Aspect       | Neural (`extract.py`)                 | Plain (`extract_plain.py`)           |
| ------------ | ------------------------------------- | ------------------------------------ |
| Init         | Loads 6 models (~3 GB, 3–5 min)       | No-op (instant)                      |
| Convert      | `convert_single_pdf(path, model_lst)` | `pymupdf4llm.to_markdown(path, ...)` |
| Images       | From rendered pages (PIL)             | Direct from PDF objects (PyMuPDF)    |
| Dependencies | marker-pdf + torch + surya + ...      | **pymupdf4llm + PyMuPDF** only       |
| OCR          | surya (loaded with models)            | Tesseract via PyMuPDF (if installed) |

### 3.4 Batch Reuse

`PlainExtractor.extract_batch()` follows the **same pattern** as `PlatExtractor.extract_batch()`:

- List PDFs, check each, extract valid ones sequentially.
- Progress `[N/M]`, per-file error handling, summary.
- The batch method can be extracted to a shared mixin or free function to avoid duplication. See §5.

---

## 4. CLI Changes

### 4.1 New `--backend` Flag

```python
parser.add_argument(
    "--backend",
    choices=["plain", "neural"],
    default="plain",
    help="Extraction backend: 'plain' (fast, no GPU) or 'neural' (marker-pdf, highest accuracy). Default: plain.",
)
```

### 4.2 Dispatch Logic

```python
if args.backend == "neural":
    from plata_extract.extract import PlatExtractor
    extractor = PlatExtractor(
        force_ocr=args.force_ocr,
        use_llm=args.use_llm,
        output_format=args.format,
        llm_service=args.llm_service,
    )
else:
    from plata_extract.extract_plain import PlainExtractor
    extractor = PlainExtractor(force_ocr=args.force_ocr)
```

### 4.3 Neural-Only Flags

`--use-llm`, `--llm-service`, and `--format` (json/html/chunks) are only valid with `--backend neural`. With `--backend plain`, warn and ignore (or error) if used.

### 4.4 Updated Examples

```bash
# Fast extraction (default, plain)
plata-extract paper.pdf -o exports/

# Neural for highest accuracy
plata-extract paper.pdf --backend neural -o exports/

# Neural with OCR for scanned docs
plata-extract scanned.pdf --backend neural --force-ocr

# Plain with OCR (Tesseract)
plata-extract scanned.pdf --backend plain --force-ocr

# Batch, plain (processes hundreds of PDFs in minutes)
plata-extract archive/ -o exports/

# Batch, neural
plata-extract archive/ --backend neural -o exports/
```

---

## 5. Shared Batch Logic (DRY)

Both extractors implement `extract_file()` and `extract_batch()`. To avoid duplicating the batch loop/progress/error-handling, extract it:

**Option A — Free function:**

```python
# In a shared module or extract.py
def run_batch(
    extractor,           # PlatExtractor or PlainExtractor (duck typing)
    input_dir: Path,
    output_dir: Path,
    max_pages: Optional[int] = None,
) -> BatchResult:
    """Shared batch loop for any extractor with extract_file()."""
    ...
```

**Option B — Keep duplicated (simpler for now):**

Copy the batch method into `PlainExtractor`. It's ~50 lines and straightforward. Refactor later if a third backend appears.

**Recommendation:** Start with **Option B** (simple duplication). Both files are small. Refactor to Option A only if a third backend materializes.

---

## 6. Dependencies

### pyproject.toml Changes

```toml
[project]
dependencies = [
    "PyMuPDF",          # Integrity checks + plain backend image extraction
    "pymupdf4llm",      # Plain backend: Markdown extraction
]

[project.optional-dependencies]
neural = [
    "marker-pdf",       # Neural backend (brings torch, surya, etc.)
]
full = [
    "marker-pdf[full]", # Neural + non-PDF file support
]
```

**Why:** Base install is lightweight (PyMuPDF + pymupdf4llm ≈ 30 MB). marker-pdf + torch is ~3 GB — only installed when the scholar needs `--backend neural`.

This means `pip install -e .` gives you `plata-extract` with plain backend immediately. For neural: `pip install -e '.[neural]'`.

---

## 7. Output Structure (Unchanged)

Both backends produce the **identical** output layout:

```
output_dir/FILENAME/
├── index.md                     # Markdown content
└── images/                      # Extracted images
    ├── 001.jpeg
    ├── 002.jpeg
    └── ...
```

Image references in Markdown: `![](images/001.jpeg)` (relative to `index.md`).

This ensures downstream consumers (`plata-scholar`, RAG pipelines) work identically regardless of which backend produced the output.

---

## 8. pymupdf4llm Integration Details

### Python API (what we use)

```python
import pymupdf4llm

# Basic: full document to Markdown string
md_text = pymupdf4llm.to_markdown("file.pdf")

# With image extraction
md_text = pymupdf4llm.to_markdown(
    "file.pdf",
    write_images=True,        # Save images as files
    image_path="./images/",   # Where to save them
    image_format="jpeg",      # jpeg or png
    dpi=150,                  # Image resolution
)

# With page range (0-based)
md_text = pymupdf4llm.to_markdown("file.pdf", pages=[0, 1, 2, 3, 4])

# With OCR (requires Tesseract installed)
md_text = pymupdf4llm.to_markdown(
    "file.pdf",
    use_ocr=True,
    ocr_language="spa+eng",
)

# Chunked output (list of dicts per page)
chunks = pymupdf4llm.to_markdown("file.pdf", page_chunks=True)
```

### Key Facts

- **No models to download.** Pure rule-based + heuristic extraction.
- **No GPU.** Runs on CPU in < 0.1 s/page.
- **Tables:** Detected via line analysis (`table_strategy="lines_strict"`).
- **Images:** Extracted directly from PDF objects (not rendered). Lossless for embedded images.
- **Multi-column:** Handled via font/position heuristics.
- **Bold/italic/code:** Detected via font analysis.
- **License:** AGPL-3.0 (pymupdf4llm inherits from PyMuPDF).

---

## 9. Implementation Prompt

> **PROMPT:**
>
> "Add a plain (non-neural) extraction backend to plata-extract.
>
> **Project path:** `/Users/ruvebal/src/plata`
>
> **What to create:**
>
> 1. `plata_extract/extract_plain.py`: Non-neural extractor using pymupdf4llm.
>    - Class `PlainExtractor` with same interface as `PlatExtractor`:
>      - `__init__(force_ocr: bool = False)` — no heavy init.
>      - `extract_file(pdf_path, output_dir, max_pages=None) -> ExtractResult` — uses `pymupdf4llm.to_markdown()` with `write_images=True`, renumbers images to `001.jpeg, 002.jpeg`, writes `FILENAME/index.md`.
>      - `extract_batch(input_dir, output_dir, max_pages=None) -> BatchResult` — same loop as PlatExtractor (list, check, extract, progress, summary).
>
> **What to modify:**
>
> 2. `plata_extract/cli.py`: Add `--backend` flag (`plain` | `neural`, default: `plain`). Dispatch to `PlainExtractor` or `PlatExtractor`. Neural-only flags (`--use-llm`, `--llm-service`, `--format`) warn if used with plain.
> 3. `pyproject.toml`: Move `marker-pdf` to `[project.optional-dependencies] neural`. Add `pymupdf4llm` to base `dependencies`.
> 4. `plata_extract/__init__.py`: Export `PlainExtractor`.
>
> **Design constraints:**
>
> - Same output structure for both backends: `FILENAME/index.md` + `FILENAME/images/NNN.jpeg`.
> - Same `ExtractResult` / `BatchResult` dataclasses.
> - Same integrity check pipeline (`check.py`, unchanged).
> - Plain backend has NO model loading, NO GPU requirement.
> - `--backend plain` is the default (fast, lightweight).
> - `--backend neural` requires `pip install -e '.[neural]'`."

---

## 10. Risks and Mitigations

| Risk                                                 | Impact                              | Mitigation                                                         |
| ---------------------------------------------------- | ----------------------------------- | ------------------------------------------------------------------ |
| pymupdf4llm table detection is less accurate         | Some tables may not parse correctly | Document that `--backend neural` is recommended for complex tables |
| pymupdf4llm image names don't match our layout       | Broken image refs in Markdown       | Renumber images in `extract_file` (same pattern as neural backend) |
| Tesseract not installed for `--force-ocr` with plain | OCR silently fails or errors        | Check for Tesseract at runtime; clear error message if missing     |
| Scholars confused by two backends                    | Choice paralysis                    | Default to `plain`; README explains when to use `neural`           |
| pymupdf4llm AGPL-3.0 license                         | Must disclose source                | Already GPL-3.0 project; AGPL is compatible for research use       |

---

## 11. Relation to PLATA Scholar

Both backends feed the **same** output into the PLATA Scholar monolith:

```
PDF → plata-extract (plain OR neural) → Markdown + Images → plata-scholar → ChromaDB + SQLite
```

The downstream pipeline does not need to know which backend produced the output. The Markdown + images structure is identical.
