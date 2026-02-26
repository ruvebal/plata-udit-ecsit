# Troubleshooting — PLATA Extract

## Neural backend (marker-pdf / surya) errors

Some PDFs trigger bugs **inside** marker-pdf, surya, or PyTorch (e.g. `index … out of bounds`, `torch.AcceleratorError` in the vision encoder). These are **not** bugs in plata-extract; the CLI catches them and prints a suggested workaround.

### What you’ll see

- **Single file:** The run fails with a message like:
  - `index … is out of bounds: 0, range 0 to 2`
  - `torch.AcceleratorError: index … is out of bounds …`
  - Followed by: *(Known surya/torch issue on some PDFs. Try --sanitize-for-neural, --backend plain, or --max-pages N.)`
- **Batch:** That file is counted as **failed**; the batch continues with the next file.

### What to do

1. **Try sanitizing the PDF** (normalizes page dimensions before neural; can avoid some surya/torch failures):
   ```bash
   plata-extract path/to/file.pdf --backend neural --sanitize-for-neural
   ```
   This rewrites the PDF so no page exceeds a maximum dimension (default 3500 pt on the longest side), then runs neural on the normalized copy. Output is still named after the original file.

2. **Use the plain backend** (no marker/surya):
   ```bash
   plata-extract path/to/file.pdf
   ```
   Default is `--backend plain`; no models, no surya.

3. **Limit pages** so neural stops before the bad page:
   ```bash
   plata-extract path/to/file.pdf --backend neural --max-pages 100
   ```
   If it fails at e.g. 178/270, try `--max-pages 175`. Use plain for the rest or run again with a different range. If it fails at **0/N** (first batch), try a small `--max-pages 10` to see if a subset works.

4. **If you already used `--sanitize-for-neural` and it still failed:** try **without** it. Sanitization helps some PDFs but can change page layout in a way that triggers the bug on others; the original file may work.

5. **Force CPU instead of MPS** (Apple Silicon stability workaround):
   ```bash
   plata-extract path/to/file.pdf --backend neural --torch-device cpu
   ```
   This sets `TORCH_DEVICE=cpu` for the run so surya/marker avoid the MPS backend entirely (slower, but typically avoids `torch.AcceleratorError`).

6. **Report upstream** (optional): Full traceback and, if possible, the PDF or a minimal repro. [datalab-to/marker](https://github.com/datalab-to/marker/issues) or surya-ocr.

### Why it happens

The failure is usually in surya’s layout or vision encoder on **specific pages** (e.g. unusual layout, very large page, or a batch edge case). Fixing it requires changes in marker-pdf or surya, not in plata-extract.

### What `--sanitize-for-neural` does

Before running the neural backend, the PDF is re-rendered with PyMuPDF so that **no page’s longest side exceeds 3500 points** (scale down only). The result is written to a temporary PDF and neural runs on that; the temp file is deleted afterward. Output filenames and paths are still based on the **original** PDF. This can avoid surya/torch errors triggered by very large or odd-sized pages.

---

## Ollama: `Ollama inference failed: 'prompt_eval_count'`

### Symptom

When using `--use-llm` with `marker.services.ollama.OllamaService`, every LLM call logs:

```
[WARNING] marker: Ollama inference failed: 'prompt_eval_count'
```

The LLM progress bar advances, but extraction quality is **not improved** (LLM output is silently discarded).

### Root cause

marker-pdf’s `OllamaService` accesses `response_data["prompt_eval_count"]` with a hard key lookup (line 61–63 of `marker/services/ollama.py`). Ollama ≥ 0.17 with vision models (`llama3.2-vision`) sometimes omits `prompt_eval_count` from the response JSON. This raises a `KeyError`, which is caught by marker’s broad `except`, logged as a warning, and the **perfectly valid response is returned as `{}`** — effectively nullifying every LLM call.

Ollama itself is working fine (all requests return HTTP 200).

### Fix

Use the **Ollama service** bundled with plata-extract:

```bash
plata-extract paper.pdf --backend neural --use-llm \
    --llm-service plata_extract.ollama_service.OllamaService
```

`OllamaService` (plata_extract) is a drop-in replacement that uses `.get()` with defaults for the optional token-count fields, so the actual LLM response is preserved.

### Alternative workarounds

- Run without `--use-llm` (neural alone is still high-accuracy).
- Wait for a marker-pdf release that fixes the `KeyError` and switch back to `marker.services.ollama.OllamaService`.

---

## Ollama: 500 Internal Server Error / “aborting completion request due to client closing the connection”

### Symptom

Ollama logs show:

```
aborting completion request due to client closing the connection
[GIN] ... | 500 | 30.001...s | POST "/api/generate"
```

Plata-extract logs: `Ollama inference failed: 500 Server Error...` and `LLM did not return a valid response`. **Extraction still finishes** and produces output.

### Root cause

The **client** (marker-pdf) was using a **30 second timeout** for each `/api/generate` request. Vision models (e.g. `llama3.2-vision`) often need longer. When the client hits the timeout it closes the connection; Ollama then aborts the request and returns 500. Marker-pdf treats the failed LLM call as “no LLM result” and **continues without LLM refinement** for that block, so the run completes with neural output only where the LLM timed out.

### Fix

Our `plata_extract.ollama_service.OllamaService` now uses a **300 second (5 minute)** default timeout per request instead of the base 30s. Use it so requests don’t time out on slow vision calls:

```bash
plata-extract paper.pdf --backend neural --use-llm \
    --llm-service plata_extract.ollama_service.OllamaService
```

If you still see timeouts on a busy or slow machine, you can increase the timeout by configuring marker’s LLM service (see marker-pdf docs) or by using a smaller/faster model.

### Why extraction “succeeds” despite 500s

Marker-pdf is built to **degrade gracefully**: when an LLM call fails (timeout, 500, or invalid response), it skips the LLM step for that block and keeps the non-LLM pipeline result. So you get a full extraction; only the LLM-enhanced parts (e.g. table/math refinement) are missing where the call failed.

---

## Use generated logs to diagnose failures

Each run now generates:

- `extract.log` (human-readable) in each document output folder.
- `extract.events.jsonl` (machine-readable events) in each document output folder.
- Batch runs also generate run-level logs in `output_dir/_runs/<RUN_ID>/`.

### Fast triage workflow

1. Open `extract.log` first and confirm:
   - exact command and backend
   - check result (page count, file size)
   - final error and suggested action
2. If needed, open `extract.events.jsonl` and filter `event_type == "error"` to inspect structured diagnostics.
3. Compare run-level metrics across runs:
   - success/failure counts
   - `throughput_pages_per_sec`
   - LLM errors/timeouts (when `--use-llm`)

### Common patterns

- `torch.AcceleratorError` + `index ... out of bounds` in events/logs:
  - Use `--backend plain`, `--max-pages`, or `TORCH_DEVICE=cpu`.
- Ollama `500` or timeout in logs/events:
  - Use `plata_extract.ollama_service.OllamaService` and/or a faster model.
- Very low word count / empty output:
  - Verify PDF integrity check and inspect source document type (scanned vs digital).

---

## Other issues

- **“marker-pdf not installed” / ImportError:** Use Python 3.10–3.12 and install the neural extra: `python3 -m pip install -e '.[neural]'`. See [README](../README.md#quick-start).
- **Plain backend:** No special troubleshooting; if a PDF is valid (not corrupted, not encrypted), plain extraction should run. For OCR you need Tesseract installed if you use `--force-ocr`.
