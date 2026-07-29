# Implementation Plan: Enriched Extraction — Surya + Ollama for All Backends

**Author:** Rubén Vega Balbás PhD — ruvebal@crea-comm.net (ECSIT - UDIT)
**Status:** Proposed
**Date:** 2026-02-27
**Supersedes / Extends:** `IMPLEMENTATION-PLAN-LLM-POSTPROCESS.md` (Phase 4 absorbed and expanded here)
**Scope:** `plata-udit-ecsit` — the extractor library, not ARKADIA

---

## 1. Executive Summary

This plan upgrades PLATA Extract from a **text extractor** to a **meta-semantic extraction engine** by adding two orthogonal enrichment layers that work with **all three backends** (plain, plain-docling, neural):

1. **Surya Layout Analysis** (`--enrich-layout`): Standalone surya models (no marker-pdf) provide ML-quality layout labels, reading order, table recognition, and bounding boxes to plain/plain-docling backends. This bridges the accuracy gap without triggering marker-pdf/MPS instability.

2. **Ollama Enrichment** (`--enrich-llm`): Post-extraction LLM pass that corrects, annotates, and structures the output — generating YAML frontmatter, semantic entity markup, summaries, and accurate indexing (page numbers, footnotes, section refs).

The extractor remains a **library + CLI** that produces maximally rich self-contained document folders. Vectorization, graph generation, and RAG stay in ARKADIA. The boundary is: **PLATA Extract produces the richest possible structured Markdown; ARKADIA consumes it.**

---

## 2. The Questions Answered

### Q: Can Ollama improve extraction in plain and plain-docling backends?

**Yes.** The existing `IMPLEMENTATION-PLAN-LLM-POSTPROCESS.md` designs this. This plan extends it with:
- YAML frontmatter generation (title, author, date, language, document type, keywords)
- Semantic entity markup (names, places, technical terms) in Markdown/HTML
- Accurate indexing correction (page numbers, footnotes, cross-references)
- Per-document summary generation

### Q: Can Ollama markup hard data (names, locations, technical terms)?

**Yes.** Two approaches, both implemented here:

| Approach | Format | Best for |
|----------|--------|----------|
| **Inline Markdown** | `**Einstein**{.person}`, `*Madrid*{.place}` | Downstream parsers, RAG metadata |
| **HTML semantic tags** | `<entity type="person">Einstein</entity>` | XPath/CSS selectors, XSLT, scholarly tools |
| **YAML frontmatter** | `entities: [{name: Einstein, type: person, pages: [4,7]}]` | Catalog, search, ChromaDB metadata |

### Q: Can surya be used in plain and plain-docling extraction too?

**Yes, and it's valuable far beyond OCR.** Surya provides 5 standalone models:

| Model | What it does | Use in plain/docling | Benefit beyond OCR |
|-------|-------------|---------------------|-------------------|
| **Layout** | Classifies regions as `Section-header`, `Footnote`, `Table`, `Caption`, `Page-header`, `Page-footer`, `Formula`, `Picture`, `Text`, etc. | Annotate pymupdf4llm/Docling output with ML-quality labels | **Reading order, footnote detection, header/footer stripping, caption linking** |
| **Reading Order** | Assigns position index to each layout block | Reorder multi-column text that pymupdf4llm misreads | **Fixes the #1 plain backend weakness** |
| **Table Recognition** | Detects rows, columns, cells with bboxes | Replace heuristic table detection with ML tables | **Accurate table structure for academic papers** |
| **Text Detection** | Line-level bbox detection | Map text chunks to exact PDF coordinates | **Tri-anchor A for ariadna (bbox per chunk)** |
| **OCR** | Character recognition from images | Scanned pages where Tesseract fails | **90+ language OCR, math recognition** |

### Q: Shall we add vector/graph generation to plata-extract or keep in ARKADIA?

**Keep in ARKADIA.** Rationale:

| Concern | Why plata-extract should NOT do it | Why ARKADIA should |
|---------|-----------------------------------|-------------------|
| Single responsibility | plata-extract = extraction + enrichment (no vector store, no graph) | ARKADIA = ingestion + RAG + API |
| Dependencies | Adding ChromaDB + embedding pipelines bloats the extractor | ARKADIA already depends on them |
| Infra needs | PLATA optionally needs **Ollama** (neural `--use-llm`, planned `--enrich-llm`); no ChromaDB/graph server | ARKADIA needs ChromaDB, embeddings, graph, web API |
| Library reuse | Other projects can `import plata_extract` without ChromaDB/graph deps | ARKADIA is the RAG consumer |
| GPL license | plata-extract is GPL-3.0 (marker-pdf); adding chromadb (Apache) is fine but adds coupling | ARKADIA can have its own license |

**Ollama is already an optional infra dependency of PLATA Extract.** The README documents it (see “Using Ollama locally”): neural backend with `--use-llm` and (once implemented) `--enrich-llm` both require a running Ollama server. So PLATA *does* depend on Ollama when using those features — but **not** on ChromaDB, embedding pipelines, or graph generation; those stay in ARKADIA. Summary: **PLATA = extract + optional Ollama (refinement/metadata); ARKADIA = chunk → embed → ChromaDB → graph.**

**The output boundary:** plata-extract outputs `index.md` + `metadata.yaml` + `images/` + `layout.json`. ARKADIA reads these, chunks, embeds (using its own Ollama/embedding setup), vectorizes, and builds the knowledge graph.

### Q: Do Ollama and Surya improve extraction, or the result afterwards?

**In plain and plain-docling: they improve the result *after* extraction.** The pipeline is:

1. **Extract** (pymupdf4llm or Docling) → raw `index.md` + `images/`.
2. **Optionally enrich** → Surya on page images → `layout.json`; Ollama on markdown → refined `index.md` + `metadata.yaml`.

So for those backends, Surya and Ollama do **not** replace or sit inside the extractor; they run on the extractor’s output. (The **neural** backend is different: marker-pdf uses Surya and optionally Ollama *during* extraction, block-by-block.)

**Is “improve afterwards” the better approach?** For plain/plain-docling, **yes**, in most cases:

| Reason | Benefit |
|--------|--------|
| **Stability** | Extraction stays lightweight (no PyTorch in the hot path for plain/docling). Surya/Ollama run only when opted in; if they fail, you still have `index.raw.md`. |
| **Reproducibility** | You keep the raw extraction. You can diff “before vs after” enrichment and re-run only enrichment with another model or prompt. |
| **Resource flexibility** | Extract on a weak machine (no GPU), enrich later on a machine with Ollama/surya. Or extract 1000 PDFs and enrich only the subset that need it. |
| **Separation of concerns** | “Get text/structure from PDF” vs “correct, annotate, add metadata” are separate steps. Easier to test, tune, and swap models. |

**When inline (during extraction) is better:** for **heavily scanned or image-only** pages, the raw text from plain/docling may be too wrong for post-hoc refinement. In that case, neural backend (Surya OCR + marker-pdf’s inline LLM) can be the right choice — at the cost of speed and MPS stability. So: **digital or decent-quality PDFs → extract then enrich. Poor scans → consider neural with inline LLM.**

### Q: Why don’t we implement enrichment block-by-block (like neural) for plain/plain-docling?

**We could**, but the current plan chooses **chunk-level** (page/section) over **block-level** for plain/plain-docling on purpose.

**What block-by-block would require:** Run Surya layout → get labelled blocks with bboxes → for each block, get text (e.g. PyMuPDF `get_text("dict")` by bbox, or clip Docling output to region) → send one LLM call per block with (block text + block image crop). Reassemble. That gives one-Ollama-call-per-table, per-footnote, per-heading — like marker-pdf’s `LLMTableProcessor`, `LLMSectionHeaderProcessor`, etc.

**Why we don’t do that (yet):**

| Factor | Chunk-level (current plan) | Block-by-block |
|--------|---------------------------|----------------|
| **Block–text alignment** | Not needed. We have full markdown; split by page/heading. | Hard. Plain/docling don’t expose block boundaries; we’d need bbox→text mapping (PyMuPDF regions or Docling block API) and robust matching. |
| **LLM call volume** | One call per chunk (~1–4 pages). 100-page doc ≈ 25–100 calls. | One call per block. 100-page doc ≈ hundreds of calls (tables, footnotes, headers, paragraphs). |
| **Implementation cost** | Low: chunk markdown, prompt, reassemble. | High: surya layout → align blocks to extracted text → crop images per block → per-block prompts and schema parsing. |
| **Quality gain** | Good for reading order, headings, light table fixes, metadata. | Best for tables and math (each block gets dedicated vision+text). |

**When block-by-block is worth it:** For documents that are **block-heavy** (many tables, equations, footnotes) and where chunk-level refinement is not enough, the right move is to use the **neural backend** (marker-pdf already does block-by-block with Surya + optional Ollama). Adding a full block-by-block path for plain/docling would largely reimplement that pipeline with a different text source (plain/Docling instead of marker’s OCR), which is a large effort for a narrow band of use cases.

**Possible future option:** A **hybrid** mode: run Surya layout → use `layout.json` to **split** the plain/docling markdown into logical segments (e.g. by Section-header blocks) and call Ollama per *segment* (each segment may contain several blocks). That’s still chunk-level, but with Surya-guided boundaries instead of fixed page breaks. That could be a Phase 5+ improvement without going full block-by-block.

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              PLATA EXTRACT PIPELINE                              │
│                                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌──────────────┐    ┌────────────────┐   │
│  │  PDF Input   │───>│  Integrity  │───>│   Backend    │───>│  Enrichment    │   │
│  │              │    │  Check      │    │  Extraction  │    │  (optional)    │   │
│  └─────────────┘    │  (check.py) │    │              │    │                │   │
│                     └─────────────┘    │  plain /     │    │  ┌───────────┐ │   │
│                                        │  plain-docl. │    │  │ Surya     │ │   │
│                                        │  / neural    │    │  │ Layout    │ │   │
│                                        │              │    │  │ (opt-in)  │ │   │
│                                        │  ↓           │    │  └───────────┘ │   │
│                                        │  index.md    │    │  ┌───────────┐ │   │
│                                        │  images/     │    │  │ Ollama    │ │   │
│                                        └──────────────┘    │  │ Enrich    │ │   │
│                                                            │  │ (opt-in)  │ │   │
│                                                            │  └───────────┘ │   │
│                                                            └───────┬────────┘   │
│                                                                    │             │
│                                                                    ▼             │
│                                                         ┌──────────────────┐    │
│                                                         │  Final Output    │    │
│                                                         │                  │    │
│                                                         │  index.md        │    │
│                                                         │  index.raw.md    │    │
│                                                         │  metadata.yaml   │    │
│                                                         │  layout.json     │    │
│                                                         │  images/         │    │
│                                                         │  extract.log     │    │
│                                                         └──────────────────┘    │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
                                         │
                                         │ (py import / filesystem)
                                         ▼
                              ┌──────────────────────┐
                              │  ARKADIA (consumer)   │
                              │                       │
                              │  Chunk index.md       │
                              │  + metadata.yaml      │
                              │  + layout.json bboxes │
                              │  → Embed (Ollama)     │
                              │  → Store (ChromaDB)   │
                              │  → Graph (ariadna)    │
                              └──────────────────────┘
```

---

## 4. Output Contract (Enhanced)

Each extracted document produces:

```
output_dir/FILENAME/
├── index.md                    # Enriched Markdown (or raw if no enrichment)
├── index.raw.md                # Original extraction (before Ollama, if enriched)
├── metadata.yaml               # YAML frontmatter extracted as standalone file
├── layout.json                 # Surya layout analysis (bboxes, labels, reading order)
├── images/
│   ├── 001.jpeg
│   ├── 002.jpeg
│   └── ...
├── extract.log                 # Human-readable log
└── extract.events.jsonl        # Structured event log
```

### `metadata.yaml` schema

```yaml
# Auto-generated by plata-extract --enrich-llm
plata_extract_version: "0.3.0"
backend: "plain-docling"
enrichment:
  surya_layout: true
  ollama_model: "llama3.2"
  ollama_vision: false

document:
  title: "Epistolario de Huidobro a Gerardo Diego"
  authors:
    - name: "Vicente Huidobro"
      role: "author"
    - name: "Gerardo Diego"
      role: "recipient"
  date: "1921-1935"
  language: "es"
  document_type: "epistolary"  # letter | article | book | proceedings | album
  pages: 37
  word_count: 12340
  image_count: 23

summary: >
  Colección de cartas entre Vicente Huidobro y Gerardo Diego
  durante el periodo 1921-1935, abarcando temas de creacionismo
  y la vanguardia literaria hispanoamericana.

keywords:
  - creacionismo
  - vanguardia
  - poesía

entities:
  persons:
    - name: "Vicente Huidobro"
      pages: [1, 3, 5, 7, 12, 15, 21, 28, 33]
    - name: "Gerardo Diego"
      pages: [1, 2, 4, 8, 14, 19, 25, 30, 36]
    - name: "Juan Larrea"
      pages: [6, 11, 22]
  places:
    - name: "Madrid"
      pages: [2, 8, 14]
    - name: "París"
      pages: [3, 7, 15, 28]
  dates:
    - value: "1921-05-12"
      pages: [1]
    - value: "1923-11-03"
      pages: [5]
  technical_terms:
    - term: "creacionismo"
      pages: [3, 7, 12, 21]
    - term: "ultraísmo"
      pages: [4, 9]
```

### `layout.json` schema

```json
{
  "surya_version": "0.17.1",
  "pages": [
    {
      "page": 0,
      "image_bbox": [0, 0, 612, 792],
      "blocks": [
        {
          "bbox": [72, 100, 540, 130],
          "polygon": [[72,100],[540,100],[540,130],[72,130]],
          "label": "Section-header",
          "position": 0,
          "confidence": 0.95
        },
        {
          "bbox": [72, 140, 540, 500],
          "label": "Text",
          "position": 1,
          "confidence": 0.92
        },
        {
          "bbox": [72, 720, 540, 750],
          "label": "Footnote",
          "position": 3,
          "confidence": 0.88
        }
      ]
    }
  ]
}
```

This `layout.json` is the **bridge to ariadna's tri-anchor A** — ARKADIA reads it to attach bounding boxes to each chunk during vectorization.

---

## 5. Surya Enrichment Layer (`--enrich-layout`)

### 5.1 What It Does

Runs surya's **layout + reading order** models on page images (rendered via PyMuPDF) to produce `layout.json` with per-page, per-block:
- Semantic label (`Section-header`, `Footnote`, `Table`, `Caption`, `Page-header`, `Page-footer`, `Text`, `Formula`, `Picture`, etc.)
- Bounding box (polygon + axis-aligned rect)
- Reading order position
- Confidence score

Optionally also runs:
- **Table recognition** (`--enrich-tables`): Row/column cell structure for detected tables
- **Text detection** (`--enrich-text-bboxes`): Line-level bboxes for text regions
- **OCR** (`--enrich-ocr`): Surya OCR as alternative to Tesseract for `--force-ocr`

### 5.2 Benefits for Plain/Plain-Docling

| Current weakness | Surya fix |
|-----------------|-----------|
| Multi-column reading order broken | Surya `position` field reorders blocks correctly |
| No footnote detection | Surya labels `Footnote` blocks → Ollama can then format them |
| Page headers/footers mixed into text | Surya labels `Page-header` / `Page-footer` → strip or mark |
| Heuristic table detection | Surya table recognition replaces line-based heuristic |
| No caption linking | Surya labels `Caption` near `Picture`/`Figure` → link in metadata |
| No formula detection | Surya labels `Formula` → Ollama can attempt LaTeX conversion |
| No bounding boxes in output | `layout.json` provides bboxes per block (tri-anchor A) |

### 5.3 Python API

```python
from surya.foundation import FoundationPredictor
from surya.layout import LayoutPredictor
from surya.settings import settings

# Load once, use for all pages
foundation = FoundationPredictor(checkpoint=settings.LAYOUT_MODEL_CHECKPOINT)
layout_predictor = LayoutPredictor(foundation)

# Per page: render image with PyMuPDF, then predict
import fitz
from PIL import Image

doc = fitz.open(pdf_path)
page = doc[0]
pix = page.get_pixmap(dpi=150)
img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

layout_predictions = layout_predictor([img])
# → list of dicts with bboxes, labels, positions
```

### 5.4 Integration Strategy

**Surya runs AFTER extraction, BEFORE Ollama enrichment.** The layout metadata improves Ollama's prompts:

```
Extract → index.md + images/
  ↓
Surya → layout.json (labels, order, bboxes)
  ↓
Ollama → enriched index.md + metadata.yaml
         (uses layout labels to guide correction and annotation)
```

Ollama's prompt can include: *"The following block was classified by layout analysis as a `Footnote` at the bottom of page 3. Format it as a markdown footnote."*

### 5.5 New Module: `plata_extract/surya_enrich.py`

```python
@dataclass
class LayoutBlock:
    bbox: tuple[float, float, float, float]
    polygon: list[list[float]]
    label: str           # Section-header, Footnote, Table, Text, ...
    position: int        # reading order
    confidence: float
    top_k: dict[str, float] | None = None

@dataclass
class PageLayout:
    page: int
    image_bbox: tuple[float, float, float, float]
    blocks: list[LayoutBlock]

@dataclass
class LayoutResult:
    ok: bool
    pages: list[PageLayout]
    elapsed_seconds: float
    error: str | None = None

class SuryaEnricher:
    """Standalone surya layout analysis (no marker-pdf dependency)."""

    def __init__(self, device: str | None = None):
        # Loads surya layout model once (~1.5 GB)
        ...

    def analyze_layout(
        self, pdf_path: Path, max_pages: int | None = None
    ) -> LayoutResult:
        """Run layout + reading order on all pages."""
        ...

    def analyze_tables(
        self, pdf_path: Path, page_layouts: list[PageLayout]
    ) -> dict:
        """Run table recognition on pages that have Table blocks."""
        ...

    def save_layout_json(
        self, result: LayoutResult, output_path: Path
    ) -> None:
        """Write layout.json to the document output directory."""
        ...
```

### 5.6 Dependencies

```toml
[project.optional-dependencies]
surya = [
    "surya-ocr",     # brings torch, but NOT marker-pdf
]
```

Surya **without marker-pdf** is a smaller dependency tree. The MPS stability issues are surya's own torch usage, but layout analysis is lighter than full marker extraction and typically more stable than the full pipeline.

---

## 6. Ollama Enrichment Layer (`--enrich-llm`)

Extends `IMPLEMENTATION-PLAN-LLM-POSTPROCESS.md` with three new capabilities beyond basic refinement.

### 6.1 Enrichment Modes (Composable)

| Mode | Flag | What it produces | Ollama passes |
|------|------|-----------------|---------------|
| **Refine** | `--enrich-llm` | Corrected reading order, headings, tables, OCR artifacts | 1 per chunk |
| **Metadata** | `--enrich-metadata` | `metadata.yaml` with title, author, date, language, type, keywords | 1 per document |
| **Entities** | `--enrich-entities` | Entity annotations in metadata.yaml + optional inline markup | 1 per chunk |
| **Summary** | `--enrich-summary` | `summary` field in metadata.yaml | 1 per document |
| **Index** | `--enrich-index` | Corrected page numbers, footnote refs, cross-references in markdown | 1 per chunk |
| **All** | `--enrich-all` | All of the above | 3-4 per chunk + 2 per document |

### 6.2 YAML Frontmatter Generation (`--enrich-metadata`)

**Prompt strategy:** After extraction (and optional Surya layout), send the first ~4000 tokens of the document + the last ~1000 tokens to Ollama with:

```
You are a Digital Humanities metadata cataloger.
Analyze this document excerpt and return ONLY valid YAML with these fields:

title: (document title, in original language)
authors: (list of {name, role} — author, editor, recipient, etc.)
date: (date or date range, ISO 8601 if possible)
language: (ISO 639-1 code)
document_type: (one of: letter, article, book, proceedings, album, manuscript, report)
keywords: (3-8 domain-specific keywords in original language)

Do NOT invent data. If a field cannot be determined, use null.
Return ONLY the YAML block, no explanation.

---
DOCUMENT START:
{first_chunk}
...
DOCUMENT END:
{last_chunk}
```

### 6.3 Entity Markup (`--enrich-entities`)

**Two output modes:**

**a) Metadata-only (default):** Entities listed in `metadata.yaml` with page numbers.

**b) Inline markup** (`--enrich-entities inline`): Entities marked in `index.md` using Markdown attribute syntax or HTML. Choose format via `--enrich-entities inline=pandoc` (default) or `inline=html`.

```markdown
<!-- Pandoc attribute syntax (default): preserves readability, works with Pandoc/LaTeX and most static site generators -->
**Vicente Huidobro**{.entity .person} escribió desde **París**{.entity .place}
sobre el **creacionismo**{.entity .term} en **1921**{.entity .date}.

<!-- HTML mode (inline=html): better for XPath/CSS selectors, XSLT, and XML-aware pipelines; some renderers may strip unknown tags. Optional id/ref for KG entity resolution. -->
<entity type="person">Vicente Huidobro</entity> escribió desde
<entity type="place">París</entity> sobre el
<entity type="term">creacionismo</entity> en <entity type="date">1921</entity>.
<!-- Example with optional id for KG: <entity type="person" id="person-0">Vicente Huidobro</entity> -->
```

**Trade-offs:**

| Aspect | Pandoc `{.entity .type}` | HTML `<entity type="...">` |
|--------|---------------------------|----------------------------|
| **Readability** | Plain Markdown + attributes; bold often used for span | Custom tags; may render as inline or block depending on CSS |
| **Tooling** | Pandoc, many SSGs; attribute-aware processors | XPath, CSS, XSLT; XML parsers |
| **Escaping** | Entity text with `}` must be escaped or wrapped differently | Entity text with `>`, `"` must be escaped (e.g. HTML entities) |
| **Types** | Same four: `person`, `place`, `date`, `term` (lowercase, aligned with NER JSON keys) |

**Implementation note:** When emitting inline markup, match each NER span to the extracted text (character/word offsets or fuzzy match) and insert the chosen syntax. Prefer a single canonical type set (`person` | `place` | `date` | `term`) for both formats.

#### Perspective: downstream knowledge-graph extraction

If the enriched output will feed a **knowledge graph** (RDF, property graph, or graph DB), the following design choices improve later KG ETL:

1. **Identifiers for entity resolution**  
   Surface form alone ("Vicente Huidobro", "París") is ambiguous and does not map 1:1 to graph nodes. Prefer markup that can carry a **stable local id** so the KG pipeline can link mentions to canonical nodes (e.g. Wikidata Q-ids, internal URIs).  
   - **Recommendation:** Support an optional `id` or `ref` attribute in HTML mode, e.g. `<entity type="person" id="huidobro-v">Vicente Huidobro</entity>`. The `id` can be a slug derived from the metadata entity list (e.g. `persons[0]` → `person-0`) or from a future reconciliation step. Pandoc attributes can carry the same via `{.entity .person #ref-person-0}` if the downstream parser reads identifier attributes.

2. **Provenance**  
   KG triples need provenance (which document, which page or span).  
   - **Recommendation:** Keep `<!-- page: N -->` markers and ensure the KG ETL can associate each `<entity>` (or Pandoc span) with the current page and document id. Emit document and page in metadata or in a sidecar (e.g. JSON-LD `provenance` or reification) so every extracted triple can be annotated with `source`, `page`, and optionally `chunk` or character range.

3. **Relation extraction**  
   This stage only marks **entity spans**, not relations. KGs require subject–predicate–object triples.  
   - **Recommendation:** Treat relation extraction as a separate step (e.g. Ollama or a relation model over sentence/chunk context). Document that co-occurrence of entities in the same sentence/chunk is the primary signal for that step. Optionally, reserve a future extension for relation hints in markup (e.g. `<relation from="ref-person-0" type="wrote_from" to="ref-place-paris"/>`) if needed; not required for v1.

4. **Normalization and types**  
   Dates and places should eventually link to normalized values (ISO dates, gazetteer IDs).  
   - **Recommendation:** Keep `metadata.yaml` as the source of normalized dates (`value: "1921-05-12"`) and optional place/term identifiers. The KG ETL can join inline mentions to metadata entities by type + surface form or by `id`/`ref`, then attach normalized values and (if applicable) ontology classes (e.g. `schema:Person`, `gn:Feature`) in the graph.

5. **Format choice for KG pipelines**  
   - **HTML mode** is usually better for KG ETL: easy to add `id`/`ref`, trivial XPath/SAX parsing to emit (subject, object, type, provenance), and no ambiguity with Markdown syntax.  
   - **Pandoc mode** remains fine for human-readable docs and pipelines that parse attributes; ensure the KG extractor can read span boundaries and optional identifier attributes if used.

**Summary for KG:** Prefer `--enrich-entities inline=html` when the primary consumer is a KG pipeline; add optional `id`/`ref` on entities; keep metadata.yaml as the authority for normalized values and page-level entity lists; and design the next stage (relation extraction) to consume entity spans + page/chunk context and provenance.

**Prompt for entity extraction (per chunk):**

```
You are a Named Entity Recognition (NER) specialist for heritage documents.
Identify ALL of the following in the text below:

- PERSON: People mentioned (authors, recipients, historical figures)
- PLACE: Geographic locations (cities, countries, buildings, institutions)
- DATE: Dates and time periods
- TERM: Domain-specific technical terms, movements, concepts

Return ONLY valid JSON:
{"persons": ["name1", "name2"], "places": [...], "dates": [...], "terms": [...]}

Do NOT include common words. Only named entities and specific terms.

---
{chunk}
```

### 6.4 Accurate Indexing (`--enrich-index`)

Uses Surya layout data (if available) to:

1. **Page number correction:** Surya detects `Page-header` / `Page-footer` blocks → extract actual printed page numbers → map to PDF page indices → insert `<!-- page: 42 -->` markers in markdown.

2. **Footnote linking:** Surya detects `Footnote` blocks → Ollama matches superscript refs in text to footnote bodies → converts to markdown `[^1]` / `[^1]: ...` syntax.

3. **Cross-reference repair:** Ollama identifies broken "see page X" / "cf. Chapter Y" references and verifies them against extracted page/section structure.

**Prompt (per page, with layout context):**

```
You are a document indexing specialist.
This page has the following layout blocks (from ML analysis):
{layout_blocks_json}

The extracted text for this page is:
{page_text}

Tasks:
1. If a Page-header or Page-footer contains a page number, extract it.
2. If Footnote blocks exist, link them to superscript references in the text
   using markdown footnote syntax: [^N] in text, [^N]: content at bottom.
3. Preserve ALL original text. Do NOT add or remove content.

Return the corrected markdown for this page only.
```

### 6.5 Summary Generation (`--enrich-summary`)

After all chunks are refined, one final Ollama call:

```
Summarize the following document in 3-5 sentences.
Write in the same language as the document.
Focus on: subject matter, key people, time period, and significance.

---
{full_text_or_compressed}
```

Result stored in `metadata.yaml` as `summary:` field.

---

## 7. CLI Changes

### New flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--enrich-layout` | bool | `False` | Run Surya layout analysis (produces `layout.json`) |
| `--enrich-tables` | bool | `False` | Run Surya table recognition (requires `--enrich-layout`) |
| `--enrich-text-bboxes` | bool | `False` | Run Surya text detection for line-level bboxes |
| `--enrich-ocr` | bool | `False` | Use Surya OCR instead of Tesseract for `--force-ocr` |
| `--enrich-llm` | bool | `False` | Run Ollama refinement on extracted markdown |
| `--enrich-metadata` | bool | `False` | Generate `metadata.yaml` via Ollama |
| `--enrich-entities` | str | `none` | Entity extraction: `none`, `metadata` (YAML only), `inline` (markup in md) |
| `--enrich-summary` | bool | `False` | Generate document summary in metadata |
| `--enrich-index` | bool | `False` | Correct page numbers, footnotes, cross-refs |
| `--enrich-all` | bool | `False` | Enable all enrichment (surya + ollama) |
| `--enrich-model` | str | `llama3.2` | Ollama model for text enrichment |
| `--enrich-vision-model` | str | `llama3.2-vision` | Ollama model for vision enrichment |
| `--enrich-vision` | bool | `False` | Send page images to Ollama for cross-reference |
| `--ollama-url` | str | `http://localhost:11434` | Ollama server URL |
| `--entity-format` | str | `pandoc` | Inline entity format: `pandoc` (attrs) or `html` (tags) |

### Convenience aliases

```bash
# Quick enrichment (layout + LLM refinement + metadata)
plata-extract paper.pdf --enrich-all

# Just layout analysis (fast, no Ollama needed)
plata-extract paper.pdf --enrich-layout

# Scholar-grade: layout + full LLM enrichment
plata-extract paper.pdf --backend plain-docling --enrich-all --enrich-vision

# Entity extraction for RAG metadata
plata-extract archive/ --enrich-metadata --enrich-entities metadata

# Surya OCR instead of Tesseract
plata-extract scanned.pdf --force-ocr --enrich-ocr
```

---

## 8. Performance Estimates

Based on M4 Max (128 GB), `llama3.2` text / `llama3.2-vision`:

| Operation | Time (40-page PDF) | GPU/RAM |
|-----------|-------------------|---------|
| Plain extraction | ~3s | CPU, < 500 MB |
| Plain-Docling extraction | ~15s | CPU, ~1 GB |
| Surya layout analysis | ~30-60s | MPS/CPU, ~2 GB VRAM |
| Ollama refinement (text) | ~2-4 min | MPS (Ollama Metal), ~7 GB |
| Ollama refinement (vision) | ~8-15 min | MPS (Ollama Metal), ~7 GB |
| Ollama metadata + entities | ~30s | Same |
| **Total: plain-docling + all enrichment** | **~5-20 min** | ~9 GB total |

Compare: Neural extraction alone = ~30 min to hours, with MPS crash risk.

---

## 9. Phased Delivery

### Phase 1: Surya Layout (standalone, no Ollama)

- [ ] `surya_enrich.py` with `SuryaEnricher` class
- [ ] Layout analysis → `layout.json`
- [ ] CLI: `--enrich-layout`
- [ ] Optional `[surya]` extra in pyproject.toml
- [ ] Integration: run after extraction, before any Ollama step
- [ ] Logging: surya timing in extract.events.jsonl

### Phase 2: Ollama Refinement (from existing plan)

- [ ] `llm_enrich.py` with `LLMEnricher` class (renamed from `llm_postprocess.py`)
- [ ] Text-only refinement mode
- [ ] Layout-aware prompts (use `layout.json` labels when available)
- [ ] CLI: `--enrich-llm`, `--enrich-model`, `--ollama-url`
- [ ] Backup as `index.raw.md`

### Phase 3: Metadata and Entities

- [ ] `--enrich-metadata` → `metadata.yaml` generation
- [ ] `--enrich-entities metadata` → entities in YAML
- [ ] `--enrich-entities inline` → markup in `index.md`
- [ ] `--entity-format` for pandoc vs html output
- [ ] Validation: image refs preserved, no content loss

### Phase 4: Index, Summary, Vision

- [ ] `--enrich-index` with footnote linking and page number extraction
- [ ] `--enrich-summary` → summary in metadata.yaml
- [ ] `--enrich-vision` → page images sent to Ollama
- [ ] `--enrich-all` convenience flag

### Phase 5: Surya Table Recognition + OCR

- [ ] `--enrich-tables` → structured table data in layout.json
- [ ] `--enrich-ocr` → surya OCR as Tesseract replacement
- [ ] `--enrich-text-bboxes` → line-level bboxes for fine-grained tri-anchoring

### Phase 6: ARKADIA Integration Optimizations

- [ ] `--output-format chunks` for plain/plain-docling (semantic chunking with metadata)
- [ ] Streaming/callback API for progress reporting
- [ ] `metadata.yaml` auto-generated even without `--enrich-llm` (basic stats only)
- [ ] `layout.json` consumed by ARKADIA's chunker for bbox-aware splitting

---

## 10. Boundary: PLATA Extract vs ARKADIA

```
┌──────────────────────────────┐         ┌──────────────────────────────┐
│       PLATA EXTRACT          │         │         ARKADIA              │
│                              │         │                              │
│  PDF → Markdown + Images     │         │  Markdown → Chunks           │
│  + metadata.yaml             │  ───→   │  + Ollama embeddings         │
│  + layout.json (bboxes)      │         │  + ChromaDB storage          │
│  + entity annotations        │         │  + Knowledge Graph (ariadna) │
│                              │         │  + FastAPI + React frontend  │
│  Pure extraction + enrichment│         │  RAG + API + UI              │
│  No network deps (optional)  │         │  Requires infra (deviac)     │
│  CLI + Python library        │         │  Web application             │
│  GPL-3.0                     │         │  Apache 2.0                  │
└──────────────────────────────┘         └──────────────────────────────┘
```

**What stays in plata-extract:**
- PDF parsing (pymupdf4llm, Docling, marker-pdf)
- Layout analysis (surya standalone)
- LLM enrichment (Ollama: correction, metadata, entities, indexing)
- Structured output (Markdown, YAML, JSON, images)

**What goes in ARKADIA:**
- Semantic chunking (Markdown → sized chunks with overlap)
- Embedding generation (Ollama nomic-embed-text)
- Vector storage (ChromaDB)
- Knowledge graph construction (ariadna tri-anchoring)
- RAG retrieval + generation
- Module/Topic/Document CRUD
- Web API + frontend

---

## 11. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Surya MPS instability (same as neural) | Medium | Layout analysis is lighter than full extraction; offer `--torch-device cpu` fallback |
| Ollama hallucinating entity names | High | Strict prompts + validation pass: cross-check entities against original text |
| metadata.yaml schema drift | Medium | Version field in YAML; Pydantic model for validation |
| Inline entity markup breaks markdown | Medium | Post-validation: verify `![](images/...)` refs preserved; diff original vs enriched |
| Two large optional deps (surya + Ollama) | Medium | Both are opt-in extras; base extraction works without either |
| Enrichment too slow for batch | Medium | `--enrich-layout` alone is fast (~1s/page); Ollama can be skipped for batch, run later |

---

## 12. Testing Strategy

1. **Unit tests:** YAML schema validation, entity JSON parsing, layout.json serialization
2. **Integration:** Extract + enrich a test PDF → verify all output files exist and parse correctly
3. **Regression:** Compare enriched vs raw extraction — enriched must contain all original content
4. **Entity accuracy:** Run on PLATA heritage PDFs with known entity lists → precision/recall
5. **Layout accuracy:** Compare surya layout labels against manually annotated pages
6. **Batch stability:** Run enriched extraction on full PLATA corpus without crashes
7. **ARKADIA consumption:** Verify ARKADIA's chunker can read `metadata.yaml` + `layout.json` + `index.md`

---

## 13. Summary

PLATA Extract evolves from a PDF-to-Markdown converter into a **meta-semantic extraction engine**:

| Capability | Before | After |
|-----------|--------|-------|
| Text extraction | 3 backends | 3 backends (unchanged) |
| Layout awareness | Docling/neural only | **Surya standalone for all backends** |
| Reading order | Heuristic (plain) | **ML-quality for all backends** |
| Table detection | Heuristic/ML | **Surya ML for all backends** |
| Footnote detection | None | **Surya labels + Ollama linking** |
| Entity extraction | None | **Ollama NER with inline markup** |
| Document metadata | None | **Ollama-generated YAML frontmatter** |
| Summary | None | **Ollama-generated summary** |
| Page indexing | None | **Layout-aware page/footnote correction** |
| Bounding boxes | Neural only | **Surya for all backends (layout.json)** |
| Output for RAG | Markdown only | **Markdown + YAML + JSON + images** |

All enrichment is **opt-in** and **composable**. The base extraction (fast, no GPU, no network) remains the default. Scholars choose their enrichment level based on accuracy needs and available compute.

The extractor plays alone as a CLI tool, and imported into ARKADIA as the first stage of the RAG pipeline. Both paths consume the same enriched output.
