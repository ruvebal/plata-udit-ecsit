#!/usr/bin/env python3
"""
PLATA Extract — PDF extractor for Digital Humanities.
Author: Rubén Vega Balbás PhD (ECSIT - UDIT) <ruben.vega@udit.es>

PLATA Extract — CLI entry point.

Usage:
    plata-extract paper.pdf -o exports/
    plata-extract archive/ -o exports/
    plata-extract archive/ --check-only
    plata-extract paper.pdf --force-ocr --use-llm
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Union

from plata_extract import __version__
from plata_extract.check import check_pdf
from plata_extract.extract import PlatExtractor
from plata_extract.extract_plain import PlainExtractor
from plata_extract.extract_plain_docling import PlainDoclingExtractor


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for CLI output."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="plata-extract",
        description=(
            "PLATA Extract — Convert heritage PDFs to Markdown + images.\n"
            "Multi-backend: plain (pymupdf4llm), plain-docling (Docling), "
            "and neural (marker-pdf)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  plata-extract paper.pdf
  plata-extract paper.pdf -o exports/
  plata-extract archive/ -o exports/
  plata-extract archive/ --check-only
  plata-extract paper.pdf --force-ocr
  plata-extract paper.pdf --use-llm
  plata-extract paper.pdf --max-pages 10

Output structure:
  exports/FILENAME/index.md
  exports/FILENAME/images/001.jpeg, 002.jpeg, ...
        """,
    )

    parser.add_argument(
        "input",
        type=Path,
        help="PDF file or directory containing PDFs.",
    )

    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=Path("./exports"),
        help="Output directory (default: ./exports).",
    )

    parser.add_argument(
        "--backend",
        choices=["plain", "plain-docling", "neural"],
        default="plain",
        help=(
            "Extraction backend: 'plain' (fast, default), "
            "'plain-docling' (layout-aware plain), or "
            "'neural' (marker-pdf, highest accuracy)."
        ),
    )

    parser.add_argument(
        "--force-ocr",
        action="store_true",
        help="Force OCR on all pages (use for scanned documents).",
    )

    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Use LLM to improve accuracy (requires Ollama or API key).",
    )

    parser.add_argument(
        "--llm-service",
        type=str,
        default=None,
        help=(
            "LLM service class for --use-llm "
            "(e.g. 'marker.services.ollama.OllamaService'). "
            "Default: Gemini."
        ),
    )

    parser.add_argument(
        "--format",
        choices=["markdown", "json", "html", "chunks"],
        default="markdown",
        help="Output format (default: markdown).",
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        metavar="N",
        help="Process only the first N pages (for testing or low-memory runs).",
    )

    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only run PDF integrity checks, skip extraction.",
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose/debug output.",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"plata-extract {__version__}",
    )

    return parser


def build_extractor(
    args: argparse.Namespace,
) -> Union[PlainExtractor, PlainDoclingExtractor, PlatExtractor]:
    """Construct backend extractor from CLI arguments."""
    if args.backend == "neural":
        return PlatExtractor(
            force_ocr=args.force_ocr,
            use_llm=args.use_llm,
            output_format=args.format,
            llm_service=args.llm_service,
        )

    if args.backend == "plain-docling":
        if args.use_llm or args.llm_service is not None:
            logging.getLogger(__name__).warning(
                "--use-llm/--llm-service are neural-only options; "
                "ignoring for plain-docling backend."
            )
        if args.format != "markdown":
            logging.getLogger(__name__).warning(
                "--format is neural-only; plain-docling backend outputs markdown."
            )
        return PlainDoclingExtractor(force_ocr=args.force_ocr)

    if args.use_llm or args.llm_service is not None:
        logging.getLogger(__name__).warning(
            "--use-llm/--llm-service are neural-only options; ignoring for plain backend."
        )
    if args.format != "markdown":
        logging.getLogger(__name__).warning(
            "--format is neural-only; plain backend always outputs markdown."
        )

    return PlainExtractor(force_ocr=args.force_ocr)


def run_single(args: argparse.Namespace) -> int:
    """Process a single PDF file."""
    pdf_path = args.input.resolve()

    # Integrity check
    check = check_pdf(pdf_path)
    if not check.ok:
        logging.getLogger(__name__).error(
            f"Cannot process {pdf_path.name}: {check.reason}"
        )
        return 1

    logging.getLogger(__name__).info(
        f"{pdf_path.name}: {check.page_count} pages, {check.file_size_mb}MB"
    )

    if args.check_only:
        logging.getLogger(__name__).info("Check passed.")
        return 0

    # Extract
    extractor = build_extractor(args)

    result = extractor.extract_file(
        pdf_path, args.output_dir, max_pages=args.max_pages
    )

    if result.ok:
        log = logging.getLogger(__name__)
        log.info(f"  -> {result.output_md}")
        if result.image_count > 0:
            log.info(f"  -> {result.output_images_dir}/ ({result.image_count} images)")
        log.info(
            f"  {result.word_count} words, {result.elapsed_seconds:.1f}s"
        )
        return 0
    else:
        logging.getLogger(__name__).error(f"Failed: {result.error}")
        return 1


def run_batch(args: argparse.Namespace) -> int:
    """Process all PDFs in a directory."""
    if args.check_only:
        # Light check mode: no need to load marker models
        from plata_extract.check import list_pdfs

        pdfs = list_pdfs(args.input)
        log = logging.getLogger(__name__)

        if not pdfs:
            log.warning(f"No PDF files found in {args.input}")
            return 0

        ok_count = 0
        fail_count = 0

        for i, pdf in enumerate(pdfs, 1):
            check = check_pdf(pdf)
            status = "OK" if check.ok else f"FAIL ({check.reason})"
            pages = f"{check.page_count}p" if check.ok else ""
            log.info(f"[{i}/{len(pdfs)}] {pdf.name}: {status} {pages}")

            if check.ok:
                ok_count += 1
            else:
                fail_count += 1

        log.info(f"\n{ok_count} OK, {fail_count} failed out of {len(pdfs)}")
        return 0 if fail_count == 0 else 1

    # Full extraction
    extractor = build_extractor(args)

    batch = extractor.extract_batch(
        input_dir=args.input,
        output_dir=args.output_dir,
        max_pages=args.max_pages,
    )

    return 0 if batch.failed == 0 else 1


def main() -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    log = logging.getLogger(__name__)
    log.info(f"PLATA Extract v{__version__} [{args.backend}]")

    input_path = args.input.resolve()

    if not input_path.exists():
        log.error(f"Input not found: {input_path}")
        return 1

    if input_path.is_file():
        return run_single(args)
    elif input_path.is_dir():
        return run_batch(args)
    else:
        log.error(f"Input is neither a file nor directory: {input_path}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
