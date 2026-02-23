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
   If it fails at e.g. 178/270, try `--max-pages 175`. Use plain for the rest or run again with a different range.

4. **Report upstream** (optional): Full traceback and, if possible, the PDF or a minimal repro. [datalab-to/marker](https://github.com/datalab-to/marker/issues) or surya-ocr.

### Why it happens

The failure is usually in surya’s layout or vision encoder on **specific pages** (e.g. unusual layout, very large page, or a batch edge case). Fixing it requires changes in marker-pdf or surya, not in plata-extract.

### What `--sanitize-for-neural` does

Before running the neural backend, the PDF is re-rendered with PyMuPDF so that **no page’s longest side exceeds 3500 points** (scale down only). The result is written to a temporary PDF and neural runs on that; the temp file is deleted afterward. Output filenames and paths are still based on the **original** PDF. This can avoid surya/torch errors triggered by very large or odd-sized pages.

---

## Other issues

- **“marker-pdf not installed” / ImportError:** Use Python 3.10–3.12 and install the neural extra: `python3 -m pip install -e '.[neural]'`. See [README](../README.md#quick-start).
- **Plain backend:** No special troubleshooting; if a PDF is valid (not corrupted, not encrypted), plain extraction should run. For OCR you need Tesseract installed if you use `--force-ocr`.
