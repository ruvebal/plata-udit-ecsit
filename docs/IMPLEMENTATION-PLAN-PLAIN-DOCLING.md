# PLATA Extract: Plain Backend (Docling + PyMuPDF) — Implementation Plan

**Project:** PDF extraction for Digital Humanities
**Scope:** `/Users/ruvebal/src/plata`
**Parent project:** PLATA (digitaLización de Archivos con Tecnología interactivA)
**Status:** Planned (not implemented yet)
**Related plans:**

- [IMPLEMENTATION-PLAN.md](./IMPLEMENTATION-PLAN.md) — neural backend (marker-pdf)
- [IMPLEMENTATION-PLAN-PLAIN.md](./IMPLEMENTATION-PLAN-PLAIN.md) — current plain backend path

**Environment:** Python 3.10–3.12. Docling is a base dependency (`python3 -m pip install -e .`). For neural backend failures (marker/surya), see [TROUBLESHOOTING.md](./TROUBLESHOOTING.md).

---

## 1. Objective

Add a **Docling-based plain backend** that keeps the same CLI/user flow and output contract as existing backends, but uses:

- **Docling** for layout-conscious extraction (text structure, tables, reading order)
- **PyMuPDF** for PDF integrity checks and image handling support

This backend is intended as a **non-neural / low-resource ingestion path** for scholar workflows where fast startup and acceptable layout fidelity are preferred over full neural accuracy.

---

## 2. Scope and Naming

To avoid breaking current behavior, introduce a new backend name:

- `--backend plain-docling` (new, planned)

Current backends remain:

- `--backend plain` (current implementation)
- `--backend neural` (marker-pdf)

After validation, we may decide to make `plain-docling` the default and deprecate old `plain`.

---

## 3. Architecture

### 3.1 Shared Pipeline Contract

All backends must follow:

```
PDF -> check.py -> backend.extract_file() -> output_dir/FILENAME/index.md + images/
```

Shared dataclasses and behavior:

- `ExtractResult`
- `BatchResult`
- Sequential per-file processing with robust per-file failure handling

### 3.2 New Module

Create:

`plata_extract/extract_plain_docling.py`

Class:

`PlainDoclingExtractor`

Public methods (same shape as other backends):

- `extract_file(pdf_path: Path, output_dir: Path, max_pages: Optional[int] = None) -> ExtractResult`
- `extract_batch(input_dir: Path, output_dir: Path, check_only: bool = False, max_pages: Optional[int] = None) -> BatchResult`

---

## 4. Extraction Strategy (Docling + PyMuPDF)

### 4.1 Core Convert Step (Docling)

Use Docling’s `DocumentConverter` API to convert PDF input to markdown:

```python
from docling.document_converter import DocumentConverter

converter = DocumentConverter()
result = converter.convert(str(pdf_path))
markdown = result.document.export_to_markdown()
```

### 4.2 Page Limiting (`max_pages`)

Docling does not always expose `max_pages` in the same API path across versions. Implementation should support one of:

1. Use Docling pipeline/page options when available.
2. Fallback: pre-split PDF with PyMuPDF to temporary first-N-pages PDF, then feed that to Docling.

This fallback keeps behavior deterministic across Docling releases.

### 4.3 Image Folder Contract

Docling markdown/image naming can vary by version. We enforce PLATA contract:

- store images under `output_dir/FILENAME/images/`
- rename sequentially to `001.jpeg`, `002.jpeg`, ...
- rewrite markdown image refs to `images/NNN.jpeg`

If Docling returns no extracted images, keep markdown and omit `images/` unless needed.

### 4.4 OCR Behavior

For `--force-ocr` with `plain-docling`:

- Prefer Docling OCR options if available in installed version
- If unavailable, warn clearly and continue without OCR
- Never fail silently

---

## 5. CLI Changes

### 5.1 Backend Choices

Extend CLI backend choices:

- `plain`
- `plain-docling` (new)
- `neural`

### 5.2 Backend Dispatch

Dispatch by backend:

- `plain` -> `PlainExtractor`
- `plain-docling` -> `PlainDoclingExtractor`
- `neural` -> `PlatExtractor`

### 5.3 Flag Compatibility

`--use-llm`, `--llm-service`, and neural output formats remain neural-only.

For `plain-docling`, ignore unsupported flags with explicit warnings.

---

## 6. Dependencies

### 6.1 pyproject.toml target state

Add optional extra:

```toml
[project.optional-dependencies]
plain_docling = [
    "docling",
]
```

Keep existing:

- base deps for existing plain backend
- `neural` extra for marker-pdf

Rationale: Docling should be opt-in until stability is validated in this repo.

---

## 7. Reliability and Error Handling

Implementation requirements:

- Wrap Docling convert call in try/except with actionable message.
- Detect missing Docling dependency and provide exact install command.
- Keep partial-file failures isolated in batch mode.
- Include elapsed time and error in `ExtractResult`.

---

## 8. Testing Plan

### 8.1 Functional smoke tests

1. Single PDF:
   - `plata-extract sample.pdf --backend plain-docling`
2. Limited pages:
   - `plata-extract sample.pdf --backend plain-docling --max-pages 10`
3. Batch folder:
   - `plata-extract folder/ --backend plain-docling`
4. Check-only path:
   - `plata-extract folder/ --check-only --backend plain-docling`

### 8.2 Contract validation

For each output:

- `FILENAME/index.md` exists
- all refs are relative `images/*.jpeg`
- image files are sequentially named
- no absolute local paths leaked in markdown

### 8.3 Real corpus test (PLATA)

Run on:

`/Users/ruvebal/projects/ruvebal/scholar/udit/research/plata/Pddf2Json/PlataPDFExporter/ALBUM_Juan_Ramon_Jimenez.pdf`

Capture:

- total time
- words extracted
- image count
- backend-specific warnings/errors

---

## 9. Rollout Plan

1. Add plan + rules + skill updates (this step).
2. Implement `extract_plain_docling.py` and CLI dispatch.
3. Install `docling` extra and run smoke tests.
4. Run full ALBUM_Juan_Ramon_Jimenez test and record results in verification docs.
5. Decide whether to keep both plain backends or deprecate old `plain`.

---

## 10. Risks and Mitigations

| Risk                                     | Impact                | Mitigation                                                |
| ---------------------------------------- | --------------------- | --------------------------------------------------------- |
| Docling API changes by version           | Breaks implementation | Add compatibility layer + fallback max-pages approach     |
| Image export behavior differs by version | Broken image refs     | Force sequential renaming and markdown rewrite in wrapper |
| OCR option mismatch                      | User confusion        | Warn clearly when `--force-ocr` is unsupported            |
| Too many backend choices                 | UX complexity         | Keep defaults stable; document usage matrix in README     |

---

## 11. Relation to PLATA Scholar

`plain-docling` remains an **ingestion backend** producing the same downstream-compatible output:

```
PDF -> plata-extract (plain/plain-docling/neural) -> Markdown + Images -> plata-scholar
```

Downstream systems remain backend-agnostic because file contract is unchanged.
