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
import os
import sys
from pathlib import Path
from typing import Union

from plata_extract import __version__
from plata_extract.check import check_pdf
from plata_extract.extract import PlatExtractor
from plata_extract.extract_plain import PlainExtractor
from plata_extract.extract_plain_docling import PlainDoclingExtractor
from plata_extract.run_logger import RunLogger


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
        "--torch-device",
        choices=["cpu", "mps", "cuda"],
        default=None,
        help=(
            "Force torch device for neural/docling models by setting TORCH_DEVICE "
            "(recommended when MPS is unstable: --torch-device cpu)."
        ),
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
        "--sanitize-for-neural",
        action="store_true",
        help=(
            "Normalize PDF (cap page dimensions) before neural extraction. "
            "Use if neural fails with index/Accelerator errors. Neural only."
        ),
    )

    parser.add_argument(
        "--force",
        "--rewrite",
        dest="overwrite",
        action="store_true",
        help="Overwrite existing output files for a document (default: skip if output exists).",
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
        "--no-log",
        action="store_true",
        help="Disable auto-generated run/extraction log files.",
    )

    parser.add_argument(
        "--no-log-jsonl",
        action="store_true",
        help="Disable structured JSONL event logs (keep human-readable logs).",
    )

    parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="Optional directory for run-level logs (default: OUTPUT_DIR/_runs/<RUN_ID>).",
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
            sanitize_for_neural=args.sanitize_for_neural,
            overwrite=args.overwrite,
        )

    if args.backend == "plain-docling":
        if args.sanitize_for_neural:
            logging.getLogger(__name__).warning(
                "--sanitize-for-neural is neural-only; ignoring for plain-docling."
            )
        if args.use_llm or args.llm_service is not None:
            logging.getLogger(__name__).warning(
                "--use-llm/--llm-service are neural-only options; "
                "ignoring for plain-docling backend."
            )
        if args.format != "markdown":
            logging.getLogger(__name__).warning(
                "--format is neural-only; plain-docling backend outputs markdown."
            )
        return PlainDoclingExtractor(force_ocr=args.force_ocr, overwrite=args.overwrite)

    if args.sanitize_for_neural:
        logging.getLogger(__name__).warning(
            "--sanitize-for-neural is neural-only; ignoring for plain backend."
        )
    if args.use_llm or args.llm_service is not None:
        logging.getLogger(__name__).warning(
            "--use-llm/--llm-service are neural-only options; ignoring for plain backend."
        )
    if args.format != "markdown":
        logging.getLogger(__name__).warning(
            "--format is neural-only; plain backend always outputs markdown."
        )

    return PlainExtractor(force_ocr=args.force_ocr, overwrite=args.overwrite)


def _args_snapshot(args: argparse.Namespace) -> dict:
    snap = vars(args).copy()
    for key, value in list(snap.items()):
        if isinstance(value, Path):
            snap[key] = str(value)
    snap["__version__"] = __version__
    return snap


def run_single(args: argparse.Namespace, run_logger: RunLogger) -> int:
    """Process a single PDF file."""
    pdf_path = args.input.resolve()
    file_log = run_logger.file_logger(pdf_path, args.output_dir)
    if file_log is not None:
        file_log.start(pdf_path=pdf_path, output_dir=args.output_dir.resolve())

    # Integrity check
    check = check_pdf(pdf_path)
    if file_log is not None:
        file_log.check_result(
            pdf_path=pdf_path,
            ok=check.ok,
            reason=check.reason,
            page_count=check.page_count,
            file_size_mb=check.file_size_mb,
        )
    if not check.ok:
        logging.getLogger(__name__).error(
            f"Cannot process {pdf_path.name}: {check.reason}"
        )
        if file_log is not None:
            class _Result:
                ok = False
                output_md = None
                output_images_dir = None
                image_count = 0
                word_count = 0
                elapsed_seconds = 0.0
                error = f"Skipped: {check.reason}"

            file_log.complete(_Result())
        return 1

    logging.getLogger(__name__).info(
        f"{pdf_path.name}: {check.page_count} pages, {check.file_size_mb}MB"
    )

    if args.check_only:
        logging.getLogger(__name__).info("Check passed.")
        if file_log is not None:
            class _Result:
                ok = True
                output_md = None
                output_images_dir = None
                image_count = 0
                word_count = 0
                elapsed_seconds = 0.0
                error = None

            file_log.complete(_Result())
        return 0

    # Extract
    extractor = build_extractor(args)

    result = extractor.extract_file(
        pdf_path, args.output_dir, max_pages=args.max_pages, file_log=file_log
    )

    if result.ok:
        log = logging.getLogger(__name__)
        log.info(f"  -> {result.output_md}")
        if result.image_count > 0:
            log.info(f"  -> {result.output_images_dir}/ ({result.image_count} images)")
        log.info(
            f"  {result.word_count} words, {result.elapsed_seconds:.1f}s"
        )
        if file_log is not None:
            file_log.complete(result)
        return 0
    else:
        if str(result.error or "").startswith("Skipped:"):
            logging.getLogger(__name__).warning(result.error)
            if file_log is not None:
                file_log.complete(result)
            return 0
        logging.getLogger(__name__).error(f"Failed: {result.error}")
        if file_log is not None:
            file_log.complete(result)
        return 1


def run_batch(args: argparse.Namespace, run_logger: RunLogger) -> tuple[int, dict]:
    """Process all PDFs in a directory."""
    if args.check_only:
        # Light check mode: no need to load marker models
        from plata_extract.check import list_pdfs

        pdfs = list_pdfs(args.input)
        log = logging.getLogger(__name__)

        if not pdfs:
            log.warning(f"No PDF files found in {args.input}")
            return 0, {"succeeded": 0, "skipped": 0, "failed": 0}

        ok_count = 0
        fail_count = 0

        for i, pdf in enumerate(pdfs, 1):
            file_log = run_logger.file_logger(pdf.resolve(), args.output_dir)
            if file_log is not None:
                file_log.start(pdf_path=pdf.resolve(), output_dir=args.output_dir.resolve())
            check = check_pdf(pdf)
            if file_log is not None:
                file_log.check_result(
                    pdf_path=pdf.resolve(),
                    ok=check.ok,
                    reason=check.reason,
                    page_count=check.page_count,
                    file_size_mb=check.file_size_mb,
                )
            status = "OK" if check.ok else f"FAIL ({check.reason})"
            pages = f"{check.page_count}p" if check.ok else ""
            log.info(f"[{i}/{len(pdfs)}] {pdf.name}: {status} {pages}")

            if check.ok:
                ok_count += 1
            else:
                fail_count += 1
            if file_log is not None:
                # Build a minimal result-like object for check-only mode.
                class _Result:
                    ok = check.ok
                    output_md = None
                    output_images_dir = None
                    image_count = 0
                    word_count = 0
                    elapsed_seconds = 0.0
                    error = None if check.ok else f"Skipped: {check.reason}"

                file_log.complete(_Result())

        log.info(f"\n{ok_count} OK, {fail_count} failed out of {len(pdfs)}")
        return (0 if fail_count == 0 else 1), {
            "succeeded": ok_count,
            "skipped": 0,
            "failed": fail_count,
        }

    # Full extraction
    extractor = build_extractor(args)

    batch = extractor.extract_batch(
        input_dir=args.input,
        output_dir=args.output_dir,
        max_pages=args.max_pages,
        run_logger=run_logger,
    )

    return (0 if batch.failed == 0 else 1), {
        "succeeded": batch.succeeded,
        "skipped": batch.skipped,
        "failed": batch.failed,
    }


def main() -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    log = logging.getLogger(__name__)
    log.info(f"PLATA Extract v{__version__} [{args.backend}]")

    # Must be set early so surya/marker/docling read it during import/config.
    if args.torch_device is not None:
        os.environ["TORCH_DEVICE"] = args.torch_device

    run_logger = RunLogger(
        backend=args.backend,
        input_path=args.input,
        output_dir=args.output_dir,
        argv=sys.argv,
        flags=_args_snapshot(args),
        enabled=not args.no_log,
        jsonl_enabled=not args.no_log_jsonl,
        log_dir=args.log_dir,
    )
    run_logger.start()

    input_path = args.input.resolve()

    if not input_path.exists():
        log.error(f"Input not found: {input_path}")
        run_logger.complete(ok=False)
        return 1

    exit_code = 1
    stats = None
    if input_path.is_file():
        exit_code = run_single(args, run_logger)
    elif input_path.is_dir():
        exit_code, stats = run_batch(args, run_logger)
    else:
        log.error(f"Input is neither a file nor directory: {input_path}")
        exit_code = 1
    if stats is not None:
        run_logger.complete(
            ok=exit_code == 0,
            succeeded=stats["succeeded"],
            skipped=stats["skipped"],
            failed=stats["failed"],
        )
    else:
        run_logger.complete(ok=exit_code == 0)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
