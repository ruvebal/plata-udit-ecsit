# Implementation Plan: LLM Post-Processing for Plain / Plain-Docling Backends

**Author:** Rubén Vega Balbás PhD (ECSIT - UDIT)  
**Status:** Proposed  
**Date:** 2026-02-26

---

## Problem

Currently only the **neural** backend (`marker-pdf`) can use an LLM (Ollama) for extraction refinement. The **plain** and **plain-docling** backends are faster and more reliable (no MPS crashes), but their output can suffer from:

- Broken reading order (multi-column, sidebars)
- Missed or mangled headings / structure
- Poor table formatting (heuristic-based)
- OCR artifacts and garbled characters (scanned docs)
- Missing semantic structure (e.g. footnotes, captions, block quotes)

An LLM post-processing step can fix most of these **without needing surya/torch/MPS at all**.

---

## Goal

Add a **`--postprocess-llm`** step that runs **after** any backend's extraction and refines the output markdown using Ollama (local, no API key, vision optional). The step must be:

1. **Backend-agnostic** — works with plain, plain-docling, and even neural output.
2. **Optional** — off by default; opt-in via `--postprocess-llm`.
3. **Non-destructive** — original extraction is saved; post-processed version replaces `index.md` (original kept as `index.raw.md`).
4. **Chunked** — processes markdown in page/section chunks to fit context windows.
5. **Image-aware** — can optionally send page images alongside text for vision-model corrections.

---

## How marker-pdf uses Ollama (vs this plan)

**Marker uses Ollama inline, per-block, with structured output.** It does **not** post-process full markdown.

| Aspect | Marker (neural + `--use-llm`) | Our post-process (`--postprocess-llm`) |
|--------|-------------------------------|----------------------------------------|
| **When** | During extraction, after layout/OCR | After extraction, on the final `index.md` |
| **Granularity** | One LLM call per **block** (table, section header, page) | One LLM call per **chunk** of markdown (multi-paragraph / multi-page) |
| **Input to LLM** | Block-level HTML/JSON + **cropped block image** | Chunk of **markdown text** + optional **full page image** |
| **Output** | **Structured** (Pydantic schema: `TableSchema`, `SectionHeaderSchema`, `PageSchema`) — parseable JSON | **Free-form** corrected markdown (no schema) |
| **Ollama API** | Same `/api/generate` with `format: <schema>` for JSON | Same `/api/generate`; we ask for raw markdown in the prompt |
| **Processors** | `LLMTableProcessor`, `LLMSectionHeaderProcessor`, `LLMTableMergeProcessor`, `LLMPageCorrectionProcessor` | Single post-processor over the whole document in chunks |

So: **marker fixes individual blocks (tables, headings) with strict schemas; we fix full-document markdown (order, structure, OCR) with natural-language prompts.** Both use Ollama at the same “level” (HTTP to Ollama); the difference is **when** (inline vs post) and **what** (block JSON vs chunk markdown).

---

## Summaries and hard data markup at this Ollama level

**Yes — we can generate summaries and hard markup in this same post-process step.** We control the prompt and the number of passes.

### Summaries

- **Per-chunk summary:** Ask Ollama to return, for each chunk, a short summary (e.g. 1–3 sentences). We concatenate or store them (e.g. `SUMMARY.md` or YAML frontmatter).
- **Per-document summary:** After all chunks are refined, send the full refined markdown (or a compressed version) in one call and ask for a single document summary. Write to `SUMMARY.md` or `index.md` frontmatter.
- **Benefits:** RAG (retrieve by summary), catalog cards, quick previews without re-reading the full text.

**Implementation:** Optional flag `--postprocess-summary`. If set, after refinement we run one extra Ollama call: “Summarize the following document in 3–5 sentences (language of the document).” Save result to `doc_dir/SUMMARY.md` or as `summary:` in frontmatter.

### Hard data markup

- **Structured annotations** we can ask Ollama to add in this same process:
  - **Semantic tags:** e.g. `<letter date="1923-05-01" author="Huidobro">...</letter>`, `<footnote id="1">...</footnote>`.
  - **YAML frontmatter:** `title:`, `author:`, `date:`, `language:`, `document_type: letter|article|book`.
  - **Inline metadata:** e.g. `## meta: author=... ; date=...` for section-level metadata.
- **Benefits:**
  - Downstream parsing (XPath, CSS selectors, custom parsers).
  - RAG and search (filter by author, date, document type).
  - Scholarly metadata (citations, provenance) and consistent structure across the corpus.
  - No need for a separate “markup” tool; one Ollama pass can do “correct + annotate”.

**Implementation:** Optional flag `--postprocess-markup` with values such as `none` (default), `frontmatter`, `semantic-tags`. Prompts are tuned to request only the chosen markup; we validate that image refs and main text are preserved.

### Summary of benefits at this Ollama level

| Feature | Benefit |
|---------|--------|
| **Refinement** (core) | Fix reading order, headings, tables, OCR; keep plain/plain-docling fast and stable. |
| **Summaries** | RAG, catalogs, previews; one extra Ollama call per document. |
| **Hard markup** | Parsable structure, metadata, scholarly use; same Ollama pass or one extra with a “markup only” prompt. |
| **Backend-agnostic** | Same behaviour for plain, plain-docling, and neural output. |
| **No PyTorch** | Avoids MPS; only Ollama (Metal) runs on GPU. |

---

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐
│  Backend     │     │  index.md    │     │  LLM Post-Processor  │
│  (plain /    │────>│  (raw)       │────>│  (Ollama, chunked)   │
│  docling /   │     │              │     │                      │
│  neural)     │     │  images/     │     │  Sends: md chunk     │
└──────────────┘     │  001.jpeg    │     │  + page image (opt)  │
                     │  002.jpeg    │     │                      │
                     └──────────────┘     │  Returns: refined md │
                                          └──────────┬───────────┘
                                                     │
                                                     ▼
                                          ┌──────────────────────┐
                                          │  index.md (refined)  │
                                          │  index.raw.md (orig) │
                                          └──────────────────────┘
```

### New module: `plata_extract/llm_postprocess.py`

Single-responsibility module. Does **not** import marker-pdf, surya, or torch.

Dependencies: `requests`, `Pillow` (already installed), `PyMuPDF` (already installed).

---

## Processing Strategy

### 1. Chunk the markdown

Split `index.md` into chunks by page breaks (form feed `\f`, `---` separators, or by heading level). Each chunk should be **≤ 3000 tokens** (~12 KB of text) to leave room for the prompt and response in Ollama's context window.

### 2. For each chunk, build a prompt

**Text-only mode** (fast, works with any model):

```
You are a document restoration assistant for heritage PDF digitalization.
Below is a markdown chunk extracted from a PDF. Fix ONLY these issues:
- Reading order (if text from multiple columns is interleaved)
- Heading levels (ensure proper hierarchy: #, ##, ###)
- Table formatting (fix broken markdown tables)
- OCR artifacts (obvious garbled characters, broken words)
- Remove duplicate content from page headers/footers

Do NOT add new content. Do NOT summarize. Do NOT translate.
Preserve all image references exactly as they are.
Return ONLY the corrected markdown, nothing else.

---
{chunk}
```

**Vision mode** (slower, higher accuracy — uses page image):

Same prompt, but also attach the rendered page image so the vision model can cross-reference the visual layout against the extracted text. Useful for:
- Verifying reading order against visual column layout
- Identifying text that was missed by the extractor
- Fixing table structure by "seeing" the original table

### 3. Reassemble

Concatenate refined chunks in order. Save as `index.md`. Keep original as `index.raw.md`.

### 4. Logging

Log per-chunk: tokens used, time, whether vision was used. Log total: chunks processed, total time, total tokens.

---

## CLI Changes

### New flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--postprocess-llm` | bool | `False` | Enable LLM post-processing after extraction. |
| `--postprocess-model` | str | `llama3.2-vision` | Ollama model to use for post-processing. |
| `--postprocess-vision` | bool | `False` | Send page images alongside text chunks (requires vision model). |
| `--postprocess-summary` | bool | `False` | After refinement, generate a short summary; write to SUMMARY.md or frontmatter. |
| `--postprocess-markup` | str | `none` | Add hard markup: `none`, `frontmatter` (YAML), or `semantic-tags` (e.g. `<letter date="...">`). |
| `--ollama-url` | str | `http://localhost:11434` | Ollama server URL (shared with `--llm-service` for neural). |

### Interaction with existing flags

- `--postprocess-llm` works with **all** backends: `plain`, `plain-docling`, `neural`.
- `--postprocess-llm` + `--backend neural --use-llm`: both run (marker's inline LLM refinement, then post-process). Useful but expensive; warn user.
- `--postprocess-llm` without Ollama running: fail fast with clear error.

### Examples

```bash
# Plain + LLM post-process (fastest reliable combo)
plata-extract paper.pdf --postprocess-llm

# Plain-docling + LLM post-process with vision
plata-extract paper.pdf --backend plain-docling --postprocess-llm --postprocess-vision

# Batch with post-processing
plata-extract archive/ -o exports/ --postprocess-llm

# Custom model
plata-extract paper.pdf --postprocess-llm --postprocess-model llama3.1:8b
```

---

## Module Design: `plata_extract/llm_postprocess.py`

```python
# Public API

class LLMPostProcessor:
    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        model: str = "llama3.2-vision",
        use_vision: bool = False,
        timeout: int = 300,
    ): ...

    def postprocess_file(
        self,
        md_path: Path,          # path to index.md
        pdf_path: Path,         # original PDF (for rendering page images)
        max_pages: int | None,
    ) -> PostProcessResult: ...

    def postprocess_batch(
        self,
        output_dir: Path,       # exports/ root — finds all index.md files
        source_dir: Path,       # original PDFs directory
    ) -> list[PostProcessResult]: ...


@dataclass
class PostProcessResult:
    ok: bool
    md_path: Path
    raw_md_path: Path | None     # index.raw.md (backup of original)
    chunks_processed: int
    chunks_failed: int
    total_tokens: int
    elapsed_seconds: float
    error: str | None = None
```

### Internal functions

```python
def _chunk_markdown(text: str, max_chars: int = 12000) -> list[str]:
    """Split markdown into chunks by page breaks or headings."""

def _render_page_image(pdf_path: Path, page_num: int) -> PIL.Image.Image | None:
    """Render a single page as an image using PyMuPDF (for vision mode)."""

def _build_prompt(chunk: str, is_vision: bool = False) -> str:
    """Build the system + user prompt for the LLM."""

def _call_ollama(
    url: str, model: str, prompt: str,
    image: PIL.Image.Image | None, timeout: int,
) -> str:
    """Call Ollama /api/generate and return the response text."""
```

---

## Integration Points

### In `cli.py`

After `extractor.extract_file()` or `extractor.extract_batch()` returns, if `--postprocess-llm` is set:

```python
if args.postprocess_llm and result.ok and result.output_md:
    from plata_extract.llm_postprocess import LLMPostProcessor
    pp = LLMPostProcessor(
        ollama_url=args.ollama_url,
        model=args.postprocess_model,
        use_vision=args.postprocess_vision,
    )
    pp_result = pp.postprocess_file(result.output_md, pdf_path, args.max_pages)
    # Log post-processing stats
```

### In extractors (no changes needed)

The extractors produce `index.md` as before. Post-processing is a **separate step** that operates on the output files. This keeps the extractors clean and the feature fully optional.

---

## Prompt Engineering Notes

### Heritage documents (PLATA context)

The prompt should be tuned for:
- **Spanish** and **multilingual** content (letters, poetry, academic text)
- **Historical typography** (ligatures, old orthography — do NOT "correct" historical spelling)
- **Epistolary format** (dates, salutations, signatures, postscripts)
- **Footnotes and endnotes** (common in academic editions)
- **Page headers/footers** (running titles, page numbers — strip or mark)

### Prompt variants

| Variant | When | Notes |
|---------|------|-------|
| `general` | Default | General-purpose markdown cleanup |
| `heritage_es` | Heritage Spanish docs | Preserve historical spelling, handle epistolary format |
| `academic` | Academic papers | Preserve citations, equations, references |

Store prompts in `plata_extract/prompts/` as text files. Load by name. Default: `general`.

---

## Performance Estimates

Based on `llama3.2-vision` on M4 Max (128 GB):

| Metric | Text-only | Vision |
|--------|-----------|--------|
| Per chunk (3K tokens) | ~2-5s | ~10-30s |
| 386-page PDF (~100 chunks) | ~5-8 min | ~20-50 min |
| Ollama VRAM | ~7 GB | ~7 GB |
| CPU/GPU | Ollama on MPS (Metal) | Ollama on MPS (Metal) |

Compare with:
- Plain extraction: ~30s total (no LLM)
- Neural extraction: ~9 hours (with MPS crashes)
- **Plain + LLM post-process: ~5-8 min** (best time/quality tradeoff)

---

## Advantages Over Neural + `--use-llm`

| | Neural + `--use-llm` | Plain + `--postprocess-llm` |
|---|---|---|
| **Reliability** | MPS crashes (surya/torch) | No PyTorch at all; Ollama runs its own Metal stack |
| **Speed** | ~9 hours (386 pages) | ~5-8 min (plain extraction + LLM post-process) |
| **Dependencies** | marker-pdf + surya + torch + Ollama | pymupdf4llm + Ollama only |
| **GPU usage** | PyTorch MPS (crashy) + Ollama Metal | Ollama Metal only (stable) |
| **LLM scope** | Refines individual blocks (tables, math) during extraction | Refines full-page/section markdown after extraction |
| **OCR** | surya (ML-based, high accuracy) | Tesseract (if `--force-ocr`) or PDF-embedded text |
| **Best for** | Scanned manuscripts needing ML OCR | Digital PDFs, heritage editions with clean text |

---

## Phased Delivery

### Phase 1: Core (MVP)

- [ ] `llm_postprocess.py` with `LLMPostProcessor` class
- [ ] Text-only mode (no vision)
- [ ] `_chunk_markdown()` splitter
- [ ] `_call_ollama()` with timeout and error handling
- [ ] CLI flags: `--postprocess-llm`, `--postprocess-model`, `--ollama-url`
- [ ] Backup original as `index.raw.md`
- [ ] Works with all three backends
- [ ] Logging: per-chunk and total stats

### Phase 2: Vision mode

- [ ] `--postprocess-vision` flag
- [ ] `_render_page_image()` using PyMuPDF
- [ ] Map chunks to page numbers for image attachment
- [ ] Base64 image encoding for Ollama API

### Phase 3: Prompt variants

- [ ] `plata_extract/prompts/` directory with `.txt` prompt templates
- [ ] `--postprocess-prompt` flag to select variant
- [ ] Heritage Spanish (`heritage_es`) prompt tuned for PLATA documents
- [ ] Academic prompt for papers/articles

### Phase 4: Summaries and hard markup

- [ ] `--postprocess-summary`: one extra Ollama call after refinement; write `SUMMARY.md` or frontmatter `summary:`.
- [ ] `--postprocess-markup`: prompt variants for `frontmatter` (title, author, date, language) and `semantic-tags` (letters, footnotes); validate image refs preserved.

### Phase 5: Smart chunking

- [ ] Detect page boundaries from PDF metadata (not just markdown heuristics)
- [ ] Chunk by semantic sections (chapters, letters in epistolary docs)
- [ ] Overlap chunks slightly to preserve cross-page context
- [ ] Parallel Ollama calls (if `OLLAMA_NUM_PARALLEL > 1`)

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| LLM hallucinates content | High | Strict prompt ("do NOT add content"); diff original vs. refined; optionally validate word count delta |
| LLM removes valid content | High | Keep `index.raw.md`; log chunk-level diffs; alert if >10% content lost |
| Ollama timeout on large chunks | Medium | Chunk size limit (12 KB); 300s timeout; retry once |
| Historical spelling "corrected" | Medium | Heritage prompt explicitly preserves original spelling |
| Image refs broken | Medium | Prompt says "preserve all image references exactly"; post-validate `![](images/...)` refs |
| Ollama not running | Low | Fail fast with clear message: "Ollama not reachable at {url}" |

---

## Testing Strategy

1. **Unit tests** for `_chunk_markdown()`: various markdown structures, page breaks, headings.
2. **Integration test**: extract a small PDF with plain, then post-process; verify `index.raw.md` exists and `index.md` is valid markdown.
3. **Regression test**: compare post-processed output against known-good reference for a test PDF.
4. **Vision test**: verify page images are correctly rendered and sent to Ollama.
5. **Error handling**: Ollama down, Ollama timeout, invalid model name, empty markdown.

---

## Summary

**Plain + `--postprocess-llm`** gives the best speed/quality/reliability tradeoff for PLATA heritage documents:

- **~5-8 min** instead of ~9 hours (neural)
- **No MPS crashes** (no surya/torch; Ollama's Metal stack is stable)
- **No PyTorch dependency** for plain backend
- **Ollama runs on MPS (Metal)** for fast inference — completely separate from PyTorch's buggy MPS
- **Backend-agnostic** — improves any extraction, including neural output
