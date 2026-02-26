# Skill: marker-pdf Python API

**Environment:** This project uses Python 3.10–3.12 only (`requires-python = ">=3.10,<3.13"`). Install with `python3 -m pip install -e '.[neural]'`.

## When to Use
Use this skill when implementing PDF extraction, conversion, or processing using the marker-pdf library.

## marker-pdf 1.10.x API Reference

### Core Imports (marker-pdf 1.10+)
```python
from marker.models import create_model_dict
from marker.converters.pdf import PdfConverter
from marker.output import text_from_rendered
```

### Load models (expensive — do once)
```python
artifact_dict = create_model_dict()  # optional: device=..., dtype=..., attention_implementation=...
```
Returns a dict of layout, recognition, table_rec, detection, ocr_error predictors. ~3GB, 3–5s. Pass as `artifact_dict` to `PdfConverter`.

### Convert a single PDF
```python
config = {
    "force_ocr": False,       # True to force OCR on all pages
    "use_llm": False,
    "pdftext_workers": 1,
    "page_range": None,       # e.g. list(range(10)) for first 10 pages
}
converter = PdfConverter(
    artifact_dict=artifact_dict,
    config=config,
    renderer="marker.renderers.markdown.MarkdownRenderer",  # or JSONRenderer, HTMLRenderer, ChunkRenderer
    llm_service=None,  # Use "plata_extract.ollama_service.OllamaService" for Ollama (our Ollama 0.17+ compatible service; marker's built-in has a KeyError bug)
)
rendered = converter("/path/to/file.pdf")
# rendered is a pydantic BaseModel (MarkdownOutput, JSONOutput, etc.)
```

### Get text and images from rendered output
```python
text, ext, images = text_from_rendered(rendered)
# text: str (markdown, html, or json string)
# ext: "md" | "html" | "json"
# images: dict[str, PIL.Image] — only for MarkdownOutput/HTMLOutput
```

### Renderer class names
- Markdown: `"marker.renderers.markdown.MarkdownRenderer"`
- JSON: `"marker.renderers.json.JSONRenderer"`
- HTML: `"marker.renderers.html.HTMLRenderer"`
- Chunks: `"marker.renderers.chunk.ChunkRenderer"`

### CLI (reference)
```bash
marker_single /path/to/file.pdf --output_format markdown
marker /path/to/folder --workers 4
marker_single file.pdf --use_llm --force_ocr
```

## When neural extraction fails (plata-extract)

Some PDFs trigger bugs inside marker-pdf/surya or torch (`index … out of bounds`, `torch.AcceleratorError`). In plata-extract we catch these, log the traceback, and append a hint. **What to do:**

1. **Sanitize the PDF first:** `plata-extract file.pdf --backend neural --sanitize-for-neural` (caps page dimensions).
2. **Use plain backend** for that file: `plata-extract file.pdf` (default).
3. **Limit pages:** `plata-extract file.pdf --backend neural --max-pages N` to stop before the failing page.
4. **Report upstream:** [datalab-to/marker](https://github.com/datalab-to/marker/issues) with full traceback (and PDF if possible).

## Ollama LLM integration

marker-pdf's `OllamaService` has a bug: it uses `response_data["prompt_eval_count"]` (hard key lookup) which raises `KeyError` on Ollama >= 0.17 with vision models. All valid responses are silently discarded.

**Use `plata_extract.ollama_service.OllamaService`** (Ollama 0.17+ compatible):
```bash
plata-extract paper.pdf --backend neural --use-llm \
    --llm-service plata_extract.ollama_service.OllamaService
```

Our `OllamaService` uses `.get()` with defaults, preserving the actual LLM output.

See project `docs/TROUBLESHOOTING.md` for full text.

## Key Facts
- Requires Python 3.10–3.12 (3.13+ not supported by PyTorch/marker wheels)
- Works on GPU (CUDA), CPU, and MPS (Apple Silicon)
- ~3GB VRAM per worker at peak
- Supports: PDF, image, PPTX, DOCX, XLSX, HTML, EPUB (with [full] extra)
- License: GPL-3.0 (code), AI Pubs Open Rail-M (model weights)
- Heuristic accuracy score: 95.67 (best among open-source tools)
