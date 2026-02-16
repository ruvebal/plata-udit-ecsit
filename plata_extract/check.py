"""
PLATA Extract — PDF extractor for Digital Humanities.
Author: Rubén Vega Balbás PhD (ECSIT - UDIT) <ruben.vega@udit.es>

PDF integrity verification.

Runs BEFORE any marker-pdf call to catch corrupted, encrypted,
or otherwise unusable files early with clear error messages.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# PDF magic bytes: %PDF (first 5 bytes of any valid PDF)
PDF_MAGIC = b"%PDF-"


@dataclass(frozen=True)
class CheckResult:
    """Result of a PDF integrity check."""

    ok: bool
    path: Path
    reason: str
    page_count: int = 0
    file_size_mb: float = 0.0


def check_pdf(path: Path) -> CheckResult:
    """
    Pre-flight integrity check for a PDF file.

    Checks performed (in order):
      1. File exists and is readable
      2. Has .pdf extension
      3. Starts with %PDF magic bytes
      4. Can be opened by PyMuPDF (not corrupted)
      5. Is not encrypted / password-protected
      6. Has at least 1 page

    Args:
        path: Path to the PDF file.

    Returns:
        CheckResult with ok=True if all checks pass,
        or ok=False with a human-readable reason.
    """
    path = Path(path).resolve()

    # 1. File exists
    if not path.exists():
        return CheckResult(ok=False, path=path, reason="File not found")

    if not path.is_file():
        return CheckResult(ok=False, path=path, reason="Not a file")

    # File size
    file_size = path.stat().st_size
    file_size_mb = round(file_size / (1024 * 1024), 2)

    if file_size == 0:
        return CheckResult(
            ok=False, path=path, reason="Empty file (0 bytes)",
            file_size_mb=0.0,
        )

    # 2. Extension check
    if path.suffix.lower() != ".pdf":
        return CheckResult(
            ok=False, path=path,
            reason=f"Not a PDF file (extension: {path.suffix})",
            file_size_mb=file_size_mb,
        )

    # 3. Magic bytes check
    try:
        with open(path, "rb") as f:
            header = f.read(5)
        if not header.startswith(PDF_MAGIC):
            return CheckResult(
                ok=False, path=path,
                reason="Invalid PDF (missing %PDF header)",
                file_size_mb=file_size_mb,
            )
    except PermissionError:
        return CheckResult(
            ok=False, path=path, reason="Permission denied",
            file_size_mb=file_size_mb,
        )
    except OSError as exc:
        return CheckResult(
            ok=False, path=path, reason=f"Cannot read file: {exc}",
            file_size_mb=file_size_mb,
        )

    # 4-6. Open with PyMuPDF for deep validation
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning("PyMuPDF not installed; skipping deep PDF validation")
        return CheckResult(
            ok=True, path=path, reason="OK (shallow check only)",
            file_size_mb=file_size_mb,
        )

    try:
        doc = fitz.open(path)
    except Exception as exc:
        return CheckResult(
            ok=False, path=path,
            reason=f"Corrupted PDF: {exc}",
            file_size_mb=file_size_mb,
        )

    try:
        # 5. Encryption check
        if doc.is_encrypted:
            doc.close()
            return CheckResult(
                ok=False, path=path,
                reason="Encrypted / password-protected PDF",
                file_size_mb=file_size_mb,
            )

        # 6. Page count
        page_count = doc.page_count
        if page_count == 0:
            doc.close()
            return CheckResult(
                ok=False, path=path,
                reason="PDF has 0 pages",
                file_size_mb=file_size_mb,
            )

        doc.close()

        return CheckResult(
            ok=True, path=path,
            reason="OK",
            page_count=page_count,
            file_size_mb=file_size_mb,
        )

    except Exception as exc:
        doc.close()
        return CheckResult(
            ok=False, path=path,
            reason=f"Error reading PDF metadata: {exc}",
            file_size_mb=file_size_mb,
        )


def list_pdfs(directory: Path) -> list[Path]:
    """
    List all PDF files in a directory (non-recursive).

    Args:
        directory: Path to scan.

    Returns:
        Sorted list of .pdf file paths.
    """
    directory = Path(directory).resolve()

    if not directory.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory}")

    pdfs = sorted(
        p for p in directory.iterdir()
        if p.is_file() and p.suffix.lower() == ".pdf"
    )

    return pdfs
