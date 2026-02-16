# Skill: pymupdf4llm Python API

## When to Use
Use this skill when implementing the **plain** (non-neural) PDF extraction backend using pymupdf4llm + PyMuPDF.

## pymupdf4llm Python API Reference

### Core Import
```python
import pymupdf4llm
```

### Basic: Full Document to Markdown
```python
md_text = pymupdf4llm.to_markdown("file.pdf")
# Returns: str — full Markdown content
```

### With Image Extraction (what we use)
```python
md_text = pymupdf4llm.to_markdown(
    doc="file.pdf",            # Path string or fitz.Document
    write_images=True,         # Save images as separate files
    image_path="./images/",    # Directory for extracted images
    image_format="jpeg",       # "jpeg" or "png"
    dpi=150,                   # Image resolution (default 150)
    image_size_limit=0.05,     # Min image size as fraction of page
)
```

### With Page Range
```python
# 0-based page indices
md_text = pymupdf4llm.to_markdown("file.pdf", pages=[0, 1, 2, 3, 4])
# Or use range:
md_text = pymupdf4llm.to_markdown("file.pdf", pages=list(range(10)))
```

### With OCR (requires Tesseract installed)
```python
md_text = pymupdf4llm.to_markdown(
    "file.pdf",
    use_ocr=True,
    ocr_language="spa+eng",    # Tesseract language codes
)
```

### Chunked Output (list of dicts per page)
```python
chunks = pymupdf4llm.to_markdown("file.pdf", page_chunks=True)
# Returns: list[dict] with keys like "metadata", "text", etc.
```

### Table Strategy
```python
md_text = pymupdf4llm.to_markdown(
    "file.pdf",
    table_strategy="lines_strict",  # Default; also "lines", "text", "explicit"
)
```

### All Key Parameters
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `doc` | str / fitz.Document | required | PDF file path or open document |
| `pages` | list[int] | None (all) | 0-based page indices |
| `write_images` | bool | False | Save images as files |
| `image_path` | str | "" | Directory for saved images |
| `image_format` | str | "png" | Image format (jpeg/png) |
| `dpi` | int | 150 | Image resolution |
| `image_size_limit` | float | 0.05 | Min image size as page fraction |
| `embed_images` | bool | False | Base64 embed images in Markdown |
| `page_chunks` | bool | False | Return list[dict] per page |
| `use_ocr` | bool | False | Enable Tesseract OCR |
| `ocr_language` | str | "eng" | Tesseract language code(s) |
| `table_strategy` | str | "lines_strict" | Table detection method |

## Key Facts
- **No models to download.** Pure rule-based + heuristic extraction.
- **No GPU.** Runs on CPU in < 0.1 s/page.
- **Tables:** Detected via line analysis (heuristic, not ML).
- **Images:** Extracted directly from PDF objects (lossless for embedded images).
- **Multi-column:** Handled via font/position heuristics.
- **Bold/italic/code:** Detected via font analysis.
- **License:** AGPL-3.0 (pymupdf4llm inherits from PyMuPDF).
- **Install:** `pip install pymupdf4llm` (lightweight, ~10 MB + PyMuPDF).

## Integration Notes for PLATA Extract
- pymupdf4llm saves images with auto-generated names. Our `PlainExtractor.extract_file()` must **renumber** them to `001.jpeg`, `002.jpeg`, etc., matching the neural backend's convention.
- Image references in the returned Markdown use the `image_path` directory. After renumbering, rewrite refs to `images/NNN.jpeg`.
- `page_chunks=True` can be used for the `--format chunks` option if we add it to the plain backend.
