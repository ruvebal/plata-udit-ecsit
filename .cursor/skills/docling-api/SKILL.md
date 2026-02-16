# Skill: Docling + PyMuPDF API

## When to Use
Use this skill when implementing the planned `plain-docling` backend for `plata-extract`, or when extracting layout-aware markdown from PDFs without marker-pdf.

## Core API

### Basic conversion
```python
from docling.document_converter import DocumentConverter

converter = DocumentConverter()
result = converter.convert("/path/to/file.pdf")
markdown = result.document.export_to_markdown()
```

### Notes
- Input can be local file path (preferred for `plata-extract`).
- Output markdown may include image references that need wrapper-level normalization.

## Backend Contract for PLATA Extract

When used inside `plata-extract`, the backend must always enforce:

1. Output folder:
   - `output_dir/FILENAME/index.md`
   - `output_dir/FILENAME/images/`
2. Sequential image naming:
   - `001.jpeg`, `002.jpeg`, ...
3. Markdown refs rewritten to relative paths:
   - `![](images/001.jpeg)`

Docling output must be post-processed to fit this contract.

## Max Pages Strategy

Docling page-limiting options can vary by version. Preferred strategy:

1. Try native Docling page/pipeline options if available.
2. Fallback: use PyMuPDF to create a temporary first-N-pages PDF, then pass that file to Docling.

This keeps `--max-pages` reliable across Docling releases.

## OCR Strategy

For `--force-ocr` in `plain-docling` backend:

- Prefer native Docling OCR options if available in the installed version.
- If unsupported, emit explicit warning and continue (do not silently ignore).

## Error Handling Pattern

Use robust, user-facing errors:

```python
try:
    from docling.document_converter import DocumentConverter
except ImportError as exc:
    raise ImportError(
        "Docling backend dependency missing. Install with:\n"
        "  pip install docling\n"
        "or\n"
        "  pip install -e '.[plain_docling]'"
    ) from exc
```

And during conversion:

```python
try:
    result = converter.convert(str(pdf_path))
except Exception as exc:
    # return ExtractResult(ok=False, error=str(exc), ...)
```

## Recommended Integration Layout

- Backend class: `PlainDoclingExtractor` in `plata_extract/extract_plain_docling.py`
- Methods:
  - `extract_file(...) -> ExtractResult`
  - `extract_batch(...) -> BatchResult`
- CLI dispatch:
  - `--backend plain-docling`

## Version Compatibility

Docling APIs evolve quickly. Keep wrapper code defensive:

- Isolate Docling import/use in one module.
- Prefer feature-detection over strict version assumptions.
- Keep fallback paths for page limiting and OCR behavior.
