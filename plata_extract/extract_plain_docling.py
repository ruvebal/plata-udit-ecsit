"""
PLATA Extract — PDF extractor for Digital Humanities.
Author: Rubén Vega Balbás PhD (ECSIT - UDIT) <ruben.vega@udit.es>

Design:
  - No heavy model loading in this wrapper.
  - Layout-aware markdown via Docling.
  - Image extraction via PyMuPDF.
  - Output: FILENAME/index.md + FILENAME/images/NNN.jpeg per PDF.
"""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path
from typing import Optional

from plata_extract.check import check_pdf, list_pdfs
from plata_extract.extract import BatchResult, ExtractResult

logger = logging.getLogger(__name__)


def _build_subset_pdf(pdf_path: Path, max_pages: int) -> Optional[Path]:
    """Create a temporary PDF with only the first N pages."""
    if max_pages <= 0:
        return None

    import fitz

    src = fitz.open(pdf_path)
    try:
        if src.page_count <= max_pages:
            return None

        limit = min(max_pages, src.page_count)
        dst = fitz.open()
        try:
            dst.insert_pdf(src, from_page=0, to_page=limit - 1)
            tmp = tempfile.NamedTemporaryFile(
                prefix=f"{pdf_path.stem}_subset_",
                suffix=".pdf",
                delete=False,
            )
            tmp_path = Path(tmp.name)
            tmp.close()
            dst.save(tmp_path)
            return tmp_path
        finally:
            dst.close()
    finally:
        src.close()


def _extract_images_with_pymupdf(pdf_path: Path, images_dir: Path, max_pages: Optional[int]) -> int:
    """Extract page images using PyMuPDF and save as NNN.jpeg files."""
    import fitz

    doc = fitz.open(pdf_path)
    count = 0
    try:
        limit = doc.page_count if max_pages is None else min(max_pages, doc.page_count)
        for page_idx in range(limit):
            page = doc[page_idx]
            for image in page.get_images(full=True):
                xref = image[0]
                pix = None
                try:
                    pix = fitz.Pixmap(doc, xref)
                    # Convert non-RGB images so JPEG save is reliable.
                    if pix.n - pix.alpha > 3:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    count += 1
                    out_path = images_dir / f"{count:03d}.jpeg"
                    pix.save(out_path)
                except Exception as exc:
                    logger.warning(f"Could not save image xref={xref}: {exc}")
                    count -= 1 if count > 0 else 0
                finally:
                    if pix is not None:
                        pix = None
    finally:
        doc.close()

    return count


def _append_image_refs_if_missing(md_content: str, image_count: int) -> str:
    """Append markdown refs if none point to our images/ folder."""
    if image_count <= 0:
        return md_content
    if "](images/" in md_content:
        return md_content

    refs = "\n".join(f"![](images/{i:03d}.jpeg)" for i in range(1, image_count + 1))
    return f"{md_content.rstrip()}\n\n## Extracted Images\n\n{refs}\n"


class PlainDoclingExtractor:
    """
    Plain extractor that uses Docling for markdown and PyMuPDF for images.
    """

    def __init__(self, force_ocr: bool = False):
        self.force_ocr = force_ocr

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
        """
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:
            raise ImportError(
                "Docling backend dependency missing. Install with:\n"
                "  pip install docling\n"
                "or\n"
                "  pip install -e '.[plain_docling]'"
            ) from exc

        if self.force_ocr:
            logger.warning(
                "--force-ocr requested for plain-docling. "
                "OCR behavior depends on installed docling capabilities."
            )

        pdf_path = Path(pdf_path).resolve()
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        stem = pdf_path.stem
        doc_dir = output_dir / stem
        md_path = doc_dir / "index.md"
        images_dir = doc_dir / "images"
        doc_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)

        t0 = time.time()
        subset_path: Optional[Path] = None
        try:
            if max_pages is not None:
                subset_path = _build_subset_pdf(pdf_path, max_pages)
            convert_path = subset_path if subset_path is not None else pdf_path

            converter = DocumentConverter()
            result = converter.convert(str(convert_path))
            md_content = result.document.export_to_markdown()

            image_count = _extract_images_with_pymupdf(pdf_path, images_dir, max_pages=max_pages)
            md_content = _append_image_refs_if_missing(md_content, image_count)

            md_path.write_text(md_content, encoding="utf-8")
            word_count = len(md_content.split())
            elapsed = time.time() - t0

            if image_count == 0:
                try:
                    images_dir.rmdir()
                except OSError:
                    pass

            return ExtractResult(
                ok=True,
                path=pdf_path,
                output_md=md_path,
                output_images_dir=images_dir if image_count > 0 else None,
                image_count=image_count,
                word_count=word_count,
                elapsed_seconds=elapsed,
            )
        except Exception as exc:
            elapsed = time.time() - t0
            logger.error(f"Plain-docling extraction failed for {pdf_path.name}: {exc}")
            return ExtractResult(
                ok=False,
                path=pdf_path,
                elapsed_seconds=elapsed,
                error=str(exc),
            )
        finally:
            if subset_path is not None:
                try:
                    subset_path.unlink(missing_ok=True)
                except OSError:
                    logger.warning(f"Could not remove temp file: {subset_path}")

    def extract_batch(
        self,
        input_dir: Path,
        output_dir: Path,
        check_only: bool = False,
        max_pages: Optional[int] = None,
    ) -> BatchResult:
        """
        Extract all PDFs in a directory using the plain-docling backend.
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
            check = check_pdf(pdf_path)
            prefix = f"[{i}/{total}]"

            if not check.ok:
                logger.warning(f"{prefix} SKIP {pdf_path.name}: {check.reason}")
                batch.skipped += 1
                batch.results.append(
                    ExtractResult(ok=False, path=pdf_path, error=f"Skipped: {check.reason}")
                )
                continue

            pages_info = f"{check.page_count} pages, {check.file_size_mb}MB"
            logger.info(f"{prefix} {pdf_path.name} ({pages_info})")

            if check_only:
                logger.info(f"{prefix} CHECK OK: {pdf_path.name}")
                batch.succeeded += 1
                batch.results.append(ExtractResult(ok=True, path=pdf_path))
                continue

            result = self.extract_file(pdf_path, output_dir, max_pages=max_pages)
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
