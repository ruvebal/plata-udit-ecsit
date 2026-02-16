# Implementation Plan Verification (Neural Backend)

**Plan:** [IMPLEMENTATION-PLAN.md](./IMPLEMENTATION-PLAN.md) (neural backend)  
**Plain backend plan:** [IMPLEMENTATION-PLAN-PLAIN.md](./IMPLEMENTATION-PLAN-PLAIN.md) (not yet implemented)  
**Verified:** Checklist against current codebase.

> This verification covers the **neural backend** (`extract.py`, marker-pdf). The plain backend (`extract_plain.py`, pymupdf4llm) has its own implementation plan and will have its own verification once implemented.

---

## 1. Objective (Plan §1)

| Requirement | Status | Evidence |
|-------------|--------|----------|
| Converts PDFs to Markdown + images | ✅ | `extract.py`: `text_from_rendered`, write `index.md`, save images as JPEG |
| Checks integrity before processing | ✅ | `check.py`: `check_pdf()` with 6 checks; called in `extract_batch` and CLI |
| Output layout: `FILENAME/index.md` + `FILENAME/images/001.jpeg` | ✅ | `extract.py`: `doc_dir / "index.md"`, `doc_dir / "images"`, `images/NNN.jpeg` |
| Single-file and batch processing | ✅ | `cli.py`: branch on file vs dir; `extract_file`, `extract_batch` |
| Usable by scholars (CLI, clear messages) | ✅ | README, argparse, progress `[N/M]`, summary |

---

## 2. Project Structure (Plan §4)

| Expected | Status | Actual |
|----------|--------|--------|
| `.cursor/rules/plata-extract.mdc` | ✅ | Present |
| `docs/IMPLEMENTATION-PLAN.md` | ✅ | Present |
| `plata_extract/__init__.py` | ✅ | Version, public API |
| `plata_extract/check.py` | ✅ | PDF integrity |
| `plata_extract/extract.py` | ✅ | Core wrapper |
| `plata_extract/cli.py` | ✅ | CLI entry |
| `pyproject.toml` | ✅ | Metadata, deps, script |
| `README.md` | ✅ | Scholar docs |
| `.gitignore` | ✅ | Present |

---

## 3. Module Design

### 3.1 check.py (Plan §5.1)

| Check | Status | Code |
|-------|--------|------|
| 1. File exists, readable | ✅ | `path.exists()`, `path.is_file()`, `file_size` |
| 2. .pdf extension | ✅ | `path.suffix.lower() != ".pdf"` |
| 3. %PDF magic bytes | ✅ | `PDF_MAGIC = b"%PDF-"`, `header.startswith(PDF_MAGIC)` |
| 4. PyMuPDF opens (not corrupted) | ✅ | `fitz.open(path)` in try/except |
| 5. Not encrypted | ✅ | `doc.is_encrypted` |
| 6. At least 1 page | ✅ | `doc.page_count == 0` |
| Returns CheckResult(ok, reason, page_count) | ✅ | `CheckResult` dataclass with `ok`, `path`, `reason`, `page_count`, `file_size_mb` |

### 3.2 extract.py (Plan §5.2)

| Requirement | Status | Code |
|-------------|--------|------|
| PlatExtractor, models once in __init__ | ✅ | `load_all_models(force_load_ocr=...)` in `__init__`, `self._model_lst` |
| extract_file(pdf_path, output_dir) → ExtractResult | ✅ | Writes `FILENAME/index.md`, `FILENAME/images/NNN.jpeg` |
| extract_batch(input_dir, output_dir) → BatchResult | ✅ | `list_pdfs`, check each, sequential extract, summary |
| Reuse model list per file | ✅ | `convert_single_pdf(path, self._model_lst)` |
| force_ocr, use_llm, output_format | ✅ | `__init__(force_ocr, use_llm, output_format, llm_service)`; force_ocr → load_all_models(force_load_ocr) |
| Images 001.jpeg, 002.jpeg | ✅ | `f"{image_count:03d}.jpeg"` |
| Image refs in markdown: `images/001.jpeg` | ✅ | `image_name_map[original_name] = f"images/{new_name}"` |

### 3.3 cli.py (Plan §5.3)

| Requirement | Status | Code |
|-------------|--------|------|
| Positional: input (file or dir) | ✅ | `parser.add_argument("input", type=Path)` |
| -o / --output-dir (default ./exports) | ✅ | `default=Path("./exports")` |
| --force-ocr | ✅ | `action="store_true"` |
| --use-llm | ✅ | `action="store_true"` |
| --llm-service | ✅ | `type=str, default=None` |
| --format (markdown|json|html|chunks) | ✅ | `choices=["markdown", "json", "html", "chunks"]` |
| --check-only | ✅ | Only integrity, no extraction |
| Entry point plata-extract | ✅ | `pyproject.toml`: `plata-extract = "plata_extract.cli:main"` |
| Scholar-friendly output | ✅ | `[N/M]`, word count, image count, summary |

**Note:** Plan mentions `--workers` for future parallel support; not implemented (sequential only). Plan says "optional" / "later".

---

## 4. Output Structure (Plan §6)

| Requirement | Status | Actual |
|-------------|--------|--------|
| output_dir/FILENAME/index.md | ✅ | `md_path = doc_dir / "index.md"` |
| output_dir/FILENAME/images/001.jpeg | ✅ | `images_dir = doc_dir / "images"`, save as `NNN.jpeg` |
| Markdown refs: `![](images/001.jpeg)` | ✅ | Relative from index.md |

---

## 5. Dependencies (Plan §7)

| Requirement | Status | pyproject.toml |
|-------------|--------|----------------|
| marker-pdf | ✅ | `dependencies` (no version pin) |
| PyMuPDF | ✅ | `dependencies` (no version pin) |
| optional full: marker-pdf[full] | ✅ | `[project.optional-dependencies] full` |

---

## 6. Summary

| Section | Items | Implemented | Missing |
|---------|--------|-------------|---------|
| §1 Objective | 5 | 5 | 0 |
| §4 Project structure | 9 | 9 | 0 |
| §5.1 check.py | 7 | 7 | 0 |
| §5.2 extract.py | 7 | 7 | 0 |
| §5.3 cli.py | 9 | 8 | 1 (--workers optional) |
| §6 Output | 3 | 3 | 0 |
| §7 Dependencies | 3 | 3 | 0 |

**Verdict:** The neural backend implementation plan has been **fully implemented** except for the optional `--workers` flag for future parallelism, which the plan explicitly defers.

**Next:** The plain backend (`extract_plain.py`) is planned but not yet implemented. See [IMPLEMENTATION-PLAN-PLAIN.md](./IMPLEMENTATION-PLAN-PLAIN.md).

---

## 7. Test Run: ALBUM_Juan_Ramon_Jimenez.pdf

**Test PDF:** `/Users/ruvebal/projects/ruvebal/scholar/udit/research/plata/Pddf2Json/PlataPDFExporter/ALBUM_Juan_Ramon_Jimenez.pdf`

### 7.1 Integrity check (no marker-pdf required)

```bash
cd /Users/ruvebal/src/plata
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e . --no-deps && pip install PyMuPDF
plata-extract "/path/to/ALBUM_Juan_Ramon_Jimenez.pdf" --check-only
```

**Result:** ✅ Pass

```
PLATA Extract v0.1.0
ALBUM_Juan_Ramon_Jimenez.pdf: 650 pages, 52.36MB
Check passed.
```

- File: 650 pages, 52.36 MB
- All 6 checks passed (exists, .pdf, %PDF magic, opens with PyMuPDF, not encrypted, page_count > 0)

### 7.2 Full extraction (requires marker-pdf)

Full extraction requires `marker-pdf` and its dependencies (PyTorch, etc.). Use **Python 3.10–3.12** (see README). Install and run:

```bash
cd /Users/ruvebal/src/plata
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .
plata-extract "/path/to/ALBUM_Juan_Ramon_Jimenez.pdf" -o ./test_export
```

Expected output layout after a successful run:

```
test_export/
└── ALBUM_Juan_Ramon_Jimenez/
    ├── index.md
    └── images/
        ├── 001.jpeg
        ├── 002.jpeg
        └── ...
```

**Error handling test (no marker-pdf):** Running extraction without marker-pdf yields a clear message:

```
ImportError: marker-pdf not installed. Install with:
  pip install marker-pdf
```
