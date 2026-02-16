# PLATA Extract – UDIT / ECSiT Research Group

**Convert heritage PDFs to clean Markdown + images — for scholars, by scholars.**

**Author:** Rubén Vega Balbás PhD (UDIT / ECSiT Research Group) <ruben.vega@udit.es>

**Version:** 0.1.0

**License:** [GPL-3.0](LICENSE)

**Status:** 🟡 Ongoing (Ingestion Phase — Active Development)

---

## Team & Affiliations

- **IP:** Rafael Conde Melguizo PhD (ECSIT - UDIT) <rafael.conde@udit.es>
- **Senior Architect:** Rubén Vega Balbás PhD (ECSIT - UDIT) <ruben.vega@udit.es>
- **Senior Collaborator:** Cristóbal Tapia García <cristobal.tapia@upm.es>
- **Junior Developer:** Gregory Torres Molina - CEAC FP <gregory.torres@alu.ceacfp.es>

---

PLATA Extract is a command-line tool that converts PDF documents into structured Markdown files with extracted images. It provides **different extraction backends**:

- **Plain** (default) — Fast, lightweight, no GPU needed. Uses [pymupdf4llm](https://github.com/pymupdf/RAG) + PyMuPDF.
- **Neural** — Highest accuracy. Uses [marker-pdf](https://github.com/datalab-to/marker) with deep learning models for layout detection, OCR, and table parsing.

Designed for the [PLATA project](https://doi.org/10.62161/sauc.v11.5739) (digitalization of the Residencia de Estudiantes archive), but usable for any research involving PDF-to-text conversion.

---

## Plain vs Neural

| Feature        | Plain (default)            | Neural (`--backend neural`)          |
| -------------- | -------------------------- | ------------------------------------ |
| Engine         | pymupdf4llm + PyMuPDF      | marker-pdf (surya models)            |
| Startup        | **Instant** (< 1 s)        | 3–5 min (model download + load)      |
| Speed (CPU)    | **< 0.1 s/page**           | ~5–30 s/page                         |
| GPU required   | **No**                     | No (but 10× faster with GPU)         |
| RAM            | **< 500 MB**               | ~8 GB+                               |
| Tables         | Heuristic (line-based)     | ML detection (high accuracy)         |
| OCR            | Tesseract (if installed)   | surya (state-of-art)                 |
| Images         | Direct from PDF (lossless) | From rendered pages                  |
| Reading order  | Font/position heuristic    | ML ordering model                    |
| Math/equations | Raw text                   | LaTeX (Texify model)                 |
| Accuracy       | Good for digital PDFs      | Best-in-class (95.67 benchmark)      |
| Best for       | Modern/digital PDFs, batch | Scanned manuscripts, complex layouts |

**When to use which:**

- **Plain:** Quick first pass; clean digitally-authored PDFs; scholar laptops with limited resources; batch of hundreds of files.
- **Neural:** Scanned manuscripts; complex multi-column layouts; heritage publications where ML accuracy matters.

---

## Quick Start

### 1. Install

Use **Python 3.10, 3.11, or 3.12**. Recommended steps:

```bash
# See what you have
python3.12 --version   # or python3.11, python3.10

# From your plata project directory
cd /Users/ruvebal/src/plata

# Create venv with that Python (use the one that's 3.10–3.12)
python3.12 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install (plain backend ready immediately)
pip install -e .
```

This installs the **plain backend** (pymupdf4llm + PyMuPDF). No models, no GPU, ready in seconds.

**For neural backend** (marker-pdf + PyTorch + surya models):

```bash
pip install -e '.[neural]'
```

First run of `--backend neural` will download ~3GB of models. Needs 8 GB+ RAM.

**Apple Silicon (M1/M2/M3/M4):** Neural works with MPS acceleration.
**NVIDIA GPU:** For CUDA, install PyTorch from [pytorch.org](https://pytorch.org) first, then `pip install -e '.[neural]'`.
**CPU only:** Neural works, just slower (~5–30 s/page instead of ~0.2 s/page).

### 2. Convert a Single PDF

```bash
# Plain (default — fast, no models)
plata-extract paper.pdf

# Neural (highest accuracy)
plata-extract paper.pdf --backend neural
```

This creates:

```
exports/
└── paper/
    ├── index.md              # Full document as Markdown
    └── images/
        ├── 001.jpeg      # First extracted image
        ├── 002.jpeg
        └── ...
```

### 3. Convert a Directory of PDFs

```bash
plata-extract archive/ -o exports/
```

Processes every `.pdf` in `archive/`, checks integrity first, extracts valid ones:

```
PLATA Extract v0.1.0 [plain]
[1/5] Creadores_Cientificos.pdf (45 pages, 12.3MB)
[1/5] Done: 1.2s, 12340 words, 23 images

[2/5] Album_JRJ.pdf (210 pages, 85.2MB)
[2/5] Done: 4.8s, 4200 words, 156 images

[3/5] corrupted.pdf: SKIP (Corrupted PDF: ...)

[4/5] Epistolario_Lorca.pdf (89 pages, 5.1MB)
[4/5] Done: 2.1s, 28400 words, 3 images

[5/5] protected.pdf: SKIP (Encrypted / password-protected PDF)

Batch complete: 3 succeeded, 2 skipped, 0 failed (8.3s total)
```

### 4. Check PDFs Without Extracting

```bash
plata-extract archive/ --check-only
```

Quickly validates all PDFs (corrupted, encrypted, empty) without extraction:

```
[1/5] Creadores_Cientificos.pdf: OK 45p
[2/5] Album_JRJ.pdf: OK 210p
[3/5] corrupted.pdf: FAIL (Corrupted PDF: ...)
[4/5] Epistolario_Lorca.pdf: OK 89p
[5/5] protected.pdf: FAIL (Encrypted / password-protected PDF)

3 OK, 2 failed out of 5
```

---

## Options

```
plata-extract [OPTIONS] INPUT
```

| Option               | Description                                                     |
| -------------------- | --------------------------------------------------------------- |
| `INPUT`              | PDF file or directory containing PDFs                           |
| `--backend`          | `plain` (default) or `neural`                                   |
| `-o`, `--output-dir` | Output directory (default: `./exports`)                         |
| `--force-ocr`        | Force OCR (surya for neural, Tesseract for plain)               |
| `--max-pages N`      | Process only the first N pages (for testing or low-memory runs) |
| `--check-only`       | Only run integrity checks, skip extraction                      |
| `-v`, `--verbose`    | Debug output                                                    |
| `--version`          | Show version                                                    |

### Neural-only options

| Option          | Description                                                                  |
| --------------- | ---------------------------------------------------------------------------- |
| `--use-llm`     | Use LLM to boost accuracy (tables, math, forms). Requires Ollama or API key. |
| `--llm-service` | LLM service class (e.g. `marker.services.ollama.OllamaService`)              |
| `--format`      | Output format: `markdown` (default), `json`, `html`, `chunks`                |

### Examples

```bash
# Fast extraction (default plain)
plata-extract paper.pdf -o output/

# Neural for highest accuracy
plata-extract paper.pdf --backend neural -o output/

# Scanned manuscript — neural with OCR
plata-extract manuscript_1923.pdf --backend neural --force-ocr

# Scanned doc — plain with Tesseract OCR
plata-extract manuscript_1923.pdf --force-ocr

# Test with first 10 pages only
plata-extract big_book.pdf --max-pages 10

# Neural + LLM enhancement (requires Ollama)
plata-extract paper.pdf --backend neural --use-llm --llm-service marker.services.ollama.OllamaService

# Neural JSON output for downstream processing
plata-extract paper.pdf --backend neural --format json

# Batch — plain processes hundreds of PDFs in minutes
plata-extract archive/ -o exports/
```

---

## Output Structure

For each PDF `FILENAME.pdf`, both backends produce the **identical** layout:

```
output_dir/
└── FILENAME/
    ├── index.md                  # Markdown (text inside document dir)
    └── images/
        ├── 001.jpeg              # Sequentially numbered
        ├── 002.jpeg
        └── ...
```

The Markdown file references images with relative paths (from `index.md`):

```markdown
![](images/001.jpeg)
```

This makes each document a self-contained folder and portable. Downstream consumers (`plata-scholar`, RAG pipelines) work identically regardless of which backend produced the output.

---

## Use from Python

```python
from pathlib import Path
from plata_extract import check_pdf

# Check a PDF
result = check_pdf(Path("paper.pdf"))
print(result.ok, result.page_count)  # True, 45

# Plain extraction (fast, no models)
from plata_extract.extract_plain import PlainExtractor

extractor = PlainExtractor()
result = extractor.extract_file(Path("paper.pdf"), Path("exports/"))
print(result.word_count, result.image_count)  # 12340, 23

# Neural extraction (highest accuracy)
from plata_extract.extract import PlatExtractor

extractor = PlatExtractor()  # loads models once (~3 GB, 3–5 min first time)
result = extractor.extract_file(Path("paper.pdf"), Path("exports/"))
print(result.word_count, result.image_count)  # 12340, 23

# Batch extraction (either backend)
batch = extractor.extract_batch(Path("archive/"), Path("exports/"))
print(batch.succeeded, batch.skipped, batch.failed)  # 11, 1, 0
```

---

## How It Works

### Both backends

1. **Integrity check** — Validates the PDF (exists, not corrupted, not encrypted, has pages) using PyMuPDF.
2. **Extraction** — Converts text to Markdown; extracts images.
3. **Output** — Clean `FILENAME/index.md` + `FILENAME/images/` directory.

### Plain backend (default)

- Uses `pymupdf4llm.to_markdown()` to extract text with font-analysis heuristics for headings, bold, italic, tables, and multi-column layout.
- Images extracted **directly from PDF objects** (lossless for embedded images).
- OCR via Tesseract (if `--force-ocr` and Tesseract is installed).

### Neural backend

- Loads 6 surya models (~3 GB) **once** in `PlatExtractor.__init__`.
- **Layout detection** — Deep learning identifies headings, paragraphs, tables, figures, reading order.
- **OCR** — Scanned pages are OCR'd with surya (better than Tesseract for multi-language).
- **Math/equations** — LaTeX formatting via Texify model.
- **Editor** — T5 model for text cleanup.

---

## Batch: Sequential by Default

**Why not parallel?** Simplicity and reliability for scholars:

- Plain: no model sharing concerns; sequential is fast enough (< 0.1 s/page).
- Neural: models loaded once, shared across all files (no wasted RAM).
- Errors in one file don't affect others.
- Progress is clear: `[3/12] filename.pdf ... done`.
- Memory usage is predictable.

If you need maximum throughput for thousands of PDFs, use marker-pdf's built-in batch directly:

```bash
marker /path/to/pdfs/ --workers 4
```

---

## Requirements

- **Python 3.10+**
- **Plain backend:** PyMuPDF + pymupdf4llm (~30 MB). No GPU, minimal RAM.
- **Neural backend:** + marker-pdf + PyTorch + surya (~3 GB download). 8 GB+ RAM recommended. GPU optional.

---

## Project Context

Part of the **PLATA** project (Proyecto de digitaLización de Archivos con Tecnología interactivA):

- **Residencia de Estudiantes** (Madrid) editorial heritage
- **UDIT** — Universidad de Diseño, Innovación y Tecnología
- **ECSiT Research Group**

Published methodology:

- Conde Melguizo, R. et al. (2025). [Methodology for the digitalization of heritage through interactive technologies and AI](https://doi.org/10.62161/sauc.v11.5739). _SAUC_, 11(3).
- Conde Melguizo, R. & Blanco Marcos, J. (2025). [Digitalization of Cultural Heritage as a Didactic Methodology](https://doi.org/10.25765/sauc.v11.5675). _SAUC_, 11(1).

---

## License

GPL-3.0 (same as marker-pdf).

Model weights (neural backend only): [AI Pubs Open Rail-M license](https://github.com/datalab-to/marker/blob/master/MODEL_LICENSE) — free for research, personal use, and startups under $2M.
