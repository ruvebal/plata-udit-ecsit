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
import shutil
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


def _extract_images_with_pymupdf(
    pdf_path: Path, images_dir: Path, max_pages: Optional[int]
) -> tuple[int, list[str]]:
    """Extract page images using PyMuPDF. Saves as PNG when alpha, else JPEG. Returns (count, relative paths)."""
    import fitz

    images_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    count = 0
    paths: list[str] = []
    try:
        limit = doc.page_count if max_pages is None else min(max_pages, doc.page_count)
        for page_idx in range(limit):
            page = doc[page_idx]
            for image in page.get_images(full=True):
                xref = image[0]
                pix = None
                try:
                    pix = fitz.Pixmap(doc, xref)
                    count += 1
                    if pix.alpha:
                        ext = "png"
                        out_path = images_dir / f"{count:03d}.png"
                        pix.save(str(out_path))
                    else:
                        # JPEG accepts only Grayscale, RGB, or CMYK; convert to RGB for any other colorspace.
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                        ext = "jpeg"
                        out_path = images_dir / f"{count:03d}.jpeg"
                        pix.save(str(out_path))
                    paths.append(f"images/{count:03d}.{ext}")
                except Exception as exc:
                    logger.warning(f"Could not save image xref={xref}: {exc}")
                    count -= 1
                finally:
                    if pix is not None:
                        pix = None
    finally:
        doc.close()

    return count, paths


def _append_image_refs_if_missing(md_content: str, image_paths: list[str]) -> str:
    """Append markdown refs if none point to our images/ folder."""
    if not image_paths:
        return md_content
    if "](images/" in md_content:
        return md_content

    refs = "\n".join(f"![]({p})" for p in image_paths)
    return f"{md_content.rstrip()}\n\n## Extracted Images\n\n{refs}\n"


class PlainDoclingExtractor:
    """
    Plain extractor that uses Docling for markdown and PyMuPDF for images.
    """

    def __init__(self, force_ocr: bool = False, overwrite: bool = False):
        self.force_ocr = force_ocr
        self.overwrite = overwrite

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
            output_dir/FILENAME/index.md
            output_dir/FILENAME/images/001.jpeg, 002.jpeg, ...
        """
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:
            raise ImportError(
                "Docling backend dependency missing. Install with:\n"
                "  python3 -m pip install -e ."
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
        if md_path.exists() and not self.overwrite:
            msg = (
                f"Skipped: output already exists at {md_path}. "
                "Use --force or --rewrite to overwrite."
            )
            if file_log is not None:
                file_log.warning(msg)
            return ExtractResult(ok=False, path=pdf_path, error=msg)
        if self.overwrite:
            if md_path.exists():
                md_path.unlink(missing_ok=True)
            if images_dir.exists():
                shutil.rmtree(images_dir, ignore_errors=True)
        doc_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(parents=True, exist_ok=True)

        t0 = time.time()
        subset_path: Optional[Path] = None
        stage_timings_ms: dict[str, int] = {}
        try:
            if max_pages is not None:
                t_subset = time.time()
                subset_path = _build_subset_pdf(pdf_path, max_pages)
                stage_timings_ms["build_subset_pdf"] = int((time.time() - t_subset) * 1000)
                if file_log is not None:
                    file_log.stage("build_subset_pdf", stage_timings_ms["build_subset_pdf"])
            convert_path = subset_path if subset_path is not None else pdf_path

            t_convert = time.time()
            converter = DocumentConverter()
            result = converter.convert(str(convert_path))
            md_content = result.document.export_to_markdown()
            stage_timings_ms["docling_convert"] = int((time.time() - t_convert) * 1000)
            if file_log is not None:
                file_log.stage("docling_convert", stage_timings_ms["docling_convert"])

            doc_dir.mkdir(parents=True, exist_ok=True)
            images_dir.mkdir(parents=True, exist_ok=True)
            t_images = time.time()
            image_count, image_paths = _extract_images_with_pymupdf(
                pdf_path, images_dir, max_pages=max_pages
            )
            stage_timings_ms["extract_images"] = int((time.time() - t_images) * 1000)
            if file_log is not None:
                file_log.stage("extract_images", stage_timings_ms["extract_images"], {
                    "image_count": image_count,
                })
            md_content = _append_image_refs_if_missing(md_content, image_paths)

            doc_dir.mkdir(parents=True, exist_ok=True)
            t_write = time.time()
            md_path.write_text(md_content, encoding="utf-8")
            stage_timings_ms["write_output"] = int((time.time() - t_write) * 1000)
            if file_log is not None:
                file_log.stage("write_output", stage_timings_ms["write_output"])
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
                stage_timings_ms=stage_timings_ms,
                pages_processed=max_pages if max_pages and max_pages > 0 else None,
            )
        except Exception as exc:
            elapsed = time.time() - t0
            logger.error(f"Plain-docling extraction failed for {pdf_path.name}: {exc}")
            return ExtractResult(
                ok=False,
                path=pdf_path,
                elapsed_seconds=elapsed,
                error=str(exc),
                stage_timings_ms=stage_timings_ms,
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
        run_logger=None,
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
            file_log = None
            if run_logger is not None:
                file_log = run_logger.file_logger(pdf_path, output_dir)
                if file_log is not None:
                    file_log.start(pdf_path=pdf_path, output_dir=output_dir)
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
                    ok=False, path=pdf_path, error=f"Skipped: {check.reason}"
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
