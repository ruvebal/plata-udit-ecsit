"""
PLATA Extract — PDF extractor for Digital Humanities.
Author: Rubén Vega Balbás PhD (ECSIT - UDIT) <ruben.vega@udit.es>

Plain (non-neural) extraction backend using pymupdf4llm + PyMuPDF.

Design:
  - No model loading, instant startup.
  - CPU-friendly extraction for digitally-authored PDFs.
  - Output: FILENAME/index.md + FILENAME/images/NNN.jpeg per PDF.
"""

import logging
import time
from pathlib import Path
from typing import Optional

from plata_extract.check import check_pdf, list_pdfs
from plata_extract.extract import BatchResult, ExtractResult

logger = logging.getLogger(__name__)


def _renumber_images(images_dir: Path) -> tuple[dict[str, str], int]:
    """
    Rename extracted images to sequential 001.jpeg, 002.jpeg, ...

    Returns:
        (mapping old filename -> new relative markdown ref, count)
    """
    image_files = sorted(
        p for p in images_dir.iterdir()
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
    )

    if not image_files:
        return {}, 0

    # Stage to temp names to avoid collisions when renaming in-place.
    staged: list[tuple[str, Path]] = []
    for idx, path in enumerate(image_files, 1):
        tmp_path = images_dir / f".tmp_{idx:03d}{path.suffix.lower()}"
        path.rename(tmp_path)
        staged.append((path.name, tmp_path))

    name_map: dict[str, str] = {}
    for idx, (old_name, tmp_path) in enumerate(staged, 1):
        new_name = f"{idx:03d}.jpeg"
        final_path = images_dir / new_name
        tmp_path.rename(final_path)
        name_map[old_name] = f"images/{new_name}"

    return name_map, len(staged)


class PlainExtractor:
    """
    Non-neural PDF extractor based on pymupdf4llm.

    This backend is optimized for speed and low-resource environments.
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
        # Optional: import before pymupdf4llm to enable improved layout analysis (titles, headings, tables)
        try:
            import pymupdf_layout  # noqa: F401
        except ImportError:
            pass
        try:
            import pymupdf4llm
        except ImportError as exc:
            raise ImportError(
                "Plain backend dependency missing. Install with:\n"
                "  python3 -m pip install -e ."
            ) from exc

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

        pages = list(range(max_pages)) if max_pages is not None else None
        markdown_kwargs = {
            "doc": str(pdf_path),
            "pages": pages,
            "write_images": True,
            "image_path": str(images_dir),
            "image_format": "jpeg",
            "dpi": 150,
        }
        if self.force_ocr:
            markdown_kwargs["use_ocr"] = True

        try:
            md_content = pymupdf4llm.to_markdown(**markdown_kwargs)
        except Exception as exc:
            elapsed = time.time() - t0
            logger.error(f"Plain extraction failed for {pdf_path.name}: {exc}")
            return ExtractResult(
                ok=False,
                path=pdf_path,
                elapsed_seconds=elapsed,
                error=str(exc),
            )

        image_name_map, image_count = _renumber_images(images_dir)

        # Rewrite image references to our stable relative layout.
        for old_name, new_ref in image_name_map.items():
            md_content = md_content.replace(old_name, new_ref)
            md_content = md_content.replace(f"./images/{old_name}", new_ref)
            md_content = md_content.replace(f"images/{old_name}", new_ref)
            md_content = md_content.replace(str(images_dir / old_name), new_ref)
            md_content = md_content.replace(str((images_dir / old_name).resolve()), new_ref)

        md_path.write_text(md_content, encoding="utf-8")
        word_count = len(md_content.split())
        elapsed = time.time() - t0

        # Clean up empty image directory if no images were extracted.
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

    def extract_batch(
        self,
        input_dir: Path,
        output_dir: Path,
        check_only: bool = False,
        max_pages: Optional[int] = None,
    ) -> BatchResult:
        """
        Extract all PDFs in a directory using the plain backend.
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
