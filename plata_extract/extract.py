"""
PLATA Extract — PDF extractor for Digital Humanities.
Author: Rubén Vega Balbás PhD (ECSIT - UDIT) <ruben.vega@udit.es>

Core extraction logic: thin wrapper around marker-pdf (PdfConverter API).

Design:
  - Model artifact dict is created ONCE in PlatExtractor.__init__ (~3GB, 3-5 seconds).
  - Each file gets a PdfConverter instance using that shared artifact_dict.
  - Output: FILENAME/index.md + FILENAME/images/NNN.jpeg per PDF.

Compatible with marker-pdf 1.10.x (create_model_dict + PdfConverter).
"""

import logging
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from plata_extract.check import CheckResult, check_pdf, list_pdfs

logger = logging.getLogger(__name__)


def _apply_pdftext_doc_patch() -> None:
    """
    Workaround for marker-pdf + pdftext mismatch: marker passes an open
    pypdfium2.PdfDocument to get_text_blocks -> pdftext.dictionary_output,
    but pdftext._load_pdf() always does PdfDocument(pdf), which raises
    'Invalid input type PdfDocument' when pdf is already a document.
    Patch _load_pdf to return a no-close wrapper so pdftext does not close
    marker's document (marker still needs it for detection/OCR/layout).
    """
    import pypdfium2 as pdfium

    try:
        import pdftext.extraction as pdftext_extraction
    except ImportError:
        return

    _original_load_pdf = pdftext_extraction._load_pdf

    class _NoCloseDoc:
        """Proxy so pdftext.close() does not close marker's document."""

        __slots__ = ("_doc",)

        def __init__(self, doc: pdfium.PdfDocument) -> None:
            self._doc = doc

        def close(self) -> None:
            pass  # Marker still needs the document

        def __len__(self) -> int:
            return len(self._doc)

        def __getitem__(self, i: int):
            return self._doc[i]

        def get_page(self, i: int):
            return self._doc.get_page(i)

        def __getattr__(self, name: str):
            return getattr(self._doc, name)

    def _load_pdf(pdf, flatten_pdf):
        if isinstance(pdf, pdfium.PdfDocument):
            if flatten_pdf:
                pdf.init_forms()
            return _NoCloseDoc(pdf)
        return _original_load_pdf(pdf, flatten_pdf)

    pdftext_extraction._load_pdf = _load_pdf


@dataclass
class ExtractResult:
    """Result of extracting a single PDF."""

    ok: bool
    path: Path
    output_md: Optional[Path] = None
    output_images_dir: Optional[Path] = None
    image_count: int = 0
    word_count: int = 0
    elapsed_seconds: float = 0.0
    error: Optional[str] = None
    stage_timings_ms: dict[str, int] = field(default_factory=dict)
    llm_requests: Optional[int] = None
    llm_tokens_used: Optional[int] = None
    llm_errors: Optional[int] = None
    pages_processed: Optional[int] = None


@dataclass
class BatchResult:
    """Summary of a batch extraction run."""

    total: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    results: list[ExtractResult] = field(default_factory=list)
    elapsed_seconds: float = 0.0


class PlatExtractor:
    """
    marker-pdf wrapper for PLATA heritage PDF extraction.

    Load once, extract many:
        extractor = PlatExtractor()
        result = extractor.extract_file(Path("paper.pdf"), Path("exports/"))
        batch = extractor.extract_batch(Path("archive/"), Path("exports/"))
    """

    def __init__(
        self,
        force_ocr: bool = False,
        use_llm: bool = False,
        output_format: str = "markdown",
        llm_service: Optional[str] = None,
        sanitize_for_neural: bool = False,
        overwrite: bool = False,
    ):
        """
        Initialize extractor: loads marker-pdf model artifacts.

        Args:
            force_ocr: Force OCR on all pages (useful for scanned docs).
            use_llm: Use LLM to improve extraction accuracy.
            output_format: "markdown" (default), "json", "html", or "chunks".
            llm_service: Marker LLM service class path
                         (e.g. "marker.services.ollama.OllamaService").
            sanitize_for_neural: If True, normalize PDF (cap page dimensions) before
                                neural extraction to reduce surya/torch failures.
        """
        try:
            from marker.models import create_model_dict
            from marker.converters.pdf import PdfConverter
            from marker.output import text_from_rendered
        except ImportError as exc:
            raise ImportError(
                "marker-pdf not installed or incompatible. Install with:\n"
                "  python3 -m pip install -e '.[neural]'\n\n"
                "For non-PDF file support:\n"
                "  python3 -m pip install -e '.[full]'"
            ) from exc

        _apply_pdftext_doc_patch()

        self.force_ocr = force_ocr
        self.use_llm = use_llm
        self.output_format = output_format
        self.llm_service = llm_service
        self.sanitize_for_neural = sanitize_for_neural
        self.overwrite = overwrite
        self._PdfConverter = PdfConverter
        self._text_from_rendered = text_from_rendered

        logger.info("Loading marker-pdf models (this takes a few seconds)...")
        t0 = time.time()
        self._artifact_dict = create_model_dict()
        elapsed = time.time() - t0
        logger.info(f"Models loaded in {elapsed:.1f}s")

    def _renderer_class_name(self) -> str:
        """Return marker renderer class path for current output_format."""
        renderers = {
            "markdown": "marker.renderers.markdown.MarkdownRenderer",
            "json": "marker.renderers.json.JSONRenderer",
            "html": "marker.renderers.html.HTMLRenderer",
            "chunks": "marker.renderers.chunk.ChunkRenderer",
        }
        return renderers.get(self.output_format, renderers["markdown"])

    def extract_file(
        self,
        pdf_path: Path,
        output_dir: Path,
        max_pages: Optional[int] = None,
        file_log=None,
    ) -> ExtractResult:
        """
        Extract a single PDF to Markdown + images.

        Output layout:
            output_dir/FILENAME/index.md (or index.json/html per output_format)
            output_dir/FILENAME/images/001.jpeg, 002.jpeg, ...

        Args:
            pdf_path: Path to the PDF file.
            output_dir: Directory for output files.
            max_pages: If set, process only the first N pages (for testing).

        Returns:
            ExtractResult with paths and stats.
        """
        pdf_path = Path(pdf_path).resolve()
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        stem = pdf_path.stem
        doc_dir = output_dir / stem
        images_dir = doc_dir / "images"
        doc_dir.mkdir(parents=True, exist_ok=True)
        ext_map = {"markdown": "md", "json": "json", "html": "html", "chunks": "json"}
        expected_ext = ext_map.get(self.output_format, "md")
        expected_out = doc_dir / f"index.{expected_ext}"
        if expected_out.exists() and not self.overwrite:
            msg = (
                f"Skipped: output already exists at {expected_out}. "
                "Use --force or --rewrite to overwrite."
            )
            if file_log is not None:
                file_log.warning(msg)
            return ExtractResult(ok=False, path=pdf_path, error=msg)
        if self.overwrite:
            if expected_out.exists():
                expected_out.unlink(missing_ok=True)
            if images_dir.exists():
                shutil.rmtree(images_dir, ignore_errors=True)
        stage_timings_ms: dict[str, int] = {}

        config: dict = {
            "force_ocr": self.force_ocr,
            "use_llm": self.use_llm,
            "pdftext_workers": 1,
        }
        if max_pages is not None and max_pages > 0:
            config["page_range"] = list(range(max_pages))

        # Optional: normalize PDF (cap page dimensions) before neural to reduce surya/torch failures
        path_to_convert = pdf_path
        temp_sanitized: Optional[Path] = None
        if self.sanitize_for_neural:
            from plata_extract.sanitize import sanitize_pdf_for_neural
            try:
                temp_sanitized = sanitize_pdf_for_neural(
                    pdf_path, max_pages=max_pages,
                )
                path_to_convert = temp_sanitized
                logger.info("Neural input sanitized (capped page size): %s", pdf_path.name)
            except Exception as exc:
                if temp_sanitized and temp_sanitized.exists():
                    try:
                        temp_sanitized.unlink()
                    except OSError:
                        pass
                logger.warning("Sanitization failed, using original PDF: %s", exc)
                temp_sanitized = None

        t0 = time.time()
        try:
            converter = self._PdfConverter(
                artifact_dict=self._artifact_dict,
                config=config,
                renderer=self._renderer_class_name(),
                llm_service=self.llm_service,
            )
            t_convert = time.time()
            rendered = converter(str(path_to_convert))
            stage_timings_ms["converter"] = int((time.time() - t_convert) * 1000)
            if file_log is not None:
                file_log.stage("converter", stage_timings_ms["converter"])
        except Exception as exc:
            elapsed = time.time() - t0
            logger.exception("Neural extraction failed for %s", pdf_path.name)
            err_msg = str(exc)
            # Suggest workarounds for known marker/surya/torch bugs (index out of bounds, AcceleratorError on some pages)
            if (
                "out of bounds" in err_msg.lower()
                or "index" in err_msg.lower()
                or "AcceleratorError" in type(exc).__name__
            ):
                err_msg += (
                    " (Known surya/torch issue on some PDFs. "
                    "Try --sanitize-for-neural, --backend plain, or --max-pages N.)"
                )
            return ExtractResult(
                ok=False,
                path=pdf_path,
                elapsed_seconds=elapsed,
                error=err_msg,
                stage_timings_ms=stage_timings_ms,
            )
        finally:
            if temp_sanitized is not None and temp_sanitized.exists():
                try:
                    temp_sanitized.unlink()
                except OSError:
                    pass

        t_rendered = time.time()
        text, ext, images = self._text_from_rendered(rendered)
        stage_timings_ms["rendered_to_text"] = int((time.time() - t_rendered) * 1000)
        if file_log is not None:
            file_log.stage("rendered_to_text", stage_timings_ms["rendered_to_text"])

        # Output filename: index.md, index.json, or index.html
        out_basename = f"index.{ext}"
        out_path = doc_dir / out_basename

        # Save images with sequential numbering
        image_count = 0
        image_name_map: dict[str, str] = {}

        if images:
            t_images = time.time()
            images_dir.mkdir(parents=True, exist_ok=True)
            for original_name, img in images.items():
                image_count += 1
                new_name = f"{image_count:03d}.jpeg"
                img_path = images_dir / new_name
                try:
                    if img.mode in ("RGBA", "P", "LA"):
                        img = img.convert("RGB")
                    img.save(img_path, "JPEG", quality=90)
                    image_name_map[original_name] = f"images/{new_name}"
                except Exception as exc:
                    logger.warning(f"Could not save image {original_name}: {exc}")
                    image_count -= 1
            stage_timings_ms["image_save"] = int((time.time() - t_images) * 1000)
            if file_log is not None:
                file_log.stage("image_save", stage_timings_ms["image_save"], {
                    "image_count": image_count,
                })

        # Rewrite image references in text (markdown/html)
        content = text or ""
        for original_name, new_ref in image_name_map.items():
            content = content.replace(original_name, new_ref)

        t_write = time.time()
        out_path.write_text(content, encoding="utf-8")
        stage_timings_ms["write_output"] = int((time.time() - t_write) * 1000)
        if file_log is not None:
            file_log.stage("write_output", stage_timings_ms["write_output"])
        word_count = len(content.split())
        elapsed = time.time() - t0

        return ExtractResult(
            ok=True,
            path=pdf_path,
            output_md=out_path,
            output_images_dir=images_dir if image_count > 0 else None,
            image_count=image_count,
            word_count=word_count,
            elapsed_seconds=elapsed,
            stage_timings_ms=stage_timings_ms,
            pages_processed=max_pages if max_pages and max_pages > 0 else None,
        )

    def extract_batch(
        self,
        input_dir: Path,
        output_dir: Path,
        check_only: bool = False,
        max_pages: Optional[int] = None,
        run_logger=None,
    ) -> BatchResult:
        """
        Extract all PDFs in a directory.

        1. Lists and sorts PDF files.
        2. Runs integrity check on each.
        3. Extracts valid PDFs sequentially.
        4. Returns summary.

        Args:
            input_dir: Directory containing PDFs.
            output_dir: Output directory.
            check_only: Only run integrity checks, skip extraction.
            max_pages: If set, process only the first N pages per file.

        Returns:
            BatchResult with per-file results and totals.
        """
        input_dir = Path(input_dir).resolve()
        output_dir = Path(output_dir).resolve()

        pdfs = list_pdfs(input_dir)
        total = len(pdfs)

        if total == 0:
            logger.warning(f"No PDF files found in {input_dir}")
            return BatchResult(total=0)

        batch = BatchResult(total=total)
        batch_t0 = time.time()

        logger.info(f"Found {total} PDF(s) in {input_dir}")

        for i, pdf_path in enumerate(pdfs, 1):
            file_log = None
            if run_logger is not None:
                file_log = run_logger.file_logger(pdf_path, output_dir)
                if file_log is not None:
                    file_log.start(pdf_path=pdf_path, output_dir=output_dir)
            # Pre-flight check
            check = check_pdf(pdf_path)
            prefix = f"[{i}/{total}]"
            if file_log is not None:
                file_log.check_result(
                    pdf_path=pdf_path,
                    ok=check.ok,
                    reason=check.reason,
                    page_count=check.page_count,
                    file_size_mb=check.file_size_mb,
                )

            if not check.ok:
                logger.warning(f"{prefix} SKIP {pdf_path.name}: {check.reason}")
                batch.skipped += 1
                skipped_result = ExtractResult(
                    ok=False, path=pdf_path, error=f"Skipped: {check.reason}",
                )
                batch.results.append(skipped_result)
                if file_log is not None:
                    file_log.complete(skipped_result)
                continue

            pages_info = f"{check.page_count} pages, {check.file_size_mb}MB"
            logger.info(f"{prefix} {pdf_path.name} ({pages_info})")

            if check_only:
                logger.info(f"{prefix} CHECK OK: {pdf_path.name}")
                batch.succeeded += 1
                check_only_result = ExtractResult(ok=True, path=pdf_path)
                batch.results.append(check_only_result)
                if file_log is not None:
                    file_log.complete(check_only_result)
                continue

            # Extract
            result = self.extract_file(
                pdf_path, output_dir, max_pages=max_pages, file_log=file_log
            )

            if result.ok:
                batch.succeeded += 1
                img_info = f", {result.image_count} images" if result.image_count else ""
                logger.info(
                    f"{prefix} Done: {result.elapsed_seconds:.1f}s, "
                    f"{result.word_count} words{img_info}"
                )
            else:
                if str(result.error or "").startswith("Skipped:"):
                    batch.skipped += 1
                    logger.warning(f"{prefix} SKIP {pdf_path.name}: {result.error}")
                else:
                    batch.failed += 1
                    logger.error(f"{prefix} FAILED: {result.error}")

            batch.results.append(result)
            if file_log is not None:
                file_log.complete(result)

        batch.elapsed_seconds = time.time() - batch_t0

        logger.info(
            f"\nBatch complete: {batch.succeeded} succeeded, "
            f"{batch.skipped} skipped, {batch.failed} failed "
            f"({batch.elapsed_seconds:.1f}s total)"
        )

        return batch
