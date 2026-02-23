"""
Optional PDF sanitization before neural extraction.

Renders each page at a capped maximum dimension to reduce the chance of
marker-pdf/surya/torch errors (e.g. index out of bounds, AcceleratorError)
on PDFs with very large or unusual page sizes. Use with --sanitize-for-neural.
"""

import logging
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default max dimension (points) for the longest side of any page.
# Larger pages are scaled down so the longest side is at most this.
DEFAULT_MAX_DIMENSION = 3500


def sanitize_pdf_for_neural(
    pdf_path: Path,
    max_pages: Optional[int] = None,
    max_dimension: int = DEFAULT_MAX_DIMENSION,
    temp_dir: Optional[Path] = None,
) -> Path:
    """
    Create a temporary PDF with pages normalized for neural extraction.

    Each page is rendered at a scale such that the longest side is at most
    max_dimension (in points). This can avoid surya/torch failures on PDFs
    with very large or odd-sized pages.

    Args:
        pdf_path: Source PDF.
        max_pages: If set, only the first N pages are included.
        max_dimension: Maximum length of the longest side per page (default 3500).
        temp_dir: Directory for the temp file; uses system default if None.

    Returns:
        Path to a temporary PDF file. Caller must delete it when done.

    Raises:
        OSError: If the PDF cannot be opened or the temp file cannot be written.
    """
    import fitz  # PyMuPDF

    pdf_path = Path(pdf_path).resolve()
    src = fitz.open(pdf_path)
    try:
        limit = src.page_count
        if max_pages is not None and max_pages > 0:
            limit = min(limit, max_pages)

        dst = fitz.open()
        try:
            for i in range(limit):
                page = src[i]
                rect = page.rect
                w, h = rect.width, rect.height
                long_side = max(w, h)
                if long_side <= 0:
                    continue
                scale = min(1.0, max_dimension / long_side)
                mat = fitz.Matrix(scale, scale)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                new_w, new_h = pix.width, pix.height
                new_page = dst.new_page(width=new_w, height=new_h)
                rect_img = fitz.Rect(0, 0, new_w, new_h)
                new_page.insert_image(rect_img, pixmap=pix)

            kwargs: dict = {"suffix": ".pdf", "delete": False}
            if temp_dir is not None:
                kwargs["dir"] = Path(temp_dir).resolve()
            tmp = tempfile.NamedTemporaryFile(
                prefix=f"plata_sanitized_{pdf_path.stem}_",
                **kwargs,
            )
            out_path = Path(tmp.name)
            tmp.close()
            dst.save(out_path)
            logger.debug("Sanitized PDF for neural: %s -> %s", pdf_path.name, out_path.name)
            return out_path
        finally:
            dst.close()
    finally:
        src.close()
