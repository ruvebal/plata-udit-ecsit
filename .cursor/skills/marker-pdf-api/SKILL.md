# Skill: marker-pdf Python API

## When to Use
Use this skill when implementing PDF extraction, conversion, or processing using the marker-pdf library.

## marker-pdf Python API Reference

### Core Imports (current marker-pdf API)
```python
from marker.models import load_all_models
from marker.convert import convert_single_pdf
```

### Load Models (expensive — do once)
```python
model_lst = load_all_models(force_load_ocr=False)  # or True to always load OCR model
```
Returns a list of 6 models (texify, layout, order, edit, detection, ocr). ~3GB, 3–5s. Store and reuse.

### Convert a Single PDF
```python
full_text, images, out_metadata = convert_single_pdf(
    "/path/to/file.pdf",
    model_lst,
    max_pages=None,       # optional limit
    langs=None,           # OCR languages (default from settings)
    batch_multiplier=1,
)
# full_text: str — markdown content
# images: dict — {filename: PIL.Image}
# out_metadata: dict — toc, pages, ocr_stats, filetype, etc.
```

### Optional: OCR languages
```python
full_text, images, meta = convert_single_pdf(
    fname, model_lst, langs=["es", "en"]
)
```

### Note on older API
Some docs or forks mention `create_model_dict`, `PdfConverter`, and `text_from_rendered`. The current PyPI marker-pdf uses `load_all_models()` and `convert_single_pdf()` only; there is no `PdfConverter` or `artifact_dict` in the package.

### CLI Commands (reference)
```bash
marker_single /path/to/file.pdf --output_format markdown
marker /path/to/folder --workers 4
marker_single file.pdf --use_llm --force_ocr
```

## Key Facts
- Requires Python 3.10+
- Works on GPU (CUDA), CPU, and MPS (Apple Silicon)
- ~3GB VRAM per worker at peak
- ~0.18s/page throughput on GPU
- Supports: PDF, image, PPTX, DOCX, XLSX, HTML, EPUB (with [full] extra)
- License: GPL-3.0 (code), AI Pubs Open Rail-M (model weights)
- Heuristic accuracy score: 95.67 (best among open-source tools)
