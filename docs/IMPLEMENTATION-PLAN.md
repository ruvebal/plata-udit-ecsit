# PLATA Extract: Neural Backend — Implementation Plan

**Project:** marker-pdf wrapper for Digital Humanities PDF extraction (neural backend)  
**Scope:** `/Users/ruvebal/src/plata`  
**Parent project:** PLATA (digitaLización de Archivos con Tecnología interactivA)  
**Status:** Implemented (see [IMPLEMENTATION-VERIFICATION.md](./IMPLEMENTATION-VERIFICATION.md))  
**See also:** [IMPLEMENTATION-PLAN-PLAIN.md](./IMPLEMENTATION-PLAN-PLAIN.md) — plain (non-neural) backend

**Environment:** Python 3.10–3.12 only (`requires-python = ">=3.10,<3.13"`). Use `python -m pip install -e '.[neural]'` for the neural backend.

**When marker/surya errors occur:** Some PDFs trigger `index out of bounds` or `torch.AcceleratorError` inside marker-pdf/surya. The wrapper catches these and suggests `--backend plain` or `--max-pages N`. See [TROUBLESHOOTING.md](./TROUBLESHOOTING.md).

---

## 1. Objective

Create a **thin, scholar-friendly Python wrapper** around [marker-pdf](https://github.com/datalab-to/marker) (GPL-3.0) that:

- Converts heritage PDFs into clean Markdown + extracted images
- Checks PDF integrity before processing (corrupted files, encrypted, zero-page)
- Produces a strict output layout: `export_dir/FILENAME/index.md` + `export_dir/FILENAME/images/001.jpeg`
- Supports single-file and batch (directory) processing
- Is usable by humanities researchers with zero ML/AI background

**License note:** marker-pdf is GPL-3.0 for code, model weights under AI Pubs Open Rail-M (free for research, personal use, and startups under $2M). This wrapper is for **scholarly/research** use.

---

## 2. Why marker-pdf for the Neural Backend (Not Docling, Not Raw PyMuPDF)

> **Note:** After implementing the neural backend, we added a **plain backend** using pymupdf4llm + PyMuPDF for fast, lightweight extraction without models. See [IMPLEMENTATION-PLAN-PLAIN.md](./IMPLEMENTATION-PLAN-PLAIN.md). The comparison below motivated choosing marker-pdf specifically for the **neural** backend where ML accuracy matters most.

| Tool | Heuristic Score | LLM Score | Speed | Layout-Aware | Tables | Images | OCR |
|------|-----------------|-----------|-------|--------------|--------|--------|-----|
| **marker-pdf** | **95.67** | **4.24** | 2.84s/page | Yes (surya) | Yes (HTML) | Yes | Yes (surya) |
| Docling | 86.71 | 3.70 | 3.70s/page | Yes | Yes | Limited | Yes |
| PyMuPDF (raw) | N/A | N/A | Fast | No | No | Manual | No |
| Llamaparse | 84.24 | 3.98 | 23.3s/page | Cloud only | Yes | Yes | Cloud |

Source: [marker-pdf benchmarks](https://github.com/datalab-to/marker)

**marker-pdf wins** on accuracy (95.67 heuristic), speed, and local execution. It handles:
- Layout detection and reading order (via surya)
- Tables preserved as HTML/Markdown
- Image extraction and saving
- OCR for scanned pages (via surya, not Tesseract — better quality)
- Multi-language support (critical for Spanish heritage documents)
- Works on GPU, CPU, or **MPS** (Apple Silicon M4)
- `--use_llm` hybrid mode for highest accuracy (optional, uses Ollama locally)

The existing PLATA prototype (`extraertexto.py`) uses raw PyMuPDF with font-size heuristics for heading detection. marker-pdf replaces this entirely with ML-based layout detection.

---

## 3. Architecture Decision: Batch Strategy

### Question: Use marker's built-in batch or wrap single-process?

**Decision: Wrap single-process (`PdfConverter` API), own batch management.**

| Aspect | marker built-in batch | Our wrapper (chosen) |
|--------|----------------------|---------------------|
| Pre-flight PDF check | No | **Yes** (integrity, encryption, page count) |
| Output structure | marker's default | **Custom** (`FILE/index.md` + `FILE/images/`) |
| Per-file error handling | Stops or skips silently | **Graceful** (report, continue) |
| Progress reporting | Basic | **Scholar-friendly** (file N/M, ETA) |
| Model loading | Per-worker | **Once, shared** across all files |
| Parallelism | Built-in (VRAM-aware) | **Sequential default**, optional `--workers` |
| Complexity | Opaque | **Transparent** (~200 lines of wrapper) |

**Rationale:** Scholars process 10-50 PDFs, not 10,000. Reliability and clarity matter more than throughput. Models are loaded once into memory and reused for every file — this is already fast enough on M4 (0.18s/page). If parallel processing is needed later, we add `--workers N` using `concurrent.futures`.

---

## 4. Project Structure

```
/Users/ruvebal/src/plata/
├── .cursor/
│   └── rules/
│       └── plata-extract.mdc         # Cursor rules for this project
├── docs/
│   └── IMPLEMENTATION-PLAN.md        # This document
│
├── plata_extract/
│   ├── __init__.py                   # Version, public API
│   ├── check.py                      # PDF integrity verification
│   ├── extract.py                    # Core marker-pdf wrapper
│   └── cli.py                        # CLI entry point (argparse)
│
├── pyproject.toml                    # Project metadata, dependencies
├── README.md                         # Scholar-friendly documentation
└── .gitignore
```

---

## 5. Module Design

### 5.1 `check.py` — PDF Integrity Verification

**Before** any extraction, validate the PDF:

```python
def check_pdf(path: Path) -> CheckResult:
    """
    Pre-flight checks:
    1. File exists and is readable
    2. File has .pdf extension
    3. File starts with %PDF magic bytes
    4. PyMuPDF can open it (not corrupted)
    5. Not encrypted / password-protected
    6. Has at least 1 page
    Returns CheckResult(ok=bool, reason=str, page_count=int)
    """
```

**Why:** Heritage archive PDFs are often old scans. Some are corrupted, some are password-protected institutional copies. Failing early with a clear message saves scholar time.

### 5.2 `extract.py` — Core Extraction

```python
class PlatExtractor:
    """
    Wraps marker-pdf's PdfConverter.
    Models loaded once in __init__, reused for every file.
    """
    def __init__(self, use_llm: bool = False, force_ocr: bool = False):
        # Load marker models ONCE (list, not dict)
        self.model_lst = load_all_models(force_load_ocr=force_ocr)
        self.config = {...}

    def extract_file(self, pdf_path: Path, output_dir: Path) -> ExtractResult:
        """
        Convert a single PDF to:
          output_dir/FILENAME/index.md
          output_dir/FILENAME/images/001.jpeg, 002.jpeg, ...
        """

    def extract_batch(self, input_dir: Path, output_dir: Path) -> BatchResult:
        """
        Process all PDFs in input_dir.
        1. List and sort PDFs
        2. Pre-flight check each one
        3. Extract valid PDFs (sequential)
        4. Report summary (succeeded, failed, skipped)
        """
```

**Key design choices:**
- `load_all_models()` is called **once** — this loads ~3GB of surya models into RAM/VRAM
- Each `extract_file()` calls `convert_single_pdf(path, self.model_lst)` reusing the shared model list
- Images are renumbered sequentially (001.jpeg, 002.jpeg) for clean references
- marker's `output_format="markdown"` is the default; JSON available via flag

### 5.3 `cli.py` — Command-Line Interface

```
# Single file
plata-extract paper.pdf -o exports/

# Batch (all PDFs in directory)
plata-extract archive/ -o exports/

# With OCR force (scanned documents)
plata-extract archive/ -o exports/ --force-ocr

# With LLM enhancement (requires Ollama)
plata-extract archive/ -o exports/ --use-llm --llm-service ollama
```

**Scholar-friendly output:**
```
PLATA Extract v0.1.0
Loading models... done (3.2s)

[1/12] Checking: Creadores_Cientificos.pdf ... OK (45 pages)
[1/12] Extracting: Creadores_Cientificos.pdf ... done (8.1s)
       → exports/Creadores_Cientificos/index.md (12,340 words)
       → exports/Creadores_Cientificos/images/ (23 images)

[2/12] Checking: Album_JRJ.pdf ... OK (210 pages)
[2/12] Extracting: Album_JRJ.pdf ... done (37.8s)
       → exports/Album_JRJ/index.md (4,200 words)
       → exports/Album_JRJ/images/ (156 images)

[3/12] Checking: corrupted_file.pdf ... SKIP (corrupted: cannot open)

...

Summary: 11 succeeded, 1 skipped, 0 failed
Total time: 3m 42s
```

---

## 6. Output Structure

For a PDF named `Creadores_Cientificos.pdf`:

```
exports/
├── Creadores_Cientificos/
│   ├── index.md                       # Full document in Markdown
│   └── images/
│       ├── 001.jpeg                   # First image extracted
│       ├── 002.jpeg
│       └── ...
├── Album_JRJ/
│   ├── index.md
│   └── images/
│       ├── 001.jpeg
│       └── ...
└── _report.json                       # Batch summary (optional)
```

The Markdown file references images as:

```markdown
![Image](images/001.jpeg)
```

---

## 7. Dependencies

```toml
[project]
dependencies = [
    "marker-pdf",               # Core extraction engine
    "PyMuPDF",                  # PDF integrity checks (lightweight)
]

[project.optional-dependencies]
full = [
    "marker-pdf[full]",         # Support for DOCX, PPTX, etc.
]
```

(No version pins so pip can resolve dependency conflicts.)

marker-pdf internally brings: torch, surya-ocr, pdftext, PIL, etc.

---

## 8. marker-pdf Integration Details

### Python API (what we use)

```python
from marker.models import load_all_models
from marker.convert import convert_single_pdf

# Load models once (expensive: ~3-5s, ~3GB RAM)
model_lst = load_all_models(force_load_ocr=False)

# Convert a file (fast: ~0.18s/page on GPU)
full_text, images, out_metadata = convert_single_pdf("/path/to/file.pdf", model_lst)
# full_text = markdown string
# images = dict of {name: PIL.Image}
# out_metadata = toc, pages, ocr_stats, etc.
```

### Available output formats

- `markdown` (default) — clean Markdown with image links
- `json` — tree structure with block types, polygons, hierarchy
- `html` — HTML with math, code, images
- `chunks` — flattened blocks for RAG (useful for PLATA Scholar downstream)

### LLM enhancement (optional)

marker-pdf supports `--use_llm` with Ollama (local), Gemini, Claude, OpenAI. For our offline-first philosophy, we'd use **Ollama** with a local model:

```python
# use_llm / output_format: current marker.convert API uses settings; not passed per-call
```

---

## 9. Implementation Prompt

The following prompt can be used to implement the wrapper:

> **PROMPT:**
>
> "Build a Python CLI wrapper around marker-pdf for Digital Humanities PDF extraction.
>
> **Project path:** `/Users/ruvebal/src/plata`
>
> **Modules to create:**
>
> 1. `plata_extract/check.py`: PDF integrity checker using PyMuPDF.
>    - Verify file exists, has .pdf extension, starts with %PDF magic bytes.
>    - Open with fitz (PyMuPDF) to check for corruption.
>    - Detect encryption. Count pages. Return a dataclass `CheckResult(ok, reason, page_count)`.
>
> 2. `plata_extract/extract.py`: Core extraction using marker-pdf Python API.
>    - Class `PlatExtractor` that calls `load_all_models(force_load_ocr=...)` once in `__init__`.
>    - Method `extract_file(pdf_path, output_dir)` that calls `convert_single_pdf(path, self._model_lst)`, writes `FILENAME/index.md`, saves images to `FILENAME/images/NNN.jpeg`.
>    - Method `extract_batch(input_dir, output_dir)` that lists PDFs, checks each, extracts valid ones sequentially, prints progress `[N/M]`, returns summary.
>    - Support `force_ocr` via `load_all_models(force_load_ocr=...)`; `use_llm`/`output_format` left for future if marker exposes them in convert_single_pdf.
>
> 3. `plata_extract/cli.py`: argparse CLI.
>    - Positional: `input` (file or directory).
>    - `--output-dir` / `-o` (default: `./exports`).
>    - `--force-ocr` flag.
>    - `--use-llm` flag (requires Ollama or API key).
>    - `--format` (markdown|json|html, default: markdown).
>    - `--workers` (default: 1, for future parallel support).
>    - Entry point: `plata-extract`.
>
> 4. `pyproject.toml`: metadata, dependencies (`marker-pdf`, `PyMuPDF` — no version pins), `[project.scripts]` entry point.
>
> **Output structure per PDF:**
> ```
> output_dir/FILENAME/index.md
> output_dir/FILENAME/images/001.jpeg
> ```
>
> **Design constraints:**
> - Load marker models ONCE, reuse for all files.
> - Check PDF integrity BEFORE extraction.
> - Sequential processing by default (simple, predictable).
> - Scholar-friendly CLI output: `[N/M] file.pdf ... done (Xs, N images)`.
> - All errors caught per-file; never crash the batch.
> - Use `set -euo pipefail` equivalent: strict Python (type hints, logging, no bare except)."

---

## 10. Relation to PLATA Scholar

This wrapper is the **Ingestor** layer. Its output feeds directly into the PLATA Scholar monolith:

```
PDF → plata-extract (plain OR neural) → Markdown + Images → plata-scholar (Upload page) → ChromaDB + SQLite
```

Both backends produce the **same** output structure (`FILENAME/index.md` + `FILENAME/images/`), so downstream consumers do not need to know which backend was used. The `chunks` output format from marker-pdf (neural backend) is particularly useful: it produces flat blocks ready for RAG embedding without additional chunking logic.

---

## 11. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| marker-pdf GPU requirement | Scholars may not have GPU | Works on CPU and MPS (M4). Slower but functional. |
| Large model download (~3GB) | First-run takes time | Document in README; add `--check-only` mode for dry run. |
| GPL-3.0 license | Derivative work must be GPL | Acceptable for research; document clearly. |
| Scanned PDFs with poor quality | Low OCR accuracy | Use `--force-ocr`; document `--use-llm` for highest accuracy. |
| marker-pdf API changes | Breaking updates | No version pins by default so pip can resolve; pin after resolving if needed; test with CI. |
