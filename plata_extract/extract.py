"""
PLATA Extract — PDF extractor for Digital Humanities.
Author: Rubén Vega Balbás PhD (ECSIT - UDIT) <ruben.vega@udit.es>

Core extraction logic: thin wrapper around marker-pdf's convert_single_pdf.

Design:
  - Models are loaded ONCE in PlatExtractor.__init__ (~3GB, 3-5 seconds).
  - Each file reuses the shared model list.
  - Output: FILENAME/index.md + FILENAME/images/NNN.jpeg per PDF.
"""

import logging
import re
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
    ):
        """
        Initialize extractor: loads marker-pdf model artifacts.

        Args:
            force_ocr: Force OCR on all pages (useful for scanned docs).
            use_llm: Use LLM to improve extraction accuracy.
            output_format: "markdown" (default), "json", "html", or "chunks".
            llm_service: Marker LLM service class path
                         (e.g. "marker.services.ollama.OllamaService").
        """
        try:
            from marker.models import load_all_models
        except ImportError as exc:
            raise ImportError(
                "marker-pdf not installed. Install with:\n"
                "  pip install marker-pdf\n\n"
                "For non-PDF file support:\n"
                "  pip install 'marker-pdf[full]'"
            ) from exc

        _apply_pdftext_doc_patch()

        self.force_ocr = force_ocr
        self.use_llm = use_llm
        self.output_format = output_format
        self.llm_service = llm_service

        logger.info("Loading marker-pdf models (this takes a few seconds)...")
        t0 = time.time()
        self._model_lst = load_all_models(force_load_ocr=self.force_ocr)
        elapsed = time.time() - t0
        logger.info(f"Models loaded in {elapsed:.1f}s")

    def extract_file(
        self,
        pdf_path: Path,
        output_dir: Path,
        max_pages: Optional[int] = None,
    ) -> ExtractResult:
        """
        Extract a single PDF to Markdown + images.

        Output layout:
            output_dir/FILENAME/index.md
            output_dir/FILENAME/images/001.jpeg, 002.jpeg, ...

        Args:
            pdf_path: Path to the PDF file.
            output_dir: Directory for output files.
            max_pages: If set, process only the first N pages (for testing).

        Returns:
            ExtractResult with paths and stats.
        """
        from marker.convert import convert_single_pdf

        pdf_path = Path(pdf_path).resolve()
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        stem = pdf_path.stem
        doc_dir = output_dir / stem
        md_path = doc_dir / "index.md"
        images_dir = doc_dir / "images"
        doc_dir.mkdir(parents=True, exist_ok=True)

        t0 = time.time()

        try:
            full_text, images, _ = convert_single_pdf(
                str(pdf_path),
                self._model_lst,
                max_pages=max_pages,
            )
            text = full_text
        except Exception as exc:
            elapsed = time.time() - t0
            logger.error(f"Extraction failed for {pdf_path.name}: {exc}")
            return ExtractResult(
                ok=False, path=pdf_path,
                elapsed_seconds=elapsed,
                error=str(exc),
            )

        # Save images with sequential numbering
        image_count = 0
        image_name_map: dict[str, str] = {}

        if images:
            images_dir.mkdir(parents=True, exist_ok=True)

            for original_name, img in images.items():
                image_count += 1
                new_name = f"{image_count:03d}.jpeg"
                img_path = images_dir / new_name

                try:
                    # Convert to RGB if necessary (some images are RGBA/palette)
                    if img.mode in ("RGBA", "P", "LA"):
                        img = img.convert("RGB")
                    img.save(img_path, "JPEG", quality=90)
                    image_name_map[original_name] = f"images/{new_name}"
                except Exception as exc:
                    logger.warning(f"Could not save image {original_name}: {exc}")
                    image_count -= 1

        # Rewrite image references in markdown
        md_content = text or ""
        for original_name, new_ref in image_name_map.items():
            # marker uses ![alt](original_name) — replace with our path
            md_content = md_content.replace(original_name, new_ref)

        # Write markdown
        md_path.write_text(md_content, encoding="utf-8")

        # Word count (rough)
        word_count = len(md_content.split())

        elapsed = time.time() - t0

        return ExtractResult(
            ok=True,
            path=pdf_path,
            output_md=md_path,
            output_images_dir=images_dir if image_count > 0 else None,
            image_count=image_count,
            word_count=word_count,
            elapsed_seconds=elapsed,
        )

    def extract_batch(
        self,
        input_dir: Path,
        output_dir: Path,
        check_only: bool = False,
        max_pages: Optional[int] = None,
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
            # Pre-flight check
            check = check_pdf(pdf_path)
            prefix = f"[{i}/{total}]"

            if not check.ok:
                logger.warning(f"{prefix} SKIP {pdf_path.name}: {check.reason}")
                batch.skipped += 1
                batch.results.append(ExtractResult(
                    ok=False, path=pdf_path, error=f"Skipped: {check.reason}",
                ))
                continue

            pages_info = f"{check.page_count} pages, {check.file_size_mb}MB"
            logger.info(f"{prefix} {pdf_path.name} ({pages_info})")

            if check_only:
                logger.info(f"{prefix} CHECK OK: {pdf_path.name}")
                batch.succeeded += 1
                batch.results.append(ExtractResult(ok=True, path=pdf_path))
                continue

            # Extract
            result = self.extract_file(
                pdf_path, output_dir, max_pages=max_pages
            )

            if result.ok:
                batch.succeeded += 1
                img_info = f", {result.image_count} images" if result.image_count else ""
                logger.info(
                    f"{prefix} Done: {result.elapsed_seconds:.1f}s, "
                    f"{result.word_count} words{img_info}"
                )
            else:
                batch.failed += 1
                logger.error(f"{prefix} FAILED: {result.error}")

            batch.results.append(result)

        batch.elapsed_seconds = time.time() - batch_t0

        logger.info(
            f"\nBatch complete: {batch.succeeded} succeeded, "
            f"{batch.skipped} skipped, {batch.failed} failed "
            f"({batch.elapsed_seconds:.1f}s total)"
        )

        return batch
