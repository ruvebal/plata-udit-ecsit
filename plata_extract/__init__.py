"""
PLATA Extract — PDF extractor for Digital Humanities.
Author: Rubén Vega Balbás PhD (ECSIT - UDIT) <ruben.vega@udit.es>
Status: Ongoing
Converts heritage PDFs into clean Markdown + extracted images using:
  - plain backend (pymupdf4llm + PyMuPDF)
  - neural backend (marker-pdf)
"""

__version__ = "0.2.0"

from plata_extract.check import CheckResult, check_pdf
from plata_extract.extract import BatchResult, ExtractResult, PlatExtractor
from plata_extract.extract_plain import PlainExtractor
from plata_extract.extract_plain_docling import PlainDoclingExtractor

__all__ = [
    "check_pdf",
    "CheckResult",
    "PlainExtractor",
    "PlainDoclingExtractor",
    "PlatExtractor",
    "ExtractResult",
    "BatchResult",
]
