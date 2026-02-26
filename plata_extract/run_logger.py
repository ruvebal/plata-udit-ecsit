"""
Run/file logging for PLATA Extract.

Writes:
  - Human-readable logs (run.log / extract.log)
  - Structured events (run.events.jsonl / extract.events.jsonl)
"""

from __future__ import annotations

import json
import platform
import shlex
import sys
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if is_dataclass(value):
        return _json_safe(asdict(value))
    return value


def _safe_env_subset() -> dict[str, str]:
    import os

    whitelist = (
        "TORCH_DEVICE",
        "OLLAMA_HOST",
        "OLLAMA_NUM_PARALLEL",
        "OLLAMA_KEEP_ALIVE",
        "PYTHONPATH",
    )
    data: dict[str, str] = {}
    for key in whitelist:
        val = os.environ.get(key)
        if val:
            data[key] = val
    return data


class _DualFileWriter:
    def __init__(
        self,
        text_path: Path,
        jsonl_path: Optional[Path],
    ) -> None:
        self.text_path = text_path
        self.jsonl_path = jsonl_path
        self.text_path.parent.mkdir(parents=True, exist_ok=True)
        self.text_path.touch(exist_ok=True)
        if self.jsonl_path is not None:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            self.jsonl_path.touch(exist_ok=True)

    def line(self, text: str) -> None:
        with self.text_path.open("a", encoding="utf-8") as f:
            f.write(f"{text}\n")

    def event(self, payload: dict[str, Any]) -> None:
        if self.jsonl_path is None:
            return
        with self.jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(_json_safe(payload), ensure_ascii=False) + "\n")


class ExtractionFileLogger:
    def __init__(
        self,
        writer: _DualFileWriter,
        run_id: str,
        backend: str,
        command_string: str,
        python_version: str,
        root_meta: dict[str, Any],
    ) -> None:
        self.writer = writer
        self.run_id = run_id
        self.backend = backend
        self.command_string = command_string
        self.python_version = python_version
        self.root_meta = root_meta
        self._started_at: Optional[datetime] = None

    def start(self, pdf_path: Path, output_dir: Path) -> None:
        self._started_at = datetime.now(timezone.utc)
        self.writer.line(f"Run ID: {self.run_id}")
        self.writer.line(f"Timestamp (UTC): {self._started_at.isoformat()}")
        self.writer.line(f"Backend: {self.backend}")
        self.writer.line(f"Command: {self.command_string}")
        self.writer.line(f"Input: {pdf_path}")
        self.writer.line(f"Output Dir: {output_dir}")
        self.writer.line(f"Python: {self.python_version}")
        self.writer.line("")
        self.writer.event({
            "event_type": "extract_started",
            "timestamp_utc": _now_iso(),
            "run_id": self.run_id,
            "backend": self.backend,
            "pdf_path": str(pdf_path),
            "output_dir": str(output_dir),
            **self.root_meta,
        })

    def check_result(
        self,
        pdf_path: Path,
        ok: bool,
        reason: Optional[str],
        page_count: Optional[int],
        file_size_mb: Optional[float],
    ) -> None:
        if ok:
            self.writer.line(
                f"Check: OK ({page_count} pages, {file_size_mb}MB)"
            )
        else:
            self.writer.line(f"Check: FAIL ({reason})")
        self.writer.event({
            "event_type": "pdf_check_completed",
            "timestamp_utc": _now_iso(),
            "run_id": self.run_id,
            "backend": self.backend,
            "pdf_path": str(pdf_path),
            "ok": ok,
            "reason": reason,
            "page_count": page_count,
            "file_size_mb": file_size_mb,
        })

    def warning(self, message: str) -> None:
        self.writer.line(f"Warning: {message}")
        self.writer.event({
            "event_type": "warning",
            "timestamp_utc": _now_iso(),
            "run_id": self.run_id,
            "backend": self.backend,
            "message": message,
        })

    def stage(self, name: str, elapsed_ms: int, extra: Optional[dict[str, Any]] = None) -> None:
        self.writer.line(f"Stage: {name} ({elapsed_ms} ms)")
        payload = {
            "event_type": "stage_completed",
            "timestamp_utc": _now_iso(),
            "run_id": self.run_id,
            "backend": self.backend,
            "stage_name": name,
            "elapsed_ms": elapsed_ms,
        }
        if extra:
            payload.update(extra)
        self.writer.event(payload)

    def complete(self, result: Any) -> None:
        self.writer.line("")
        if result.ok:
            if result.output_md:
                self.writer.line(f"  -> {result.output_md}")
            if result.output_images_dir and result.image_count > 0:
                self.writer.line(
                    f"  -> {result.output_images_dir} ({result.image_count} images)"
                )
            self.writer.line(
                f"  {result.word_count} words, {result.elapsed_seconds:.1f}s"
            )
            verdict = "SUCCESS"
        else:
            self.writer.line(f"Failed: {result.error}")
            verdict = "SKIPPED" if str(getattr(result, "error", "")).startswith("Skipped:") else "FAILED"

        elapsed_ms = int((result.elapsed_seconds or 0.0) * 1000)
        throughput = None
        if getattr(result, "ok", False) and elapsed_ms > 0:
            throughput = (
                (self.root_meta.get("page_count") or 0) / (elapsed_ms / 1000)
            ) if self.root_meta.get("page_count") else None

        self.writer.line(f"Verdict: {verdict}")
        if throughput is not None:
            self.writer.line(f"Throughput: {throughput:.3f} pages/sec")

        self.writer.event({
            "event_type": "extract_completed",
            "timestamp_utc": _now_iso(),
            "run_id": self.run_id,
            "backend": self.backend,
            "ok": bool(result.ok),
            "elapsed_ms": elapsed_ms,
            "word_count": getattr(result, "word_count", 0),
            "image_count": getattr(result, "image_count", 0),
            "output_md": str(result.output_md) if getattr(result, "output_md", None) else None,
            "output_images_dir": str(result.output_images_dir) if getattr(result, "output_images_dir", None) else None,
            "error": getattr(result, "error", None),
            "throughput_pages_per_sec": throughput,
            "stage_timings_ms": getattr(result, "stage_timings_ms", {}),
            "llm_requests": getattr(result, "llm_requests", None),
            "llm_tokens_used": getattr(result, "llm_tokens_used", None),
            "llm_errors": getattr(result, "llm_errors", None),
            "pages_processed": getattr(result, "pages_processed", None),
        })


class RunLogger:
    def __init__(
        self,
        backend: str,
        input_path: Path,
        output_dir: Path,
        argv: list[str],
        flags: dict[str, Any],
        enabled: bool = True,
        jsonl_enabled: bool = True,
        log_dir: Optional[Path] = None,
    ) -> None:
        self.enabled = enabled
        self.backend = backend
        self.input_path = Path(input_path).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.argv = argv
        self.flags = _json_safe(flags)
        self.run_id = str(uuid.uuid4())
        self.command_string = shlex.join(argv)
        self.python_version = sys.version.split()[0]
        self._jsonl_enabled = jsonl_enabled
        self._run_started_at: Optional[datetime] = None

        self._root_meta = {
            "plata_extract_version": flags.get("__version__", "unknown"),
            "python_version": self.python_version,
            "os_name": platform.system(),
            "os_version": platform.version(),
            "arch": platform.machine(),
            "command_argv": argv,
            "command_string": self.command_string,
            "flags": self.flags,
            "env_subset": _safe_env_subset(),
            "input_path": str(self.input_path),
            "output_dir": str(self.output_dir),
        }

        if not enabled:
            self._run_writer = None
            return

        base_dir = (
            Path(log_dir).resolve()
            if log_dir is not None
            else self.output_dir / "_runs" / self.run_id
        )
        self._run_writer = _DualFileWriter(
            text_path=base_dir / "run.log",
            jsonl_path=(base_dir / "run.events.jsonl") if jsonl_enabled else None,
        )

    def start(self) -> None:
        if not self.enabled or self._run_writer is None:
            return
        self._run_started_at = datetime.now(timezone.utc)
        self._run_writer.line(f"Run ID: {self.run_id}")
        self._run_writer.line(f"Timestamp (UTC): {self._run_started_at.isoformat()}")
        self._run_writer.line(f"Backend: {self.backend}")
        self._run_writer.line(f"Command: {self.command_string}")
        self._run_writer.line(f"Input: {self.input_path}")
        self._run_writer.line(f"Output Dir: {self.output_dir}")
        self._run_writer.line(f"Python: {self.python_version}")
        self._run_writer.line("")
        self._run_writer.event({
            "event_type": "run_started",
            "timestamp_utc": _now_iso(),
            "run_id": self.run_id,
            "backend": self.backend,
            **self._root_meta,
        })

    def complete(
        self,
        ok: bool,
        succeeded: Optional[int] = None,
        skipped: Optional[int] = None,
        failed: Optional[int] = None,
    ) -> None:
        if not self.enabled or self._run_writer is None:
            return
        end_time = datetime.now(timezone.utc)
        elapsed_ms = 0
        if self._run_started_at is not None:
            elapsed_ms = int((end_time - self._run_started_at).total_seconds() * 1000)
        verdict = "SUCCESS" if ok else "FAILED"
        self._run_writer.line(f"Verdict: {verdict}")
        if succeeded is not None:
            self._run_writer.line(
                f"Summary: succeeded={succeeded}, skipped={skipped or 0}, failed={failed or 0}"
            )
        self._run_writer.line(f"Elapsed: {elapsed_ms / 1000:.1f}s")
        self._run_writer.event({
            "event_type": "run_completed",
            "timestamp_utc": _now_iso(),
            "run_id": self.run_id,
            "backend": self.backend,
            "ok": ok,
            "elapsed_ms": elapsed_ms,
            "succeeded": succeeded,
            "skipped": skipped,
            "failed": failed,
        })

    def file_logger(
        self,
        pdf_path: Path,
        output_dir: Path,
        page_count: Optional[int] = None,
    ) -> Optional[ExtractionFileLogger]:
        if not self.enabled:
            return None
        pdf_path = Path(pdf_path).resolve()
        output_dir = Path(output_dir).resolve()
        doc_dir = output_dir / pdf_path.stem
        writer = _DualFileWriter(
            text_path=doc_dir / "extract.log",
            jsonl_path=(doc_dir / "extract.events.jsonl") if self._jsonl_enabled else None,
        )
        root_meta = dict(self._root_meta)
        root_meta["page_count"] = page_count
        return ExtractionFileLogger(
            writer=writer,
            run_id=self.run_id,
            backend=self.backend,
            command_string=self.command_string,
            python_version=self.python_version,
            root_meta=root_meta,
        )
